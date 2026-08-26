# salt-minion-kubernetes

Installs RBAC and an optional Salt minion Deployment for running CIS Kubernetes
compliance assessments via kube-bench on-demand Jobs.

Supports two deployment modes, selected via `agent.authMode`:

- **in_cluster** (default) — the Salt minion runs as a Deployment inside the
  cluster. The chart creates the Deployment plus RBAC (ServiceAccount, Role,
  ClusterRole, and their bindings).
- **external** — RBAC only. The minion runs outside the cluster (e.g. via
  salt-ssh or on a standalone host) and authenticates to the Kubernetes API
  using a token issued for the ServiceAccount this chart creates.

## Prerequisites

- Kubernetes 1.24+
- Helm 3+
- A reachable Salt master (required for `in_cluster` mode)

## Installing the chart

```bash
helm install salt-minion-kubernetes . -f my-values.yaml
```

At minimum, for `in_cluster` mode set `agent.saltMasterHost` to your Salt
master's address:

```bash
helm install salt-minion-kubernetes . --set agent.saltMasterHost=salt-master.example.com
```

For `external` mode (RBAC only):

```bash
helm install salt-minion-kubernetes . --set agent.authMode=external
```

Then issue a token for the created ServiceAccount and use it in the external
minion's kubeconfig:

```bash
kubectl create token salt-minion-kubernetes -n kube-system
```

## Uninstalling the chart

```bash
helm uninstall salt-minion-kubernetes
```

## Configuration

The following table lists the most commonly overridden values. See
[values.yaml](values.yaml) for the full, commented list.

| Parameter | Description | Default |
| --- | --- | --- |
| `namespace` | Namespace for all chart resources. Must match `kube-bench-job`'s namespace. | `kube-system` |
| `agent.authMode` | `in_cluster` or `external`. | `in_cluster` |
| `agent.image.repository` | Salt minion image repository. | `saltstack/salt` |
| `agent.image.tag` | Salt minion image tag. | `3007.1` |
| `agent.saltMasterHost` | Salt master address. Required for `in_cluster` mode. | `""` |
| `agent.saltMasterPort` | Salt master "ret" port (`master_port`). Override alongside `agent.saltPublishPort` when the master isn't reachable on its default ports, e.g. behind a Kubernetes NodePort Service. | `4506` |
| `agent.saltPublishPort` | Salt master "publish" port (`publish_port`). | `4505` |
| `agent.minion.id` | Salt minion ID. Empty uses the pod hostname. | `""` |
| `agent.persistence.enabled` | Persist the minion's generated keypair (`/etc/salt/pki`) across pod restarts. | `false` |
| `agent.persistence.type` | `pvc` or `hostPath`. `hostPath` requires `agent.nodeSelector`. | `pvc` |
| `agent.nodeSelector` | Pins the pod to a node. Required when `agent.persistence.type=hostPath`. | `{}` |
| `serviceAccount.name` | ServiceAccount name. | `salt-minion-kubernetes` |
| `rbac.create` | Set to `false` to manage RBAC externally. | `true` |
| `kubeBench.cronJobName` | Must match `cronJob.name` in the `kube-bench-job` chart. | `kube-bench` |
| `pillar.ttlSeconds` | Cached assessment result TTL. | `900` |
| `pillar.jobTimeout` | Timeout for the kube-bench assessment Job. | `600` |

### Persistence

Without persistence, the minion generates a fresh keypair on every pod
restart, and the Salt master rejects it as a mismatch against the key already
on file — requiring a manual `salt-key -d`/`-a` cycle each time. Enable
`agent.persistence.enabled` to avoid this:

- `pvc` (default) — requires a StorageClass. Use `agent.persistence.pvc.existingClaim`
  to reuse an existing claim instead of letting the chart create one.
- `hostPath` — for clusters without a dynamic provisioner (e.g. bare kubeadm
  labs). Ties the data to a specific node, so `agent.nodeSelector` must also
  be set.

### kube-bench coordination

The `kubeBench.*` and `pillar.*` values are rendered into the
`salt-minion-kubernetes-pillar` ConfigMap, mounted at
`/srv/pillar/kube_bench.sls` inside the minion pod. These must stay in sync
with the corresponding values in the `kube-bench-job` chart. External minions
can point `pillar_roots` at a copy of this ConfigMap via a hostPath or
projected volume.
