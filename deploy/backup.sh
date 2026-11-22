#!/usr/bin/env bash
# Back up the production SQLite store and encryption key, verified offline.
#
#   deploy/backup.sh [--label LABEL] [--leave-stopped]
#
# Stops the codex-lb container, copies store.db (+ store.db-wal if present) and
# encryption.key into BACKUP_ROOT/[LABEL-]<UTC timestamp>/, proves the copy is
# byte-identical (sha256), runs integrity_check and row counts on a scratch copy,
# writes SHA256SUMS + manifest.json, then restarts the container if it was
# running (unless --leave-stopped). Any failure prints "BACKUP FAILED", exits
# non-zero and leaves the attempt as <name>.failed; it is never a valid backup.
set -euo pipefail
OPERATION=BACKUP
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

label=""
leave_stopped=false
while [ $# -gt 0 ]; do
  case "$1" in
    --label) label="${2:-}"; shift 2 ;;
    --leave-stopped) leave_stopped=true; shift ;;
    *) die "usage: backup.sh [--label LABEL] [--leave-stopped]" ;;
  esac
done
if [ -n "${label}" ] && ! [[ "${label}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  die "label must match [A-Za-z0-9][A-Za-z0-9._-]*"
fi

[ -f "${DATA_DIR}/store.db" ] || die "${DATA_DIR}/store.db not found"
take_lock
name="${label:+${label}-}$(timestamp)"
dest="${BACKUP_ROOT}/${name}"
partial="${dest}.partial"
[ -e "${dest}" ] || [ -e "${partial}" ] && die "${dest} already exists"

was_running=false
container_running && was_running=true
image="$(container_image)"

finish() {
  local status=$?
  if [ "${status}" -ne 0 ] && [ -d "${partial}" ]; then
    mv "${partial}" "${dest}.failed" && log "Left the failed attempt at ${dest}.failed"
  fi
  if "${was_running}" && ! "${leave_stopped}"; then
    log "Starting ${CONTAINER} again..."
    "${DOCKER}" start "${CONTAINER}" >/dev/null || { log "BACKUP: could not restart ${CONTAINER}"; status=1; }
  fi
  [ "${status}" -eq 0 ] || log "BACKUP FAILED (exit ${status})"
  exit "${status}"
}
trap finish EXIT

stop_app
mkdir -m 700 "${partial}"
mapfile -t files < <(present_db_files "${DATA_DIR}")
case " ${files[*]} " in *" encryption.key "*) ;; *) die "${DATA_DIR}/encryption.key not found" ;; esac

# Checksum the source while the app is stopped, copy, then prove the copy matches.
(cd "${DATA_DIR}" && sha256sum "${files[@]}") >"${partial}/SHA256SUMS"
for file in "${files[@]}"; do
  cp -p "${DATA_DIR}/${file}" "${partial}/${file}"
done
verify_checksums "${partial}"

"${PYTHON}" "${VERIFY}" snapshot "${partial}" \
  --meta "created_at=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)" \
  --meta "image=${image}" \
  --meta "data_dir=${DATA_DIR}" >"${partial}/manifest.json.tmp"
mv "${partial}/manifest.json.tmp" "${partial}/manifest.json"
verify_checksums "${partial}"

mv "${partial}" "${dest}"
log "BACKUP OK: ${dest}"
log "  schema: $("${PYTHON}" -c 'import json,sys; print(",".join(json.load(open(sys.argv[1]))["schema"]))' "${dest}/manifest.json")"
log "  image:  ${image}"
printf '%s\n' "${name}"
