# Changelog (salt-master-kubernetes chart)

Records what each `salt-master-kubernetes-chart/vX.Y.Z` release tag (see
[`docs/releasing.md`](../docs/releasing.md)) defaults to. The chart's own version is independent
of the image version it happens to default to — check here, not the tag number.

## salt-master-kubernetes-chart/v1.0.0
**Breaking - requires a fresh install, not `helm upgrade`, from any prior release:**
- `kind: Deployment` → `kind: StatefulSet` (`templates/deployment.yaml` removed, replaced
  by `templates/statefulset.yaml`). Kubernetes cannot reconcile a Deployment-owned release
  into StatefulSet manifests of the same name in place.
- New `templates/service-headless.yaml` (`clusterIP: None`) for in-cluster per-ordinal DNS,
  and optional `templates/service-per-ordinal.yaml` (`service.perOrdinal.enabled`) for
  external per-ordinal NodePort access. The existing flat `templates/service.yaml` is
  unchanged in shape but its `clusterIP`/type semantics can still conflict with a prior
  release's Service object on `helm upgrade` - reinstall rather than upgrade regardless.
- `agent.persistence.*` (PKI persistence) removed entirely - `agent.masterKeySecretName`
  is now the only supported way to give the master a stable identity, and is **required**
  when `agent.replicas > 1` (the chart fails fast otherwise). Replaced by
  `agent.jobCache.persistence.*`, a separate per-replica PVC (via `volumeClaimTemplates`)
  for the master's job/event cache only (`/var/cache/salt/master/jobs`) - an operational
  concern, decoupled from identity, which no longer needs protecting since it's always
  pre-seeded rather than generated.
- `agent.initContainers.fixPkiPerms` renamed `agent.initContainers.fixCachePerms`.
- Enables genuine active-active multi-master: with `agent.masterKeySecretName` set and
  `agent.replicas > 1`, all replicas share one keypair (per Salt's own multi-master
  convention) and minions can hold independent, simultaneous connections to every
  replica via a `master:` list - see
  [`docs.saltproject.io/en/3006/topics/tutorials/multimaster.html`](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html).
  Accepting minion keys consistently across all replicas still requires the separate
  `salt-key-operator` component (see its own `CHANGELOG.md`) - manual `salt-key -a`
  only ever affects whichever single pod `kubectl exec` happens to pick.
- New `agent.trustedMinions.*` (default `enabled: false`): delegates minion acceptance
  to `salt-key-operator` entirely. New `templates/configmap.yaml` creates a ConfigMap
  (rendered with no `data:` key, so `helm upgrade` never stomps the operator's
  out-of-band writes to it) that a new `trusted-minions-sync` sidecar container
  continuously copies into the writable directory Salt actually reads. **Not** a
  direct ConfigMap volume mount onto `/etc/salt/pki/master/minions` - confirmed by
  live testing that Kubernetes always mounts ConfigMap volumes as symlinks, and
  Salt 3008's `localfs_key` cache driver explicitly rejects symlinks in every key
  read path as a PKI-tampering hardening measure. `cp` dereferences a symlink
  source by default, which is what makes the sidecar's copy actually work. Once
  enabled, `salt-key -a` no longer works against this master at all (Salt only
  ever reads what the sidecar copies in) - that's intentional, see `values.yaml`'s
  comment.

## salt-master-kubernetes-chart/v0.1.0
- Default image: `salt-master:1.0.0` (`appVersion` in `Chart.yaml`) — see
  [`../docker/salt-master/CHANGELOG.md`](../docker/salt-master/CHANGELOG.md) for what that image
  version carries. Chart default `agent.image.repository` is still the unqualified local name
  `salt-master` (see `values.yaml`), not this published tag.
