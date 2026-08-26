#!/usr/bin/env bash
set -euo pipefail

CONF_DIR=/etc/salt/minion.d
mkdir -p "$CONF_DIR"

{
    [ -z "${SALT_MASTER:-}" ] || printf 'master: %s\n' "$SALT_MASTER"
    [ -z "${SALT_MASTER_PORT:-}" ] || printf 'master_port: %s\n' "$SALT_MASTER_PORT"
    [ -z "${SALT_PUBLISH_PORT:-}" ] || printf 'publish_port: %s\n' "$SALT_PUBLISH_PORT"
    [ -z "${SALT_MINION_ID:-}" ] || printf 'id: %s\n' "$SALT_MINION_ID"
} > "$CONF_DIR/99-env.conf"

if [ $# -eq 0 ]; then
    exec salt-minion -l info
fi

exec "$@"
