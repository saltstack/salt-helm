# Changelog (salt-minion)

Image and chart in this directory publish under separate release tags (see
[`docs/releasing.md`](../docs/releasing.md)) but neither tag encodes the Salt/extension
versions it carries — check here.

## Image releases (`salt-minion-image/vX.Y.Z`)

### salt-minion-image/v0.1.1
- Salt: 3008.2
- Extensions: saltext.kubernetes==2.1.0, saltext.vault==1.8.0
- Base: ubuntu:24.04
- Bundles: kubectl v1.30.2
- `docker-entrypoint.sh` now (a) pre-seeds the minion's own keypair from
  `SALT_MINION_PRIVATE_KEY_B64`/`SALT_MINION_PUBLIC_KEY_B64` if present -
  previously this image had no such mechanism at all, unlike
  `salt-minion-vcf` - and (b) renders a comma-separated `SALT_MASTER` as a
  YAML list (Salt's native multi-master mode). No change to the Salt/
  extension versions above.

### salt-minion-image/v0.1.0
- Salt: 3008.2
- Extensions: saltext.kubernetes==2.1.0, saltext.vault==1.8.0
- Base: ubuntu:24.04
- Bundles: kubectl v1.30.2

## Chart releases (`salt-minion-chart/vX.Y.Z`)

### salt-minion-chart/v1.0.0
**Breaking - defaults change on `helm upgrade` from any prior release:**
- `agent.minion.keySecretName` is now **required** - the chart fails fast
  otherwise. Set `agent.minion.allowSelfGeneratedKey: true` to explicitly
  opt back into the old self-generated-keypair behavior.
  `agent.persistence.enabled` was already `false` by default - no change
  there, but a self-generated key now needs that explicit opt-out too, not
  just an empty `keySecretName`.
- `agent.saltMasterHost` now also accepts a YAML list, for Salt's native
  [multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html) -
  point it at every replica address of an active-active
  `salt-master-kubernetes` release instead of a single master.
- Default image: `salt-minion:0.1.1` (see "Image releases" above for what that
  version carries)

### salt-minion-chart/v0.1.0
- Default image: `salt-minion:0.1.0` (see "Image releases" above for what that
  version carries)
