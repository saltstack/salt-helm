#!/bin/sh
# Push one or more local .sls files into an already-running salt-minion-vcf
# container's /etc/salt/pillar, then regenerate top.sls to match '*' against
# every .sls file present. No container restart is needed: 'salt-call
# --local' recompiles pillar from disk on every invocation.
#
# This only affects 'salt-call --local' inside the container. Jobs
# dispatched from a real Salt Master use the Master's own pillar_roots and
# never see this directory - see README.md for the Master-side setup.
#
# Usage: scripts/pillar-push.sh <container> <local-sls-file> [<local-sls-file> ...]
# Example: scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls
set -eu

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <container> <local-sls-file> [<local-sls-file> ...]" >&2
  exit 64
fi

CONTAINER="$1"
shift

for f in "$@"; do
  if [ ! -f "$f" ]; then
    echo >&2 "ERROR: no such file: $f"
    exit 66
  fi
  name="$(basename "$f")"
  echo "Pushing ${f} -> ${CONTAINER}:/etc/salt/pillar/${name}"
  docker exec -i "$CONTAINER" sh -c "cat > /etc/salt/pillar/${name}" < "$f"
done

echo "Regenerating top.sls inside ${CONTAINER}"
docker exec "$CONTAINER" sh -c '
PILLAR_DIR=/etc/salt/pillar
{
  echo "base:"
  echo "  '"'"'*'"'"':"
  sls_found=0
  for f in "$PILLAR_DIR"/*.sls; do
    [ -e "$f" ] || continue
    base="$(basename "$f" .sls)"
    [ "$base" = "top" ] && continue
    echo "    - $base"
    sls_found=1
  done
  [ "$sls_found" -eq 1 ] || echo "    []"
} > "$PILLAR_DIR/top.sls"
'

echo "Current pillar keys visible to salt-call --local:"
docker exec "$CONTAINER" salt-call --local pillar.items --out=json 2>/dev/null
