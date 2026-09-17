# Changelog (salt-key-operator chart)

Records what each `salt-key-operator-chart/vX.Y.Z` release tag (see
[`docs/releasing.md`](../../docs/releasing.md)) defaults to. The chart's own
version is independent of the image version it happens to default to —
check here, not the tag number.

## salt-key-operator-chart/v0.1.0
- Default image: `salt-key-operator:0.1.0` (see
  [`../CHANGELOG.md`](../CHANGELOG.md) for what that image version carries).
- Installs the `SaltMinionKey` CRD (`crds/salt.saltstack.io_saltminionkeys.yaml`).
- Deliberately lightweight defaults: `replicas: 1`, `leaderElection.enabled: false`,
  20m/32Mi resource requests - no control-plane HA for a controller that
  does nothing but occasionally patch one ConfigMap per namespace.
- `watchNamespace: salt-master` by default, matching
  `salt-master-kubernetes`'s own default namespace - scopes RBAC to a
  namespaced `Role`/`RoleBinding` in just that namespace rather than a
  cluster-wide `ClusterRole`. Recommended install: same namespace as the
  target `salt-master-kubernetes` release (`helm install ... -n salt-master`).
