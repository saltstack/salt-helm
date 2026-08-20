# DEV/TEST ONLY - not for production or customer environments.
#
# Minimal Salt Master used solely to validate the POC flow locally:
#   build image -> start minion -> connect -> accept key -> test.ping
# without requiring a real customer-provided Salt Master.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG SALT_VERSION=3008.2

# Optional internal mirrors for air-gapped/restricted-network builds. See
# the main Dockerfile for details; these default to the public mirrors.
ARG APT_MIRROR=""
ARG SALT_GPG_KEY_URL="https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public"
ARG SALT_APT_REPO_URL="https://packages.broadcom.com/artifactory/saltproject-deb"

# See docker/apt/salt.sources for why this is vendored instead of curled
# from GitHub's release-assets CDN at build time.
COPY docker/apt/salt.sources /etc/apt/sources.list.d/salt.sources

RUN set -eu; \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    sed -i "s#^URIs: .*#URIs: ${SALT_APT_REPO_URL}#" /etc/apt/sources.list.d/salt.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tini \
    && mkdir -m 0755 -p /etc/apt/keyrings \
    && curl --retry 5 --retry-all-errors --retry-delay 2 -fsSL "${SALT_GPG_KEY_URL}" \
       | gpg --dearmor > /etc/apt/keyrings/salt-archive-keyring.pgp \
    && printf 'Package: salt-*\nPin: version 3008.*\nPin-Priority: 1001\n' \
       > /etc/apt/preferences.d/salt-pin-1001 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       "salt-common=${SALT_VERSION}" \
       "salt-master=${SALT_VERSION}" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/salt/master.d && cat > /etc/salt/master.d/dev.conf <<'EOF'
interface: 0.0.0.0
log_level: info
log_file: /dev/stdout
EOF

EXPOSE 4505 4506

VOLUME ["/etc/salt/pki/master"]

ENTRYPOINT ["/usr/bin/tini", "--", "salt-master", "-l", "info"]
