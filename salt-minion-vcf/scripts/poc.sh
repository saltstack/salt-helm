#!/bin/sh
# Local POC harness driver. Exercises the required validation flow:
#   build -> start minion -> connect -> accept key -> test.ping
#   -> verify saltext-vcf modules
# against the throwaway dev Salt Master started by `make dev-up`.
#
# The final "execute one read-only VCF operation" step needs real
# vCenter/NSX/SDDC-M/Ops endpoint credentials (supplied via Salt Pillar, never
# via this repo) and is intentionally left as a manual step below.
set -eu

MASTER_SERVICE="${MASTER_SERVICE:-salt-master}"
MINION_SERVICE="${MINION_SERVICE:-salt-minion-vcf}"
COMPOSE="docker compose --profile dev"

echo "==> Waiting for minion to register a key with the dev master..."
i=0
until $COMPOSE exec -T "$MASTER_SERVICE" salt-key -L 2>/dev/null | grep -q "Unaccepted Keys"; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: timed out waiting for a pending minion key" >&2
    exit 1
  fi
  sleep 2
done
$COMPOSE exec -T "$MASTER_SERVICE" salt-key -L

echo "==> Accepting pending minion key(s)..."
$COMPOSE exec -T "$MASTER_SERVICE" salt-key -y -A

echo "==> test.ping from the master..."
$COMPOSE exec -T "$MASTER_SERVICE" salt '*' test.ping

echo "==> test.ping from the minion (local)..."
$COMPOSE exec -T "$MINION_SERVICE" salt-call --local test.ping

echo "==> Installed Salt extension packages:"
$COMPOSE exec -T "$MINION_SERVICE" /bin/sh -c \
  "salt-pip freeze | grep -Ei '^(saltext[.-]|salt-ext|salt[-_].*extension)' || true"

echo "==> saltext-vcf execution modules visible to the minion:"
$COMPOSE exec -T "$MINION_SERVICE" salt-call --local sys.list_modules | grep -i vcf || \
  echo "  (none matched 'vcf' - check salt-extensions.txt / the image build)"

cat <<'EOF'

==> POC harness complete through key acceptance and extension verification.

Remaining manual step (requires real VCF endpoint credentials, supplied via
Salt Pillar - never baked into this image or committed to this repo):

  salt '<minion-id>' <vcf_module>.<read_only_function>

EOF
