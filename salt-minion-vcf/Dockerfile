# hadolint ignore=DL3009
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
ARG SALT_GPG_KEY_URL
ARG SALT_APT_REPO_URL

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


# Point apt at internal mirrors when APT_MIRROR/SALT_APT_REPO_URL are set
# (air-gapped/restricted-network builds); otherwise these are no-ops that
# leave the public defaults in place.
RUN set -eu; \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \


# ca-certificates/curl/gnupg/tini/iproute2/dnsutils/netcat-openbsd are OS
# packages that should track the latest security patches from Ubuntu's own
# release channel rather than being frozen at build time - only Salt's own
# packages are version-pinned (SALT_VERSION), just below.
# hadolint ignore=DL3008,DL3009,SC2174
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tini iproute2 dnsutils netcat-openbsd \
    && mkdir -p /etc/apt/keyrings \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    curl -fsSL -o /tmp/bootstrap-salt.sh https://github.com/saltstack/salt-bootstrap/releases/latest/download/bootstrap-salt.sh; \
    curl -fsSL -o /tmp/bootstrap-salt.sh.sha256 https://github.com/saltstack/salt-bootstrap/releases/latest/download/bootstrap-salt.sh.sha256; \
    printf '%s  /tmp/bootstrap-salt.sh\n' "$(cut -d' ' -f1 /tmp/bootstrap-salt.sh.sha256)" > /tmp/bootstrap-salt.sh.sha256.check; \
    sha256sum -c /tmp/bootstrap-salt.sh.sha256.check; \
    if [ "$SALT_VERSION" = "latest" ]; then \
        sh /tmp/bootstrap-salt.sh -X -P onedir; \
    else \
        sh /tmp/bootstrap-salt.sh -X -P onedir "$SALT_VERSION"; \
    fi; \
    rm -f /tmp/bootstrap-salt.sh /tmp/bootstrap-salt.sh.sha256 /tmp/bootstrap-salt.sh.sha256.check


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

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh

# Non-root: run as the 'salt' system user/group salt-common's own postinst
# already created (rather than inventing a separate one), and own
# everything the minion writes to at runtime. saltext-vcf makes remote API
# calls against vCenter/NSX/SDDC-M/Ops rather than managing local host
# state, so the minion never needs root inside the container.
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh \
    && mkdir -p /etc/salt/minion.d /etc/salt/pki/minion /etc/salt/pillar \
                /var/cache/salt/minion /var/log/salt \
    && chown -R salt:salt /etc/salt /var/cache/salt /var/log/salt

# These are empty placeholder defaults meant to be supplied at container
# start (env var or Kubernetes Secret) - not secrets baked into the image.
# hadolint ignore=DL3064
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

# Numeric, not the name: Kubernetes' runAsNonRoot check can't resolve a
# named USER without executing code inside the image, and refuses to start
# the container at all ("cannot verify user is non-root") if it can't. 999
# is what salt-common's own postinst allocates the 'salt' user/group in
# this build (verify with `id salt` if the base image or install order
# ever changes).
USER 999:999

VOLUME ["/etc/salt/pki/minion"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
