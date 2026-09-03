#!/bin/sh
set -eu

CONFIG_DIR=/etc/salt/minion.d
MASTER_CONFIG="${CONFIG_DIR}/10-master.conf"
RUNTIME_CONFIG="${CONFIG_DIR}/20-runtime.conf"
PILLAR_DIR=/etc/salt/pillar

mkdir -p "$CONFIG_DIR" /etc/salt/pki/minion /var/cache/salt/minion/.socks /var/log/salt "$PILLAR_DIR"

# Kubernetes StatefulSet pods receive a stable POD_NAME such as
# salt-minion-vcf-0. Use that as the default identity when no explicit ID is set.
if [ -z "${SALT_MINION_ID:-}" ]; then
  if [ -n "${POD_NAME:-}" ]; then
    SALT_MINION_ID="${POD_NAME}"
  else
    SALT_MINION_ID="${SALT_MINION_ID_PREFIX:-vcf-salt-executor}-${HOSTNAME}"
  fi
fi

# Pre-seed the minion's own RSA keypair when supplied. vcf-ops-onboard.py now
# generates this keypair and registers its public half as trusted via the
# VCF Operations API *before* the minion ever starts - so the minion must be
# handed that exact keypair rather than generating its own (which would not
# match whatever key was already registered as trusted, and would just sit
# untrusted). Independent of the master-side config model below (Docker/env
# or Kubernetes/ConfigMap+Secret) - either can supply these two variables.
#
# Only applied when minion.pem doesn't already exist, so a restarted/
# rescheduled container (persistent PKI volume) keeps its established
# identity rather than re-seeding on every start.
if [ ! -s /etc/salt/pki/minion/minion.pem ] \
    && [ -n "${SALT_MINION_PRIVATE_KEY_B64:-}" ] && [ -n "${SALT_MINION_PUBLIC_KEY_B64:-}" ]; then
  echo "${SALT_MINION_PRIVATE_KEY_B64}" | base64 -d > /etc/salt/pki/minion/minion.pem
  chmod 0400 /etc/salt/pki/minion/minion.pem
  echo "${SALT_MINION_PUBLIC_KEY_B64}" | base64 -d > /etc/salt/pki/minion/minion.pub
  chmod 0644 /etc/salt/pki/minion/minion.pub
  echo "Pre-seeded minion keypair (already registered as trusted)"
fi

# There are two supported configuration models:
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
EOF

  # Preferred: pre-seed the master's actual public key so the minion trusts
  # it directly on first connect, instead of independently re-deriving and
  # comparing a fingerprint (master_finger) against whatever key is presented
  # live - the two can disagree for reasons outside this image's control
  # (e.g. a management-plane key registry vs. what the wire protocol
  # presents), and this is also how VCF's own internal component minions are
  # bootstrapped - handed the master's public key directly, no fingerprint
  # verification. SALT_MASTER_PUBKEY_B64 takes precedence over the legacy
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

# FIPS-compliant crypto defaults: VCF-managed Salt masters run FIPS-validated
# crypto libraries that do not implement SHA-1 for RSA OAEP/PKCS1v15
# operations at all - a minion defaulting to SHA-1 doesn't get a clean
# protocol-level rejection from them, it triggers an unhandled exception on
# both sides ("Some exception handling minion payload" / "...a payload from
# minion") on every single auth attempt. These are the same values real
# VCF-managed minions use. Set SALT_FIPS_MODE=false only if your target
# master is confirmed to NOT be FIPS-enforced.
FIPS_CONFIG="${CONFIG_DIR}/15-fips.conf"
if [ "${SALT_FIPS_MODE:-true}" = "true" ]; then
  cat > "$FIPS_CONFIG" <<EOF
fips_mode: True
encryption_algorithm: ${SALT_ENCRYPTION_ALGORITHM:-OAEP-SHA224}
signing_algorithm: ${SALT_SIGNING_ALGORITHM:-PKCS1v15-SHA224}
EOF
fi

cat > "$RUNTIME_CONFIG" <<EOF
id: ${SALT_MINION_ID}
log_level: ${SALT_LOG_LEVEL}

# Route Salt's log file to stdout so 'docker logs'/'kubectl logs' capture
# minion activity instead of it being written only to /var/log/salt/minion.
log_file: /dev/stdout

# Keep the pidfile/IPC sockets under a path owned by the non-root minion
# user rather than the root-owned /var/run default.
pidfile: /var/cache/salt/minion/minion.pid
sock_dir: /var/cache/salt/minion/.socks

