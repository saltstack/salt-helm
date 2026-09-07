# Changelog (salt-minion-kubernetes)

Image and chart in this directory publish under separate release tags (see
[`docs/releasing.md`](../docs/releasing.md)) but neither tag encodes the Salt/extension
versions it carries — check here.

## Image releases (`salt-minion-kubernetes-image/vX.Y.Z`)

### salt-minion-kubernetes-image/v0.1.0
- Salt: 3008.2
- Extensions: saltext.kubernetes==2.1.0, saltext.vault==1.8.0
- Base: ubuntu:24.04
- Bundles: kubectl v1.30.2

## Chart releases (`salt-minion-kubernetes-chart/vX.Y.Z`)

### salt-minion-kubernetes-chart/v0.1.0
- Default image: `salt-minion-kubernetes:0.1.0` (see "Image releases" above for what that
  version carries)
