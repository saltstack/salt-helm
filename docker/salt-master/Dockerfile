# syntax=docker/dockerfile:1
#
# Master-only counterpart to the salt-minion-vcf/salt-minion-kubernetes
# minion images. Deliberately minimal: unlike either minion variant, this
# image doesn't need any Salt extensions (execution/state modules run on
# minions, not the master) or kubectl (the master never talks to a cluster
# API directly), so it skips both.
FROM debian:12-slim

# Pinned rather than "latest" so a given salt-master-image release tag
# reproducibly carries one specific Salt version - see CHANGELOG.md.
ARG SALT_VERSION=3008.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Salt's official bootstrap script, install type "onedir": fetches the same
# self-contained onedir tarball salt-ci-containers uses directly, without
# provisioning an apt repo + GPG key just to unpack it. -X skips starting any
# daemon at install time; the entrypoint starts salt-master as PID 1 instead.
# -N skips installing/configuring the minion service (this image is
# master-only); -M installs the master service, which the bootstrap script
# does not do by default.
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
        sh /tmp/bootstrap-salt.sh -X -N -M -P onedir; \
    else \
        sh /tmp/bootstrap-salt.sh -X -N -M -P onedir "$SALT_VERSION"; \
    fi; \
    rm -f /tmp/bootstrap-salt.sh /tmp/bootstrap-salt.sh.sha256

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Non-root: the onedir bootstrap install doesn't reliably create a system
# 'salt' user the way the Debian/Ubuntu apt packages do (that's a distro
# packaging postinst step, not part of the onedir tarball), so create one
# ourselves if it isn't already there, then own everything the master
# writes to at runtime. Pinned to uid/gid 999 (matching what salt-common's
# own postinst allocates in the apt-based minion images, empirically) -
# USER below must be numeric, not the name, or Kubernetes' runAsNonRoot
# check can't verify it without resolving /etc/passwd inside the image,
# and refuses to start the container at all ("cannot verify user is
# non-root").
RUN id salt >/dev/null 2>&1 || useradd --system --uid 999 --no-create-home --shell /usr/sbin/nologin salt; \
    mkdir -p /etc/salt/pki/master /var/cache/salt/master /var/run/salt/master /var/log/salt; \
    chown -R salt:salt /etc/salt /var/cache/salt /var/run/salt /var/log/salt

USER 999:999

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
