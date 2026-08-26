# syntax=docker/dockerfile:1
#
# Master-only counterpart to docker/salt-minion/Dockerfile. Deliberately
# minimal: unlike the minion, this image doesn't need saltext.kubernetes
# (execution/state modules run on minions, not the master) or kubectl (the
# master never talks to a cluster API directly), so it skips both.
FROM debian:12-slim

ARG SALT_VERSION=latest

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

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