# Local pillar for saltext.vcf credentials (see pillar/*.sls.example). This
# only affects 'salt-call --local' invocations run inside this container -
# jobs dispatched from a real Salt Master use the Master's own pillar_roots
# and never see this directory.
pillar_roots:
  base:
    - ${PILLAR_DIR}

grains:
  vcf_executor: true
  deployment_type: ${DEPLOYMENT_TYPE:-docker}
  managed_by: salt-minion-vcf
  # VCF Operations' minion listing (GET /api/salt/minions) surfaces this as
  # resourceKind, read via a bulk get_minion_details grains lookup - it is
  # null until this grain is set and synced to the master, which is exactly
  # what this line does on every start of this image. "external" (rather
  # than a real component kind like vcenter/sddcm) reflects that this is a
  # generic, user-managed executor minion, not a VCF appliance component -
  # see vcf_grain_keys.py in config-modules for the full set of recognized
  # component kinds.
  vcfops_resource_kind: ${VCFOPS_RESOURCE_KIND:-external}
EOF

# Opt-in: make ALL pillar compiles (including those for jobs dispatched from
# a real Salt Master) resolve from this minion's own pillar_roots instead of
# asking the Master. UNVERIFIED beyond basic testing - validate
# 'salt <minion-id> pillar.items' and 'salt <minion-id> test.ping' from your
# real Master before relying on this. See README.md "Vault Integration".
if [ "${SALT_FILE_CLIENT_LOCAL:-false}" = "true" ]; then
  cat >> "$RUNTIME_CONFIG" <<EOF

file_client: local
EOF
fi

# Optional Vault integration (saltext.vault): configures the 'vault' auth/
# server block plus an sdb profile so pillar values can reference
# sdb://vault_sdb/<path>:<key> instead of containing plaintext secrets. See
# README.md "Vault Integration" for the full picture, including why this
# only keeps secrets off the Master when combined with SALT_FILE_CLIENT_LOCAL.
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

# Regenerate top.sls to match '*' against every *.sls file present in
# PILLAR_DIR (excluding top.sls itself), so pillar files can just be
# dropped in (mounted at start, or pushed via scripts/pillar-push.sh into
# an already-running container) without hand-authoring a top file. This
# container only ever runs a single Minion ID, so a wildcard match is
# always sufficient. Failure here (e.g. a read-only mount with its own
# top.sls already in place) is not fatal - that top.sls is used as-is.
{
  echo "base:"
  echo "  '*':"
  sls_found=0
  for f in "${PILLAR_DIR}"/*.sls; do
    [ -e "$f" ] || continue
    base="$(basename "$f" .sls)"
    [ "$base" = "top" ] && continue
    echo "    - ${base}"
    sls_found=1
  done
  [ "$sls_found" -eq 1 ] || echo "    []"
} > "${PILLAR_DIR}/top.sls" 2>/dev/null || true

# Optional customer-specific configuration can be mounted independently.
if [ -f "${CONFIG_DIR}/90-customer.conf" ]; then
  echo "Using customer configuration: ${CONFIG_DIR}/90-customer.conf"
fi

echo "===================================================="
echo " Salt Minion VCF"
echo "===================================================="
echo "Minion ID       : ${SALT_MINION_ID}"
echo "Minion Keypair  : $([ -n "${SALT_MINION_PRIVATE_KEY_B64:-}" ] && echo "pre-seeded (pre-registered as trusted)" || echo "self-generated on first start")"
echo "Deployment Type : ${DEPLOYMENT_TYPE:-docker}"
if [ -n "${SALT_MASTER:-}" ]; then
  echo "Salt Master     : ${SALT_MASTER}"
else
  echo "Salt Master     : configured by mounted ConfigMap"
fi
echo "Log Level       : ${SALT_LOG_LEVEL}"
echo "file_client     : $([ "${SALT_FILE_CLIENT_LOCAL:-false}" = "true" ] && echo local || echo remote)"
echo "FIPS Mode       : $([ "${SALT_FIPS_MODE:-true}" = "true" ] && echo "enabled (${SALT_ENCRYPTION_ALGORITHM:-OAEP-SHA224}/${SALT_SIGNING_ALGORITHM:-PKCS1v15-SHA224})" || echo disabled)"
echo "Vault           : $([ -n "${VAULT_ADDR:-}" ] && echo "${VAULT_ADDR}" || echo disabled)"
echo "===================================================="

exec salt-minion -l "${SALT_LOG_LEVEL}"
