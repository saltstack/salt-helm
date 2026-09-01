FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG SALT_VERSION=3008.2

# Optional additional extension packages, space-separated.
# Prefer salt-extensions.txt for reproducible builds.
ARG EXTRA_SALT_EXTENSIONS=""

# Optional corporate/internal PyPI mirror configuration, needed when the build
# host cannot reach public PyPI directly (e.g. behind an Artifactory proxy).
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""
ARG PIP_ONLY_BINARY=""

# Optional internal mirrors for air-gapped/restricted-network builds. Leave
# empty to use the public defaults (Ubuntu's own mirrors, Broadcom's public
# Artifactory).
ARG APT_MIRROR=""
ARG SALT_GPG_KEY_URL="https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public"
ARG SALT_APT_REPO_URL="https://packages.broadcom.com/artifactory/saltproject-deb"

LABEL org.opencontainers.image.title="Salt Minion VCF"
LABEL org.opencontainers.image.description="Portable Salt Minion runtime with configurable Salt extensions for VMware Cloud Foundation automation"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# salt.sources is vendored from the salt-install-guide release rather than
# curled at build time: its actual download URL redirects through
# release-assets.githubusercontent.com, whose CDN edges intermittently omit
# an intermediate certificate that Linux/OpenSSL clients (unlike macOS/Windows)
# won't auto-fetch via AIA, causing random build failures. Refresh this file
# from https://github.com/saltstack/salt-install-guide/releases if Salt
# changes its packaging config.
COPY docker/apt/salt.sources /etc/apt/sources.list.d/salt.sources

# Point apt at internal mirrors when APT_MIRROR/SALT_APT_REPO_URL are set
# (air-gapped/restricted-network builds); otherwise these are no-ops that
# leave the public defaults in place.
RUN set -eu; \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    sed -i "s#^URIs: .*#URIs: ${SALT_APT_REPO_URL}#" /etc/apt/sources.list.d/salt.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tini iproute2 dnsutils netcat-openbsd \
    && mkdir -m 0755 -p /etc/apt/keyrings \
    && curl --retry 5 --retry-all-errors --retry-delay 2 -fsSL "${SALT_GPG_KEY_URL}" \
       | gpg --dearmor > /etc/apt/keyrings/salt-archive-keyring.pgp \
    && printf 'Package: salt-*\nPin: version 3008.*\nPin-Priority: 1001\n' \
       > /etc/apt/preferences.d/salt-pin-1001 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       "salt-common=${SALT_VERSION}" \
       "salt-minion=${SALT_VERSION}" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install any Salt extension packages listed by the image builder.
# This deliberately does not hard-code saltext-vcf into the Dockerfile.
# PIP_INDEX_URL/PIP_TRUSTED_HOST/PIP_ONLY_BINARY are only unset when empty so
# pip is not handed a literal empty --index-url.
COPY salt-extensions.txt /tmp/salt-extensions.txt
RUN set -eu; \
    if [ -z "${PIP_INDEX_URL}" ]; then unset PIP_INDEX_URL; fi; \
    if [ -z "${PIP_TRUSTED_HOST}" ]; then unset PIP_TRUSTED_HOST; fi; \
    if [ -z "${PIP_ONLY_BINARY}" ]; then unset PIP_ONLY_BINARY; fi; \
    if grep -Eq '^[[:space:]]*[^#[:space:]]' /tmp/salt-extensions.txt; then \
      salt-pip install --no-cache-dir -r /tmp/salt-extensions.txt; \
    fi; \
    if [ -n "${EXTRA_SALT_EXTENSIONS:-}" ]; then \
      salt-pip install --no-cache-dir ${EXTRA_SALT_EXTENSIONS}; \
    fi; \
    rm -f /tmp/salt-extensions.txt

# Dedicated non-root identity. saltext-vcf makes remote API calls against
# vCenter/NSX/SDDC-M/Ops rather than managing local host state, so the minion
# does not need root inside the container.
RUN groupadd -g 10000 saltminion \
    && useradd -u 10000 -g saltminion -M -s /usr/sbin/nologin saltminion

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh

RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh \
    && mkdir -p /etc/salt/minion.d /etc/salt/pki/minion /etc/salt/pillar \
                /var/cache/salt/minion /var/log/salt \
    && chown -R saltminion:saltminion /etc/salt /var/cache/salt /var/log/salt

ENV SALT_MASTER="" \
    SALT_MASTER_PORT="4506" \
    SALT_PUBLISH_PORT="4505" \
    SALT_MASTER_PUBKEY_B64="" \
    SALT_MINION_ID="" \
    SALT_MINION_ID_PREFIX="vcf-salt-executor" \
    SALT_MINION_PRIVATE_KEY_B64="" \
    SALT_MINION_PUBLIC_KEY_B64="" \
    SALT_MASTER_FINGER="" \
    SALT_LOG_LEVEL="info" \
    SALT_FILE_CLIENT_LOCAL="false" \
    VAULT_ADDR="" \
    VAULT_AUTH_METHOD="approle" \
    VAULT_ROLE_ID="" \
    VAULT_SECRET_ID="" \
    VAULT_SECRET_ID_FILE="" \
    VAULT_TOKEN="" \
    VAULT_TOKEN_FILE="" \
    VAULT_SDB_PROFILE="vault_sdb"

USER saltminion

VOLUME ["/etc/salt/pki/minion"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
