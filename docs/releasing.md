# Releasing

This is a monorepo with several independently-versioned images and charts, so
there is no single repo-wide release tag. Each component is released by
pushing a tag scoped to that component; only that component's workflow
fires.

All artifacts publish to GHCR under `ghcr.io/saltstack/salt-helm/...`
(GitHub Container Registry — public, no extra credentials to set up, and
already the pattern this project used before it moved into this monorepo).

## Docker images

Each image installs a pinned Salt version (`ARG SALT_VERSION`) plus, for the
two minion images, a pinned set of Salt extensions from PyPI
(`salt-extensions.txt`). **The release tag is an independent semver for the
image — it does not encode the Salt/extension versions.** Check each
component's own `CHANGELOG.md` for exactly what a given tag carries before
assuming.

| Component | Tag to push | Publishes to | Changelog |
| --- | --- | --- | --- |
| `docker/salt-master` | `salt-master-image/vX.Y.Z` | `ghcr.io/saltstack/salt-helm/salt-master:X.Y.Z` (and `:latest`) | [`docker/salt-master/CHANGELOG.md`](../docker/salt-master/CHANGELOG.md) |
| `salt-minion-vcf` | `salt-minion-vcf-image/vX.Y.Z` | `ghcr.io/saltstack/salt-helm/salt-minion-vcf:X.Y.Z` (and `:latest`) | [`salt-minion-vcf/CHANGELOG.md`](../salt-minion-vcf/CHANGELOG.md) |
| `salt-minion-kubernetes` | `salt-minion-kubernetes-image/vX.Y.Z` | `ghcr.io/saltstack/salt-helm/salt-minion-kubernetes:X.Y.Z` (and `:latest`) | [`salt-minion-kubernetes/CHANGELOG.md`](../salt-minion-kubernetes/CHANGELOG.md) |
| `salt-key-operator` | `salt-key-operator-image/vX.Y.Z` | `ghcr.io/saltstack/salt-helm/salt-key-operator:X.Y.Z` (and `:latest`) | [`salt-key-operator/CHANGELOG.md`](../salt-key-operator/CHANGELOG.md) |

Each release workflow refuses to publish unless the tag's version already
has a matching heading in that component's `CHANGELOG.md` — add the entry
(Salt version + extension versions) *before* tagging, not after:

```bash
# 1. Bump versions (Dockerfile ARG SALT_VERSION / salt-extensions.txt) if needed.
# 2. Add a "## salt-master-image/v1.0.1" heading to docker/salt-master/CHANGELOG.md.
# 3. Then:
git tag salt-master-image/v1.0.1
git push origin salt-master-image/v1.0.1
```

## Helm charts

Charts publish as OCI artifacts to the *same* registry, under a `charts/`
subpath — no separate `helm repo add` or `gh-pages` branch needed. The tag's
version must exactly match the chart's `version:` in `Chart.yaml`, and have a
matching `CHANGELOG.md` heading, or the release workflow fails before
pushing anything.

| Component | Tag to push | Publishes to | Changelog |
| --- | --- | --- | --- |
| `salt-master-kubernetes` | `salt-master-kubernetes-chart/vX.Y.Z` | `oci://ghcr.io/saltstack/salt-helm/charts/salt-master-kubernetes:X.Y.Z` | [`salt-master-kubernetes/CHANGELOG.md`](../salt-master-kubernetes/CHANGELOG.md) |
| `salt-minion-kubernetes` | `salt-minion-kubernetes-chart/vX.Y.Z` | `oci://ghcr.io/saltstack/salt-helm/charts/salt-minion-kubernetes:X.Y.Z` | [`salt-minion-kubernetes/CHANGELOG.md`](../salt-minion-kubernetes/CHANGELOG.md) |
| `salt-minion-vcf` (chart) | `salt-minion-vcf-chart/vX.Y.Z` | `oci://ghcr.io/saltstack/salt-helm/charts/salt-minion-vcf:X.Y.Z` | [`salt-minion-vcf/helm/salt-minion-vcf/CHANGELOG.md`](../salt-minion-vcf/helm/salt-minion-vcf/CHANGELOG.md) |
| `salt-key-operator` (chart) | `salt-key-operator-chart/vX.Y.Z` | `oci://ghcr.io/saltstack/salt-helm/charts/salt-key-operator:X.Y.Z` | [`salt-key-operator/helm/salt-key-operator/CHANGELOG.md`](../salt-key-operator/helm/salt-key-operator/CHANGELOG.md) |

```bash
# 1. Bump version: in the chart's Chart.yaml.
# 2. Add a "## salt-master-kubernetes-chart/v0.1.0" heading to its CHANGELOG.md
#    noting which image version it now defaults to.
# 3. Then:
git tag salt-master-kubernetes-chart/v0.1.0
git push origin salt-master-kubernetes-chart/v0.1.0
```

Installing a published chart:

```bash
helm install salt-master-kubernetes \
  oci://ghcr.io/saltstack/salt-helm/charts/salt-master-kubernetes \
  --version 1.0.0 \
  -f my-values.yaml
```

## First-time setup

GHCR packages created via `GITHUB_TOKEN` default to **private** on first
push. After the first release of each component, go to the package's
settings on GitHub (org → Packages) and set visibility to **public**, and
link it to this repository if it isn't already — otherwise consumers can't
`docker pull` / `helm pull` it anonymously.
