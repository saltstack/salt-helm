#!/bin/sh
set -eu

CONTAINER="${CONTAINER:-salt-minion-vcf}"

echo "Checking Salt version..."
docker exec "$CONTAINER" salt-call --local test.version

echo "Checking local Salt execution..."
docker exec "$CONTAINER" salt-call --local test.ping

echo "Installed Salt extension packages:"
docker exec "$CONTAINER" /bin/sh -c \
  "salt-pip freeze | grep -Ei '^(saltext[.-]|salt-ext|salt[-_].*extension)' || true"

echo "Checking Salt execution modules..."
docker exec "$CONTAINER" salt-call --local sys.list_modules >/dev/null

echo "Checking Salt state modules..."
docker exec "$CONTAINER" salt-call --local sys.list_state_modules >/dev/null

echo "Checking master connectivity..."
docker exec "$CONTAINER" salt-call status.master
