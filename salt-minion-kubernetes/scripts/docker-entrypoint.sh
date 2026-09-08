#!/bin/sh
set -eu

CONFIG_DIR=/etc/salt/minion.d
MASTER_CONFIG="${CONFIG_DIR}/10-master.conf"
RUNTIME_CONFIG="${CONFIG_DIR}/20-runtime.conf"

mkdir -p "$CONFIG_DIR" /etc/salt/pki/minion /var/cache/salt/minion/.socks /var/log/salt

# Kubernetes Deployment pods get a random pod name (no stable identity like a
# StatefulSet's), so fall back to the container hostname when no explicit ID
# is set.
if [ -z "${SALT_MINION_ID:-}" ]; then
  if [ -n "${POD_NAME:-}" ]; then
    SALT_MINION_ID="${POD_NAME}"
  else
    SALT_MINION_ID="$(hostname)"
  fi
fi

# Two supported configuration models, same as salt-minion-vcf's entrypoint:
#   1. Docker/env: SALT_MASTER is supplied and this script writes master config.
#   2. Kubernetes/ConfigMap: 10-master.conf is mounted by Kubernetes/Helm.
if [ -n "${SALT_MASTER:-}" ]; then
  case "${SALT_MASTER_PORT:-4506}" in
    *[!0-9]*|'') echo >&2 "ERROR: SALT_MASTER_PORT must be numeric"; exit 64 ;;
  esac
  case "${SALT_PUBLISH_PORT:-4505}" in
    *[!0-9]*|'') echo >&2 "ERROR: SALT_PUBLISH_PORT must be numeric"; exit 64 ;;
  esac

  cat > "$MASTER_CONFIG" <<EOF
master: ${SALT_MASTER}
master_port: ${SALT_MASTER_PORT}
publish_port: ${SALT_PUBLISH_PORT}
master_tries: -1
retry_dns: 30
auth_timeout: ${SALT_AUTH_TIMEOUT:-60}
master_alive_interval: ${SALT_MASTER_ALIVE_INTERVAL:-60}
recon_default: ${SALT_RECON_DEFAULT:-1000}
recon_max: ${SALT_RECON_MAX:-5000}
recon_randomize: ${SALT_RECON_RANDOMIZE:-True}
EOF

  # Preferred: pre-seed the master's actual public key so the minion trusts
  # it directly on first connect, instead of independently re-deriving and
  # comparing a fingerprint (master_finger) against whatever key is presented
  # live. SALT_MASTER_PUBKEY_B64 takes precedence over the legacy
  # SALT_MASTER_FINGER when both are set.
  if [ -n "${SALT_MASTER_PUBKEY_B64:-}" ]; then
    echo "${SALT_MASTER_PUBKEY_B64}" | base64 -d > /etc/salt/pki/minion/minion_master.pub
  elif [ -n "${SALT_MASTER_FINGER:-}" ]; then
    cat >> "$MASTER_CONFIG" <<EOF
master_finger: '${SALT_MASTER_FINGER}'
EOF
  fi
elif [ ! -s "$MASTER_CONFIG" ]; then
  echo >&2 "ERROR: Salt Master configuration is missing."
  echo >&2 "Provide SALT_MASTER or mount ${MASTER_CONFIG} (Kubernetes ConfigMap)."
  exit 64
fi

# FIPS-compliant crypto defaults - see salt-minion-vcf/scripts/docker-entrypoint.sh
# for the full rationale (masters running FIPS-validated crypto don't
# implement SHA-1 for RSA OAEP/PKCS1v15, which breaks auth with a minion
# defaulting to it). Set SALT_FIPS_MODE=false only if your target master is
# confirmed to NOT be FIPS-enforced.
FIPS_CONFIG="${CONFIG_DIR}/15-fips.conf"
if [ "${SALT_FIPS_MODE:-true}" = "true" ]; then
  cat > "$FIPS_CONFIG" <<EOF
fips_mode: True
encryption_algorithm: ${SALT_ENCRYPTION_ALGORITHM:-OAEP-SHA224}
signing_algorithm: ${SALT_SIGNING_ALGORITHM:-PKCS1v15-SHA224}
EOF
fi

# Deliberately does NOT set pillar_roots or touch /srv/pillar: the
# salt-minion-kubernetes chart's kube_bench.sls ConfigMap is consumed via the
# Master's own pillar_roots (see chart README "kube-bench coordination"), not
# a local pillar tree - unlike salt-minion-vcf, which is meant to run
# disconnected enough to need one.
cat > "$RUNTIME_CONFIG" <<EOF
id: ${SALT_MINION_ID}
log_level: ${SALT_LOG_LEVEL:-info}

# Route Salt's log file to stdout so 'kubectl logs' captures minion activity
# instead of it being written only to /var/log/salt/minion.
log_file: /dev/stdout

pidfile: /var/cache/salt/minion/minion.pid
sock_dir: /var/cache/salt/minion/.socks

grains:
  managed_by: salt-minion-kubernetes
EOF

# Optional Vault integration (saltext.vault): configures the 'vault' auth/
# server block plus an sdb profile so pillar values can reference
# sdb://vault_sdb/<path>:<key> instead of containing plaintext secrets. Same
# shape as salt-minion-vcf/scripts/docker-entrypoint.sh.
if [ -n "${VAULT_ADDR:-}" ]; then
  if [ -n "${VAULT_SECRET_ID_FILE:-}" ] && [ -f "${VAULT_SECRET_ID_FILE}" ]; then
    VAULT_SECRET_ID="$(cat "${VAULT_SECRET_ID_FILE}")"
  fi
  if [ -n "${VAULT_TOKEN_FILE:-}" ] && [ -f "${VAULT_TOKEN_FILE}" ]; then
    VAULT_TOKEN="$(cat "${VAULT_TOKEN_FILE}")"
  fi

  {
    echo ""
    echo "vault:"
    echo "  server:"
    echo "    url: ${VAULT_ADDR}"
    echo "  auth:"
    if [ "${VAULT_AUTH_METHOD:-approle}" = "token" ]; then
      echo "    method: token"
      echo "    token: '${VAULT_TOKEN:-}'"
    else
      echo "    method: approle"
      echo "    role_id: '${VAULT_ROLE_ID:-}'"
      if [ -n "${VAULT_SECRET_ID:-}" ]; then
        echo "    secret_id: '${VAULT_SECRET_ID}'"
      fi
    fi
    echo ""
    echo "${VAULT_SDB_PROFILE:-vault_sdb}:"
    echo "  driver: vault"
  } >> "$RUNTIME_CONFIG"
fi

echo "===================================================="
echo " Salt Minion Kubernetes"
echo "===================================================="
echo "Minion ID   : ${SALT_MINION_ID}"
if [ -n "${SALT_MASTER:-}" ]; then
  echo "Salt Master : ${SALT_MASTER}"
else
  echo "Salt Master : configured by mounted ConfigMap"
fi
echo "Log Level   : ${SALT_LOG_LEVEL:-info}"
echo "FIPS Mode   : $([ "${SALT_FIPS_MODE:-true}" = "true" ] && echo "enabled (${SALT_ENCRYPTION_ALGORITHM:-OAEP-SHA224}/${SALT_SIGNING_ALGORITHM:-PKCS1v15-SHA224})" || echo disabled)"
echo "Vault       : $([ -n "${VAULT_ADDR:-}" ] && echo "${VAULT_ADDR}" || echo disabled)"
echo "===================================================="

exec salt-minion -l "${SALT_LOG_LEVEL:-info}"
