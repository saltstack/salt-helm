# Building From Source

Most users don't need this — the published images and charts on GHCR (see
the main [`README.md`](../README.md)) are the fastest path to a working
deployment. Build from source instead when you need a patched/local image,
a Salt version other than what's published, or an air-gapped build with no
route to GHCR.

## Prerequisites

- Docker (or another OCI builder) for the images
- Helm 3+ for the charts

## Docker images

Each image is self-contained (pip-installed Salt extensions from PyPI rather
than a checkout of the extension's own repo, where applicable), so all three
build directly from this repo with that image's own directory as the build
context:

```bash
docker build -t salt-master:3008.2 docker/salt-master
docker build -t salt-minion-vcf:0.1.0 salt-minion-vcf
docker build -t salt-minion-kubernetes:0.1.0 salt-minion-kubernetes
```

See each image's own README for the full build-arg reference (Salt version,
extension selection, internal PyPI/apt mirrors for air-gapped builds, etc.):

- [`docker/salt-master/README.md`](../docker/salt-master/README.md)
- [`salt-minion-vcf/README.md`](../salt-minion-vcf/README.md)
- [`salt-minion-kubernetes/README.md`](../salt-minion-kubernetes/README.md)

### Running a locally-built image

`salt-minion-vcf` also runs as a plain Docker container or via Docker
Compose, without Kubernetes — see
[`salt-minion-vcf/README.md`](../salt-minion-vcf/README.md) for the full
guide, including the local Vault-backed testing workflow:

```bash
docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=salt-master.example.com \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  salt-minion-vcf:0.1.0
```

or with Docker Compose:

```bash
cd salt-minion-vcf
cp .env.example .env   # set SALT_MASTER, etc.
docker compose up -d --build
```

### Getting a locally-built image onto a cluster

- **With a registry:** tag and push, then point the chart's
  `agent.image.repository`/`image.repository` value at your registry path.
- **Without a registry** (air-gapped/test clusters): `docker save` the image
  and `ctr -n k8s.io images import` it directly into every node's containerd
  store, then set `image.pullPolicy: Never` (or `agent.image.pullPolicy`) so
  Kubernetes doesn't try to pull.

## Helm charts

The charts themselves need no build step — install straight from a checkout
of this repo:

```bash
helm install salt-master-kubernetes ./salt-master-kubernetes -f my-values.yaml
helm install salt-minion-kubernetes ./salt-minion-kubernetes -f my-values.yaml
helm install salt-minion-vcf ./salt-minion-vcf/helm/salt-minion-vcf \
  --set salt.master=salt-master.example.com
```

Remember to also point each chart's image value at whatever you built above
(the charts otherwise default to either the published GHCR image or an
unqualified local tag — check `values.yaml`).

To produce a distributable `.tgz` instead (e.g. for your own chart repo or
registry):

```bash
helm package salt-master-kubernetes
helm package salt-minion-kubernetes
helm package salt-minion-vcf/helm/salt-minion-vcf
```

## Cutting an actual release

Building locally doesn't publish anything. To push a build to
`ghcr.io/saltstack/salt-kubernetes/...` under a real version tag, see
[`docs/releasing.md`](releasing.md).
