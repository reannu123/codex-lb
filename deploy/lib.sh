# shellcheck shell=bash
# Shared helpers for deploy/backup.sh, restore.sh and rehearse-migration.sh.
# Sourced, not executed. Every path and command can be overridden for tests.

DATA_DIR="${CODEX_LB_DATA_DIR:-/docker/appdata/codex-lb}"
BACKUP_ROOT="${CODEX_LB_BACKUP_ROOT:-/docker/backups/codex-lb}"
CONTAINER="${CODEX_LB_CONTAINER:-codex-lb}"
DOCKER="${DOCKER:-docker}"
PYTHON="${PYTHON:-python3}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY="${DEPLOY_DIR}/verify_backup.py"
# Database files that move together. store.db-shm is derived state and is
# never copied; a stale one next to a restored store.db is deleted.
DB_FILES=(store.db store.db-wal encryption.key)

log() { printf '%s\n' "$*" >&2; }
die() {
  printf '%s FAILED: %s\n' "${OPERATION:-deploy}" "$*" >&2
  exit 1
}

timestamp() { date -u +%Y%m%dT%H%M%SZ; }

take_lock() {
  [ -d "${BACKUP_ROOT}" ] || die "backup root ${BACKUP_ROOT} does not exist"
  exec 9>"${BACKUP_ROOT}/.lock"
  flock -n 9 || die "another backup, restore or rehearsal holds ${BACKUP_ROOT}/.lock"
}

container_running() {
  [ "$("${DOCKER}" inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null)" = "true" ]
}

container_image() {
  local image
  image="$("${DOCKER}" inspect -f '{{.Config.Image}}' "${CONTAINER}" 2>/dev/null)" || image=""
  printf '%s\n' "${image:-none}"
}

# Fail if any running container still bind-mounts the data directory.
require_data_dir_unmounted() {
  local id mounts
  for id in $("${DOCKER}" ps -q); do
    mounts="$("${DOCKER}" inspect -f '{{.Name}} {{range .Mounts}}{{.Source}} {{end}}' "${id}")"
    case " ${mounts} " in
      *" ${DATA_DIR} "*) die "running container ${mounts%% *} still mounts ${DATA_DIR}" ;;
    esac
  done
}

stop_app() {
  if container_running; then
    log "Stopping ${CONTAINER}..."
    "${DOCKER}" stop -t 60 "${CONTAINER}" >/dev/null || die "could not stop ${CONTAINER}"
  fi
  container_running && die "${CONTAINER} is still running"
  require_data_dir_unmounted
}

# Resolve a backup name (not a path) to its verified directory.
backup_dir() {
  local name="$1"
  case "${name}" in
    "" | */* | .* | *.partial | *.failed) die "invalid backup name '${name}'" ;;
  esac
  [ -f "${BACKUP_ROOT}/${name}/manifest.json" ] || die "${BACKUP_ROOT}/${name} is not a completed backup"
  printf '%s\n' "${BACKUP_ROOT}/${name}"
}

# Checksums are always verified from inside the directory they describe.
verify_checksums() {
  (cd "$1" && sha256sum --strict --quiet -c SHA256SUMS) || die "checksum mismatch in $1"
}

present_db_files() {
  local dir="$1" name
  for name in "${DB_FILES[@]}"; do
    [ -e "${dir}/${name}" ] && printf '%s\n' "${name}"
  done
  return 0
}
