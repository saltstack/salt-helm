# salt-master-kubernetes

Installs a Salt master as a Kubernetes Deployment, exposed via a `NodePort`
Service (`4505`/`4506`) for minions that connect from outside normal pod
scheduling (e.g. bare processes/containers on the node hosts, not cluster
pods).

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

```bash
helm install salt-master-kubernetes . -f my-values.yaml
```

```bash
helm install salt-master-kubernetes . --set agent.autoAccept=true
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
| `namespace` | Namespace for all chart resources. | `kube-system` |
| `agent.image.repository` | Salt master image repository. | `salt-master` |
| `agent.image.tag` | Salt master image tag. | `3007.1` |
| `agent.autoAccept` | Auto-accept new minion keys instead of requiring `salt-key -a` per minion. Leave `false` for a production master. | `false` |
| `agent.masterId` | Sets `id:` on the master itself. Empty uses the pod hostname. | `""` |
| `agent.persistence.enabled` | Persist the master's `/etc/salt/pki` (its own keypair *and* the accepted-minion key list) across pod restarts. | `false` |
| `agent.persistence.type` | `pvc` or `hostPath`. `hostPath` requires `agent.nodeSelector`. | `pvc` |
| `agent.nodeSelector` | Pins the pod to a node. Required when `agent.persistence.type=hostPath`. | `{}` |
| `service.type` | `NodePort`, `ClusterIP`, or `LoadBalancer`. `NodePort` is required when minions connect from outside the cluster's pod network. | `NodePort` |
| `service.nodePorts.publish` | NodePort forwarding to the master's `4505` (publish channel). Only used when `service.type=NodePort`. | `30505` |
| `service.nodePorts.ret` | NodePort forwarding to the master's `4506` (ret channel). Only used when `service.type=NodePort`. | `30506` |

### Persistence

Without persistence, every pod restart regenerates the master's keypair
(breaking every minion's cached copy of it) and forgets which minion keys
were already accepted — requiring a manual re-accept of every minion.
Enable `agent.persistence.enabled` to avoid this:

- `pvc` (default) — requires a StorageClass. Use
  `agent.persistence.pvc.existingClaim` to reuse an existing claim instead of
  letting the chart create one.
- `hostPath` — for clusters without a dynamic provisioner (e.g. bare kubeadm
  labs). Ties the data to a specific node, so `agent.nodeSelector` must also
  be set.

### Minion-side port configuration

When `service.type=NodePort`, minions connecting from outside the cluster
must point at a node IP and the **NodePort** values, not the container's
internal `4505`/`4506`:

```yaml
# salt-minion-kubernetes values
agent:
  saltMasterHost: <any-node-ip>
  saltMasterPort: 30506    # service.nodePorts.ret
  saltPublishPort: 30505   # service.nodePorts.publish
```

Any node's IP works — the NodePort is opened on every node in the cluster,
regardless of which node the master pod is actually scheduled on.
