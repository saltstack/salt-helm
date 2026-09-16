# hadolint ignore=DL3009
# syntax=docker/dockerfile:1
#
# Self-contained Salt minion image for salt-minion-kubernetes: core Salt plus
# saltext.vault and saltext.kubernetes, both pip-installed from PyPI (same
# pattern as salt-minion-vcf/Dockerfile) rather than requiring a checkout of
# any extension's own repo as build context.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
# Pinned rather than "latest" so a given salt-minion-kubernetes-image release
# tag reproducibly carries one specific Salt version - see CHANGELOG.md.
ARG SALT_VERSION=3008.2

# Bundles kubectl directly into the image so the salt-minion-kubernetes chart
# can skip its install-kubectl init container (agent.kubectl.bundled: true).
ARG INCLUDE_KUBECTL=true
ARG KUBECTL_VERSION=v1.30.2
ARG TARGETARCH

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

LABEL org.opencontainers.image.title="Salt Minion Kubernetes"
LABEL org.opencontainers.image.description="Salt Minion runtime preloaded with saltext.vault and saltext.kubernetes, for RBAC-driven kube-bench compliance assessments"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# salt.sources is vendored from the salt-install-guide release rather than
# curled at build time - see salt-minion-vcf/docker/apt/salt.sources for why
# (intermittent cert-chain failures on Linux/OpenSSL clients).


RUN set -eu; \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    mkdir -p /etc/apt/sources.list.d && curl -fslL https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources -o /etc/apt/sources.list.d/salt.sources; \


# ca-certificates/curl/gnupg/tini/iproute2/dnsutils/netcat-openbsd are OS
# packages that should track the latest security patches from Ubuntu's own
# release channel rather than being frozen at build time - only Salt's own
# packages are version-pinned (SALT_VERSION), just below.
# hadolint ignore=DL3008,DL3009,SC2174
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tini iproute2 dnsutils netcat-openbsd \
    && mkdir -m 755 -p /etc/apt/keyrings \
    && curl -fsSL https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public -o /tmp/salt-archive-keyring.asc \
    && gpg --dearmor -o /etc/apt/keyrings/salt-archive-keyring.pgp /tmp/salt-archive-keyring.asc \
    && rm -f /tmp/salt-archive-keyring.asc \
    && printf 'Package: salt-*\nPin: version 3008.*\nPin-Priority: 1001\n' \
       > /etc/apt/preferences.d/salt-pin-1001 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       "salt-common=${SALT_VERSION}" \
       "salt-minion=${SALT_VERSION}" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# Install any Salt extension packages listed by the image builder.
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

# Bundled so this image needs no separate init container to reach the
# Kubernetes API - see salt-minion-kubernetes/values.yaml (agent.kubectl.bundled).
RUN if [ "$INCLUDE_KUBECTL" = "true" ]; then \
        set -eu; \
        curl -fsSL -o /usr/local/bin/kubectl \
            "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl"; \
        curl -fsSL -o /tmp/kubectl.sha256 \
            "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256"; \
        printf '%s  /usr/local/bin/kubectl\n' "$(cat /tmp/kubectl.sha256)" \
            > /tmp/kubectl.sha256.check; \
        sha256sum -c /tmp/kubectl.sha256.check; \
        chmod +x /usr/local/bin/kubectl; \
        rm -f /tmp/kubectl.sha256 /tmp/kubectl.sha256.check; \
    fi

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh

# Non-root: run as the 'salt' system user/group salt-common's own postinst
# already created (rather than inventing a separate one), and own
# everything the minion writes to at runtime. This image only calls the
# Kubernetes API via its mounted ServiceAccount token, so it never needs
# root inside the container.
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
    SALT_MASTER_FINGER="" \
    SALT_LOG_LEVEL="info" \
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
