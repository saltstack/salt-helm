# Changelog (salt-minion-vcf chart)

Records what each `salt-minion-vcf-chart/vX.Y.Z` release tag (see
[`docs/releasing.md`](../../../docs/releasing.md)) defaults to. The chart's own version is
independent of the image version it happens to default to — check here, not the tag number.

## salt-minion-vcf-chart/v1.0.0
**Breaking - defaults change on `helm upgrade` from any prior release:**
- `salt.minionKeySecretName` is now **required** for both `workload.kind`
  values (`StatefulSet` and `Deployment`) - the chart fails fast otherwise.
  Set `salt.allowSelfGeneratedKey: true` to explicitly opt back into the old
  self-generated-keypair behavior.
- `persistence.enabled` default flipped `true` → `false`: once a keypair is
  always pre-seeded, there's nothing generated-then-persisted left to
  protect - the minion is fully stateless by default. Set `enabled: true`
  alongside `salt.allowSelfGeneratedKey: true` if you need a
  self-generated keypair to survive pod restarts.
- `salt.master` now also accepts a YAML list, for Salt's native
  [multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html) -
  point it at every replica address of an active-active
  `salt-master-kubernetes` release instead of a single master.
- Default image: `salt-minion-vcf:0.1.1` (see
  [`../../CHANGELOG.md`](../../CHANGELOG.md) for what that image version carries)

## salt-minion-vcf-chart/v0.1.0
- Default image: `salt-minion-vcf:0.1.1` (see
  [`../../CHANGELOG.md`](../../CHANGELOG.md) for what that image version carries)
