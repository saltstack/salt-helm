# Changelog (salt-master-kubernetes chart)

Records what each `salt-master-kubernetes-chart/vX.Y.Z` release tag (see
[`docs/releasing.md`](../docs/releasing.md)) defaults to. The chart's own version is independent
of the image version it happens to default to — check here, not the tag number.

## salt-master-kubernetes-chart/v0.1.0
- Default image: `salt-master:1.0.0` (`appVersion` in `Chart.yaml`) — see
  [`../docker/salt-master/CHANGELOG.md`](../docker/salt-master/CHANGELOG.md) for what that image
  version carries. Chart default `agent.image.repository` is still the unqualified local name
  `salt-master` (see `values.yaml`), not this published tag.
