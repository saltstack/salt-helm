# salt-minion

Installs RBAC and an optional Salt minion Deployment for running CIS Kubernetes
compliance assessments via kube-bench on-demand Jobs.

This directory is also the image's own project: `Dockerfile` builds a
self-contained Salt minion (core Salt plus `saltext.vault` and
`saltext.kubernetes`, both pip-installed from PyPI — see
`salt-extensions.txt`) with `kubectl` bundled in. Build it the same way as
[`salt-minion-vcf`](../salt-minion-vcf/README.md):

```bash
docker build -t salt-minion:0.1.0 .
```

See [`CHANGELOG.md`](CHANGELOG.md) for which Salt/extension versions each
published image and chart release tag actually carries.

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
helm install salt-minion . -f my-values.yaml
```

At minimum, for `in_cluster` mode set `agent.saltMasterHost` to your Salt
master's address:

```bash
helm install salt-minion . --set agent.saltMasterHost=salt-master.example.com
```

For `external` mode (RBAC only):

```bash
helm install salt-minion . --set agent.authMode=external
```

Then issue a token for the created ServiceAccount and use it in the external
minion's kubeconfig:

```bash
kubectl create token salt-minion -n salt
```

## Uninstalling the chart

```bash
helm uninstall salt-minion
```

## Configuration

The following table lists the most commonly overridden values. See
[values.yaml](values.yaml) for the full, commented list.

| Parameter | Description | Default |
| --- | --- | --- |
| `namespace` | Namespace for all chart resources. Must match `kube-bench-job`'s namespace. | `salt` |
| `agent.authMode` | `in_cluster` or `external`. | `in_cluster` |
| `agent.image.repository` | Salt minion image repository. | `ghcr.io/saltstack/salt-kubernetes/salt-minion` |
| `agent.image.tag` | Salt minion image tag. | `0.1.1` |
| `agent.kubectl.bundled` | Skip the install-kubectl init container — true when `agent.image` already bundles `kubectl` (the default image does). | `true` |
| `agent.saltMasterHost` | Salt master address. Required for `in_cluster` mode. Also accepts a list, for Salt's native [multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html) against an active-active `salt-master-kubernetes` release. | `""` |
| `agent.minion.keySecretName` | Existing Secret with the minion's keypair (`private-key-b64`/`public-key-b64`). **Required** unless `agent.minion.allowSelfGeneratedKey: true`. | `""` |
| `agent.saltMasterPort` | Salt master "ret" port (`master_port`). Override alongside `agent.saltPublishPort` when the master isn't reachable on its default ports, e.g. behind a Kubernetes NodePort Service. | `4506` |
| `agent.saltPublishPort` | Salt master "publish" port (`publish_port`). | `4505` |
| `agent.authTimeout` | Seconds to wait for master auth before retrying - reduces thundering-herd retry storms. | `60` |
| `agent.masterAliveInterval` | Seconds between checks that the master TCP connection is still alive; reconnects if not. | `60` |
| `agent.reconDefault` / `agent.reconMax` | ZeroMQ transport reconnect backoff range (ms). | `1000` / `5000` |
| `agent.reconRandomize` | Jitters reconnect delay so minions don't all retry in lockstep. | `true` |
| `agent.minion.id` | Salt minion ID. Empty uses the pod hostname. | `""` |
| `agent.persistence.enabled` | Persist the minion's generated keypair (`/etc/salt/pki`) across pod restarts. | `false` |
| `agent.persistence.type` | `pvc` or `hostPath`. `hostPath` requires `agent.nodeSelector`. | `pvc` |
| `agent.nodeSelector` | Pins the pod to a node. Required when `agent.persistence.type=hostPath`. | `{}` |
| `serviceAccount.name` | ServiceAccount name. | `salt-minion` |
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

### Vault integration

`saltext.vault` is baked into the default image, giving pillar values an
`sdb` driver so they can reference `sdb://vault_sdb/<path>:<key>` instead of
plaintext. Configure it via `agent.vault.*` in `values.yaml` — same
mechanism and env vars as
[`salt-minion-vcf`'s Vault integration](../salt-minion-vcf/README.md#vault-integration),
disabled unless `agent.vault.addr` is set.

### kube-bench coordination

The `kubeBench.*` and `pillar.*` values are rendered into the
`salt-minion-pillar` ConfigMap, mounted at
`/srv/pillar/kube_bench.sls` inside the minion pod. These must stay in sync
with the corresponding values in the `kube-bench-job` chart. External minions
can point `pillar_roots` at a copy of this ConfigMap via a hostPath or
projected volume.
