# syntax=docker/dockerfile:1
#
# See specs/docker-salt-minion-image.md for the design rationale behind the
# choices below (base image, install method, version-pinning, kubectl bundling).
FROM debian:12-slim

ARG SALT_VERSION=latest
ARG INCLUDE_KUBECTL=true
ARG KUBECTL_VERSION=v1.36.3
ARG SALTEXT_KUBERNETES_VERSION=0+unknown
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ARG PIP_ONLY_BINARY=
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tar \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Salt's official bootstrap script, install type "onedir": fetches the same
# self-contained onedir tarball salt-ci-containers uses directly, without
# provisioning an apt repo + GPG key just to unpack it. -X skips starting the
# minion daemon at install time; the entrypoint starts it as PID 1 instead.
#
# bootstrap.saltproject.io was decommissioned in Jan 2025; the script now
# ships as a GitHub release asset of saltstack/salt-bootstrap instead.
RUN set -eu; \
    curl -fsSL -o /tmp/bootstrap-salt.sh \
        https://github.com/saltstack/salt-bootstrap/releases/latest/download/bootstrap-salt.sh; \
    curl -fsSL -o /tmp/bootstrap-salt.sh.sha256 \
        https://github.com/saltstack/salt-bootstrap/releases/latest/download/bootstrap-salt.sh.sha256; \
    (cd /tmp && sha256sum -c bootstrap-salt.sh.sha256); \
    if [ "$SALT_VERSION" = "latest" ]; then \
        sh /tmp/bootstrap-salt.sh -X -P onedir; \
    else \
        sh /tmp/bootstrap-salt.sh -X -P onedir "$SALT_VERSION"; \
    fi; \
    rm -f /tmp/bootstrap-salt.sh /tmp/bootstrap-salt.sh.sha256

# This repo's own saltext.kubernetes, installed from the local working tree
# (not PyPI) so unreleased changes are always reflected -- via salt-pip, the
# onedir bundle's own pip entrypoint, exactly as docs/topics/installation.md
# documents for onedir installs. setup.py's use_scm_version=True needs .git
# to derive a version, which we deliberately don't COPY in; pass one from
# the host/CI instead (see docker/salt-minion/README.md).
#
# PIP_INDEX_URL/PIP_TRUSTED_HOST/PIP_ONLY_BINARY let this (and its
# transitive/build deps, e.g. kubernetes, setuptools_scm) be resolved through
# an internal mirror when public PyPI isn't reachable -- e.g. behind a VPN
# that breaks TLS to pythonhosted.org's CDN. All three default unset, so pip
# falls back to its normal defaults (public PyPI, sdist-or-wheel).
#
# --no-build-isolation on the second install: onedir's Python (built via
# relenv) ships its own sitecustomize.py that manipulates sys.path, which
# crashes (`assert not path in sys.path`) inside pip's build-isolation
# subprocess. Installing the build-time deps directly first (they ship as
# prebuilt wheels, so this doesn't invoke build isolation at all) and then
# installing saltext.kubernetes without isolation avoids that code path.
COPY pyproject.toml setup.py /opt/build/saltext-kubernetes/
COPY src /opt/build/saltext-kubernetes/src
RUN set -eu; \
    [ -n "${PIP_INDEX_URL:-}" ] || unset PIP_INDEX_URL; \
    [ -n "${PIP_TRUSTED_HOST:-}" ] || unset PIP_TRUSTED_HOST; \
    [ -n "${PIP_ONLY_BINARY:-}" ] || unset PIP_ONLY_BINARY; \
    salt-pip install --disable-pip-version-check \
        wheel "setuptools>=50.3.2" "setuptools_scm[toml]>=3.4"; \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SALTEXT_KUBERNETES="$SALTEXT_KUBERNETES_VERSION" \
        salt-pip install --disable-pip-version-check --no-build-isolation \
            /opt/build/saltext-kubernetes; \
    rm -rf /opt/build

# Bundled so this image can stand in for saltstack/salt in
# helm/salt-minion-kubernetes without that chart's kubectl init container.
RUN if [ "$INCLUDE_KUBECTL" = "true" ]; then \
        set -eu; \
        curl -fsSL -o /usr/local/bin/kubectl \
            "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl"; \
        curl -fsSL -o /tmp/kubectl.sha256 \
            "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256"; \
        echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum -c -; \
        chmod +x /usr/local/bin/kubectl; \
        rm -f /tmp/kubectl.sha256; \
    fi

COPY docker/salt-minion/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
