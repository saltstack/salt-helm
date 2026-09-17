#!/usr/bin/env bash
# Verify that required Salt extensions are present in the container image.
# Expected extensions are listed in extensions.yaml (or salt-extensions.txt).
# Usage: docker run --rm <image> /scripts/check-extensions.sh /etc/extensions.yaml

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <extensions.yaml>"
  exit 2
fi

EXT_FILE="$1"
required=(extension-a extension-b extension-c)

missing=()
for ext in "${required[@]}"; do
  if ! grep -q "${ext}" "$EXT_FILE"; then
    missing+=("$ext")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing required extensions: ${missing[*]}"
  exit 1
fi

echo "All required extensions are present"
exit 0
