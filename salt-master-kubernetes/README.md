# salt-master-kubernetes

Installs a Salt master as a Kubernetes `StatefulSet`, supporting Salt's
native [multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html)
for active-active horizontal scaling: all replicas share one pre-seeded
keypair, so any of them can be trusted equally by minions.

Deliberately minimal: unlike `salt-minion-kubernetes`, this chart creates no
RBAC and the image installs no `saltext.kubernetes` — the master never calls
the Kubernetes API itself, only minions do.

## Prerequisites

- Kubernetes 1.24+
- Helm 3+
- The `salt-master` image (built from `docker/salt-master/` in
  [saltext-kubernetes](https://github.com/saltstack/saltext-kubernetes))
  available on your nodes/registry

## Installing the chart

Single replica (dev/test - the master generates its own keypair on first
start if `agent.masterKeySecretName` is left unset):

```bash
helm install salt-master-kubernetes . -f my-values.yaml
```

Active-active (3 replicas, one shared identity - see "Active-active" below):

```bash
kubectl create secret generic salt-master-keypair \
  --from-literal=private-key-b64="$(base64 < master.pem)" \
  --from-literal=public-key-b64="$(base64 < master.pub)" \
  -n salt-master

helm install salt-master-kubernetes . \
  --set agent.replicas=3 \
  --set agent.masterKeySecretName=salt-master-keypair
```

## Uninstalling the chart

```bash
helm uninstall salt-master-kubernetes
```

## Configuration

The following table lists the most commonly overridden values. See
[values.yaml](values.yaml) for the full, commented list.

| Parameter | Description | Default |
| --- | --- | --- |
| `namespace` | Namespace for all chart resources. | `salt-master` |
| `agent.image.repository` | Salt master image repository. | `salt-master` |
| `agent.image.tag` | Salt master image tag. | `3007.1` |
| `agent.replicas` | Number of master replicas (active-active - see below). | `1` |
| `agent.masterKeySecretName` | Existing Secret with the master's keypair (`private-key-b64`/`public-key-b64`). **Required** when `agent.replicas > 1`. | `""` |
| `agent.autoAccept` | Auto-accept new minion keys instead of requiring `salt-key -a`/a `SaltMinionKey`. Leave `false` for a production master. | `false` |
| `agent.masterId` | Sets `id:` on the master itself. Empty uses the pod hostname. Need not be unique across replicas. | `""` |
| `agent.presenceEvents` | Fires `salt/presence/present`/`change` events so `manage.present`/`manage.status` reflect which minions are actually connected right now. | `true` |
| `agent.jobCache.persistence.enabled` | Per-replica PVC (via `volumeClaimTemplates`) for the master's job/event cache. Decoupled from identity - PKI is never persisted, only pre-seeded. | `true` |
| `agent.trustedMinions.enabled` | Delegate minion acceptance to `salt-key-operator` (../salt-key-operator) instead of `salt-key -a`. See "Minion acceptance" below. | `false` |
| `agent.nodeSelector` | Pins every replica to a node. | `{}` |
| `service.type` | `NodePort`, `ClusterIP`, or `LoadBalancer` for the flat (non-per-ordinal) Service. `NodePort` is required when minions connect from outside the cluster's pod network. | `NodePort` |
| `service.nodePorts.publish` / `service.nodePorts.ret` | NodePort forwarding to `4505`/`4506` on the flat Service. Only used when `service.type=NodePort`. | `30505` / `30506` |
| `service.perOrdinal.enabled` | One NodePort Service per replica ordinal - needed for **external** minions to hold independent connections to every replica (see "Active-active" below). | `false` |

## Active-active (multiple replicas)

Every master replica is an independent Salt process - Salt's PUB (`4505`)
and REQ/REP (`4506`) channels are per-process, never shared between
replicas. A minion connected to only one replica only ever sees jobs
dispatched via *that* replica. For genuine fan-out (any replica can reach
any minion), point each minion's `master:` config at a **list** of every
replica's address, not a single Service:

- **In-cluster minions**: `salt-master-kubernetes-<N>.salt-master-kubernetes-headless.<namespace>.svc.cluster.local`
  for `N` in `0..agent.replicas-1` (the headless Service is always created).
- **External minions**: set `service.perOrdinal.enabled=true` for one
  NodePort Service per replica, then use any node's IP with that replica's
  NodePort (`service.perOrdinal.basePublishPort`/`baseRetPort` + ordinal).

All replicas must share the identical keypair (`agent.masterKeySecretName`)
- the chart fails to render otherwise. There is no cross-replica job/event
cache by design (matching Salt's own multi-master docs: "the masters do not
share any information") - `agent.jobCache.persistence` is per-replica.

## Minion acceptance

Two ways to accept a minion's key, mutually exclusive per release:

- **Traditional** (`agent.trustedMinions.enabled: false`, the default):
  `salt-key -a` against a specific pod. With more than one replica this
  only affects that one pod - repeat against every replica, or accept the
  inconsistency isn't safe for production active-active use.
  ```bash
  kubectl -n salt-master exec -it salt-master-kubernetes-0 -- salt-key -L
  kubectl -n salt-master exec -it salt-master-kubernetes-0 -- salt-key -a '<minion-id>'
  ```
- **`salt-key-operator`** (`agent.trustedMinions.enabled: true`): install
  the separate [`salt-key-operator`](../salt-key-operator) chart, then
  apply a `SaltMinionKey` custom resource instead - it keeps every replica
  consistent automatically. See that component's own README for the full
  flow. Once enabled, `salt-key -a` no longer works against this master at
  all - a `trusted-minions-sync` sidecar continuously copies the
  operator's ConfigMap into the directory Salt reads, and that's the only
  path in. (Not a direct ConfigMap volume mount: Kubernetes always mounts
  ConfigMaps as symlinks, and Salt 3008 explicitly rejects symlinks in its
  key store - confirmed by live testing, see the chart's own
  `CHANGELOG.md`.) This is intentional, not a bug.
