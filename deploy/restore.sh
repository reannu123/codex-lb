#!/usr/bin/env bash
# Restore a named backup made by deploy/backup.sh into the production data dir.
#
#   deploy/restore.sh BACKUP_NAME [--yes]
#
# Re-verifies the backup (checksums, integrity_check, row counts against its
# manifest), stops the codex-lb container, moves the current store.db,
# store.db-wal, store.db-shm and encryption.key aside to
# BACKUP_ROOT/pre-restore-<UTC timestamp>/, copies the backup in and checks the
# restored bytes. It leaves the container STOPPED: start the image recorded in
# the backup's manifest.json (migrations are one-way; a newer image would
# migrate the restored store again).
set -euo pipefail
OPERATION=RESTORE
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

name="${1:-}"
[ -n "${name}" ] || die "usage: restore.sh BACKUP_NAME [--yes]"
assume_yes=false
[ "${2:-}" = "--yes" ] && assume_yes=true

take_lock
src="$(backup_dir "${name}")"
log "Verifying ${src}..."
verify_checksums "${src}"
"${PYTHON}" "${VERIFY}" check "${src}" >/dev/null
image="$("${PYTHON}" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("image","unknown"))' "${src}/manifest.json")"

if ! "${assume_yes}"; then
  [ -t 0 ] || die "refusing to restore without --yes on a non-interactive shell"
  printf 'This replaces %s with %s. Type the backup name to continue: ' "${DATA_DIR}" "${name}" >&2
  read -r answer
  [ "${answer}" = "${name}" ] || die "confirmation did not match"
fi

stop_app
aside="${BACKUP_ROOT}/pre-restore-$(timestamp)"
mkdir -m 700 "${aside}"
for file in store.db store.db-wal store.db-shm encryption.key; do
  if [ -e "${DATA_DIR}/${file}" ]; then
    mv "${DATA_DIR}/${file}" "${aside}/${file}"
  fi
done
log "Moved the current files aside to ${aside}"

mapfile -t files < <(present_db_files "${src}")
for file in "${files[@]}"; do
  cp -p "${src}/${file}" "${DATA_DIR}/${file}"
done
(cd "${DATA_DIR}" && sha256sum --strict --quiet -c "${src}/SHA256SUMS") || die "restored files do not match ${src}/SHA256SUMS"

log "RESTORE OK: ${name} -> ${DATA_DIR} (container left stopped)"
log "  Next: deploy the backup's image, then verify /health/ready: ${image}"
