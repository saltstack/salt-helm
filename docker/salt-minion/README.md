# Salt minion image

A Salt minion Docker image built from the official onedir distribution via Salt's
[bootstrap script](https://github.com/saltstack/salt-bootstrap), with `kubectl` bundled and this
repo's own `saltext.kubernetes` (including any local, not-yet-released changes) installed by
default. Design rationale lives in
[`specs/docker-salt-minion-image.md`](../../specs/docker-salt-minion-image.md).

## Build

The build context is the **repo root** (not this directory), since the image needs
`pyproject.toml`/`setup.py`/`src/` to install `saltext.kubernetes` from the local working tree:

```bash
docker build -f docker/salt-minion/Dockerfile -t salt-minion .
```

Build args:

| Arg | Default | Purpose |
| --- | --- | --- |
| `SALT_VERSION` | `latest` | Salt version to install, e.g. `3007.1`. `latest` installs the newest stable onedir release. |
| `INCLUDE_KUBECTL` | `true` | Set to `false` to skip bundling `kubectl`. |
| `KUBECTL_VERSION` | `v1.36.3` | `kubectl` version to bundle, when included. |
| `SALTEXT_KUBERNETES_VERSION` | `0+unknown` | Version string recorded for the installed `saltext.kubernetes` (its `setup.py` needs `.git` to derive one otherwise, which the build deliberately doesn't copy in). Must be a valid [PEP 440](https://peps.python.org/pep-0440/) version — `git describe`'s raw output (e.g. `v2.1.0-dirty`) isn't one; see the command below for the transform. |
| `PIP_INDEX_URL` | unset (pip's normal default, i.e. public PyPI) | Override to route `saltext.kubernetes`'s install — including its build deps and transitive runtime deps like `kubernetes` — through an internal mirror, e.g. when public PyPI isn't reachable from behind a VPN/proxy. |
| `PIP_TRUSTED_HOST` | unset | Pair with `PIP_INDEX_URL` — the mirror's hostname, so pip doesn't warn/fail on it. |
| `PIP_ONLY_BINARY` | unset | Pair with `PIP_INDEX_URL` if the mirror only serves wheels — set to `:all:` to force wheel-only installs (this image has no compiler toolchain to build from sdist anyway). |

Broadcom-internal builds (this repo's own CI): the working combination, matching the one already
used in `saltstack-raas/cicd/build-rpm.sh`, is

```bash
docker build -f docker/salt-minion/Dockerfile \
  --build-arg SALT_VERSION=3007.1 \
  --build-arg SALTEXT_KUBERNETES_VERSION="$(git describe --tags --always --dirty | sed -E 's/^v//; s/-/+/')" \
  --build-arg PIP_INDEX_URL=https://packages.vcfd.broadcom.net/artifactory/api/pypi/upstream-pypi-virtual/simple \
  --build-arg PIP_TRUSTED_HOST=packages.vcfd.broadcom.net \
  --build-arg PIP_ONLY_BINARY=:all: \
  -t salt-minion:3007.1 .
```

## Run

```bash
docker run --rm -e SALT_MASTER=salt.example.com -e SALT_MINION_ID=my-minion salt-minion
```

Environment variables (translated into `/etc/salt/minion.d/99-env.conf` at container start):

| Variable | Effect |
| --- | --- |
| `SALT_MASTER` | Sets `master:` in the minion config. |
| `SALT_MASTER_PORT` | Sets `master_port:` (the "ret" channel, default `4506`). |
| `SALT_PUBLISH_PORT` | Sets `publish_port:` (the "publish" channel, default `4505`). Needed alongside `SALT_MASTER_PORT` whenever the master isn't reachable on its default ports as-is — e.g. behind a Kubernetes NodePort Service, where both ports are remapped. |
| `SALT_MINION_ID` | Sets `id:`. Defaults to the container hostname if unset. |

Mount additional config, pillar, or state trees the same way `helm/salt-minion-kubernetes` does
today, e.g. `-v ./pillar:/srv/pillar:ro`.

With no arguments, the entrypoint starts `salt-minion` in the foreground as PID 1. Passing an
explicit command instead (as in the smoke test below) runs that command in the container instead
of the minion.

## Smoke test

```bash
docker run --rm salt-minion:3007.1 salt-call --local test.ping
docker run --rm salt-minion:3007.1 kubectl version --client
docker run --rm salt-minion:3007.1 salt-call --local sys.list_functions kube_bench_cache
```
