#!/usr/bin/env bash
# Boot an image with a throwaway data dir and require /health/ready within 120s.
set -euo pipefail
image="$1"
name="fork-ci-boot-$$"
docker run -d --name "${name}" -p 127.0.0.1:2455:2455 "${image}" >/dev/null
trap 'docker logs "${name}" 2>&1 | tail -n 80; docker rm -f "${name}" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:2455/health/ready >/dev/null 2>&1; then
    echo "container ready"
    curl -fsS http://127.0.0.1:2455/ -o /dev/null && echo "dashboard served"
    exit 0
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "${name}")" != "true" ]; then
    echo "::error::container exited before becoming ready"
    exit 1
  fi
  sleep 2
done
echo "::error::container not ready within 120s"
exit 1
