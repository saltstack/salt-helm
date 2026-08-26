#!/usr/bin/env bash
set -euo pipefail

CONF_DIR=/etc/salt/master.d
mkdir -p "$CONF_DIR"

{
    [ -z "${SALT_AUTO_ACCEPT:-}" ] || printf 'auto_accept: %s\n' "$SALT_AUTO_ACCEPT"
    [ -z "${SALT_MASTER_ID:-}" ] || printf 'id: %s\n' "$SALT_MASTER_ID"
} > "$CONF_DIR/99-env.conf"

if [ $# -eq 0 ]; then
    exec salt-master -l info
fi

exec "$@"
