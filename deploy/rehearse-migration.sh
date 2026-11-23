#!/usr/bin/env bash
# Rehearse a new image's database migrations against a throwaway copy of a backup.
#
#   deploy/rehearse-migration.sh IMAGE [BACKUP_NAME]
#
# IMAGE is the candidate, ideally pinned: ghcr.io/reannu123/codex-lb@sha256:...
# BACKUP_NAME defaults to the newest completed backup in BACKUP_ROOT. The backup
# is re-verified, copied to BACKUP_ROOT/.rehearsal.*, and the image runs only
# `python -m app.db.migrate` (current, upgrade, check) on that copy in a
# container with no network, a read-only root filesystem and no app server, so
# no scheduler, warm-up or upstream call can run. The migrated copy must pass
# integrity_check. The copy and the container are always deleted afterwards;
# production data and the production container are never touched.
set -euo pipefail
OPERATION=REHEARSAL
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

image="${1:-}"
[ -n "${image}" ] || die "usage: rehearse-migration.sh IMAGE [BACKUP_NAME]"
case "${image}" in *@sha256:*) ;; *) log "warning: ${image} is not pinned by digest" ;; esac

take_lock
name="${2:-}"
if [ -z "${name}" ]; then
  name="$("${PYTHON}" - "${BACKUP_ROOT}" <<'EOF'
import json, sys
from pathlib import Path
done = [
    (json.loads(manifest.read_text())["created_at"], manifest.parent.name)
    for manifest in Path(sys.argv[1]).glob("*/manifest.json")
    if not manifest.parent.name.startswith(".")
    and not manifest.parent.name.endswith((".partial", ".failed"))
]
print(max(done)[1] if done else "")
EOF
)"
  [ -n "${name}" ] || die "no completed backup in ${BACKUP_ROOT}; run deploy/backup.sh first"
fi
src="$(backup_dir "${name}")"
log "Verifying ${src}..."
verify_checksums "${src}"

scratch="$(mktemp -d "${BACKUP_ROOT}/.rehearsal.XXXXXX")"
runner="codex-lb-rehearsal-$$"
cleanup() {
  local status=$?
  "${DOCKER}" rm -f "${runner}" >/dev/null 2>&1 || true
  rm -rf "${scratch}"
  [ "${status}" -eq 0 ] || log "REHEARSAL FAILED (exit ${status}); the throwaway copy was deleted"
  exit "${status}"
}
trap cleanup EXIT

mapfile -t files < <(present_db_files "${src}")
for file in "${files[@]}"; do
  cp "${src}/${file}" "${scratch}/${file}"
done

migrate() {
  "${DOCKER}" run --rm --name "${runner}" --pull missing \
    --network none --read-only --tmpfs /tmp \
    --user "$(id -u):$(id -g)" \
    -e CODEX_LB_DATA_DIR=/var/lib/codex-lb \
    -e CODEX_LB_DATABASE_SQLITE_PRE_MIGRATE_BACKUP_ENABLED=false \
    -v "${scratch}:/var/lib/codex-lb" \
    --entrypoint python "${image}" -m app.db.migrate "$@"
}

before="$(migrate current | tail -n 1)" || die "the image could not read the copy's revision"
log "Backup ${name}: revision ${before}"
migrate upgrade || die "migrations failed on the copy of ${name}"
after="$(migrate current | tail -n 1)" || die "could not read the migrated revision"
migrate check || die "migrated schema fails the image's policy/drift check"

"${PYTHON}" "${VERIFY}" snapshot "${scratch}" --in-place >"${scratch}/.after.json"
"${PYTHON}" - "${src}/manifest.json" "${scratch}/.after.json" <<'EOF'
import json, sys
old, new = (json.load(open(path))["counts"] for path in sys.argv[1:])
for table in sorted(set(old) | set(new)):
    if old.get(table) != new.get(table):
        print(f"  rows {table}: {old.get(table, 'absent')} -> {new.get(table, 'absent')}", file=sys.stderr)
EOF

log "REHEARSAL OK: ${image}"
log "  ${name}: ${before} -> ${after}"
