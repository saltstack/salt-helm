#!/usr/bin/env bash
set -euo pipefail

CONF_DIR=/etc/salt/master.d
mkdir -p "$CONF_DIR"

{
    [ -z "${SALT_AUTO_ACCEPT:-}" ] || printf 'auto_accept: %s\n' "$SALT_AUTO_ACCEPT"
    [ -z "${SALT_MASTER_ID:-}" ] || printf 'id: %s\n' "$SALT_MASTER_ID"

    # Fires salt/presence/present (and /change) events on the event bus so
    # `salt-run manage.present`/`manage.status` reflect which minions are
    # actually connected right now - useful in Kubernetes, where minion pods
    # come and go independently of their accepted-key status.
    printf 'presence_events: %s\n' "${SALT_PRESENCE_EVENTS:-True}"

    # Keep pidfile/sock_dir off /var/run: the container runtime remounts
    # /run fresh (root-owned, 0755) on every pod start regardless of what's
    # baked into the image, so a non-root master can never mkdir under
    # /var/run/salt/master - same reasoning/pattern as
    # salt-minion-vcf/scripts/docker-entrypoint.sh's pidfile/sock_dir.
    printf 'pidfile: /var/cache/salt/master/master.pid\n'
    printf 'sock_dir: /var/cache/salt/master/.socks\n'
} > "$CONF_DIR/99-env.conf"

# Optional: pre-seed the master's own keypair (e.g. generated and registered
# with RaaS/the minion side out-of-band, then handed to this container as a
# Secret) instead of letting salt-master generate one on first start. Only
# applied when master.pem doesn't already exist, so a restarted/rescheduled
# container (persistent PKI volume) keeps its established identity rather
# than re-seeding on every start.
PKI_DIR=/etc/salt/pki/master
mkdir -p "$PKI_DIR"

if [ ! -s "$PKI_DIR/master.pem" ] \
    && [ -n "${SALT_MASTER_PRIVATE_KEY_B64:-}" ] && [ -n "${SALT_MASTER_PUBLIC_KEY_B64:-}" ]; then
    mkdir -p "$PKI_DIR"
    echo "${SALT_MASTER_PRIVATE_KEY_B64}" | base64 -d > "$PKI_DIR/master.pem"
    chmod 0400 "$PKI_DIR/master.pem"
    echo "${SALT_MASTER_PUBLIC_KEY_B64}" | base64 -d > "$PKI_DIR/master.pub"
    chmod 0644 "$PKI_DIR/master.pub"
    echo "Pre-seeded master keypair"
fi

mkdir -p /var/cache/salt/master/.socks

if [ $# -eq 0 ]; then
    exec salt-master -l info
fi

exec "$@"
