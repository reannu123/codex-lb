#!/usr/bin/env bash
# Print the registry manifest digest of an image reference; print nothing if
# the registry says it does not exist. Any other failure exits non-zero, so a
# transient registry or auth error can never look like "absent" (fail closed).
set -uo pipefail
ref="$1"
if ! out=$(docker buildx imagetools inspect "${ref}" --format '{{json .Manifest}}' 2>&1); then
  if grep -qiE 'not found|manifest unknown|name unknown|NAME_UNKNOWN|MANIFEST_UNKNOWN' <<<"${out}"; then
    exit 0
  fi
  echo "registry lookup failed for ${ref}: ${out}" >&2
  exit 2
fi
digest=$(jq -r '.digest // empty' <<<"${out}" 2>/dev/null)
if [[ ! "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "unexpected manifest for ${ref}" >&2
  exit 2
fi
printf '%s\n' "${digest}"
