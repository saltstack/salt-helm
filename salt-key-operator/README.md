# salt-key-operator

A small Kubernetes operator (controller-runtime/kubebuilder-style, Go) that
reconciles a `SaltMinionKey` custom resource - the declarative replacement
for running `salt-key -a <minion-id>` by hand against a
`salt-master-kubernetes` pod.

## Why this exists

`salt-master-kubernetes` (see `../salt-master-kubernetes/README.md`) supports
running multiple master replicas that all share one keypair, using Salt's
own [multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html).
That doc explicitly calls out a gap vanilla Salt multi-master doesn't solve:

> Keys accepted, deleted, or rejected on one master will NOT be
> automatically managed on redundant masters.

Manually running `salt-key -a` also only ever affects whichever single pod
`kubectl exec` happens to pick - with 3+ replicas, that's 3+ separate manual
steps that all have to stay in sync by hand. `salt-key-operator` replaces
that entirely: creating one `SaltMinionKey` object gets a minion trusted by
**every** replica of the target master release, consistently.

## How it works

1. You create a `SaltMinionKey` with just two fields: the minion ID and its
   public key, inline (PEM, plain text - a minion's public key isn't
   sensitive, so there's no separate Secret to create first). There's also
   no need to say *which* master release to trust it with - the controller
   finds the one `salt-master-kubernetes` release installed in the
   `SaltMinionKey`'s own namespace automatically (see "Design notes" below
   for what happens if that's ambiguous).
2. The controller writes `data[<minionId>] = <publicKey>` into that
   release's trusted-minions ConfigMap (see `salt-master-kubernetes`'s
   `agent.trustedMinions.*` values).
3. `salt-master-kubernetes` runs a `trusted-minions-sync` sidecar in every
   replica that continuously copies that ConfigMap into the directory Salt
   actually reads (`/etc/salt/pki/master/minions`) - **not** a direct
   ConfigMap volume mount. Kubernetes always mounts ConfigMap volumes as
   symlinks (the atomic `..data` indirection scheme), and Salt 3008's
   `localfs_key` cache driver explicitly rejects symlinks in every key
   read path as a PKI-tampering hardening measure - confirmed by testing
   this directly against a real cluster, a minion whose key existed only
   as a ConfigMap-mounted symlink was invisible to Salt and got rejected.
   `cp` dereferences a symlink source by default, which is what makes the
   sidecar's copy actually work. No `salt-key -a`, no pod restart -
   propagation is bounded by kubelet's ConfigMap resync (on the order of a
   minute) plus the sidecar's own poll interval (`syncIntervalSeconds`,
   default 15s).
4. Deleting the `SaltMinionKey` removes the entry the same way, via a
   finalizer.

## Design notes / trade-offs

- **No Secret, no target reference - just an ID and a public key.** A
  minion's public key isn't sensitive (that's the whole point of asymmetric
  crypto), so requiring a Secret object just to hold it would be pure
  indirection. And rather than making every `SaltMinionKey` name which
  master ConfigMap to target, the controller discovers the one
  `trustedMinionsLabel`-marked ConfigMap in its own namespace - matching
  this repo's convention of one `salt-master-kubernetes` release per
  dedicated namespace (e.g. `salt-master`). Running more than one master
  release in the same namespace isn't supported by this auto-discovery
  (the controller returns an error - `NoMasterConfigMap` if none, an
  ambiguity error if more than one - rather than guessing).
- **No exec-into-pod from the operator, no volume shared *across*
  replicas.** The operator itself only ever writes to one ConfigMap - it
  never touches a master pod directly. Making that ConfigMap's content
  actually usable by Salt is `salt-master-kubernetes`'s own problem, solved
  there with a per-pod `trusted-minions-sync` sidecar and a per-pod
  `emptyDir` (see that chart's `templates/statefulset.yaml`) - not shared
  between replicas, just between the two containers of the same pod.
- **Propagation latency is bounded by kubelet's ConfigMap resync period**
  (on the order of a minute) plus the sync sidecar's own poll interval on
  top - not instant. If sub-second propagation is ever needed, the
  escalation path (not built) is having the sidecar watch the ConfigMap
  directly via the API server (informer/watch) instead of polling a
  kubelet-synced volume mount.
- **ConfigMap size ceiling.** Kubernetes ConfigMaps are capped near 1MiB in
  etcd. At roughly 1-2KB per RSA-2048 PEM entry, that's on the order of a
  few hundred to ~1000 minions per master release before the ConfigMap
  needs sharding (not implemented).
- **Why a real controller-runtime operator instead of a lightweight
  script**: many `SaltMinionKey` objects can reconcile concurrently against
  the *same* target ConfigMap (e.g. on operator startup, reconciling every
  existing object at once). The controller wraps every ConfigMap write in
  `client-go`'s `RetryOnConflict`, which a `kubectl patch` loop in a script
  doesn't get for free - concurrent writers would otherwise silently lose
  updates. Leader election (`--leader-elect`) also lets the operator itself
  run >1 replica without split-brain writers, matching the active-active
  goal of the master tier it feeds.
- **RBAC is the single biggest new attack-surface item this component adds
  to the repo** - nothing else here touches ConfigMaps or a custom API
  group (and, per the point above, this design needs no Secret access at
  all). The chart defaults `watchNamespace: salt-master` - matching
  `salt-master-kubernetes`'s own default namespace - which scopes RBAC down
  to a namespaced `Role`/`RoleBinding` in just that namespace, not a
  cluster-wide `ClusterRole`. Set `watchNamespace: ""` only for a genuine
  multi-tenant cluster with target master releases spread across multiple
  namespaces - that falls back to `ClusterRole`/`ClusterRoleBinding`, since
  `SaltMinionKey` objects and their target ConfigMaps could then be
  anywhere. Treat any change to this component's RBAC as
  security-review-worthy either way.
- **Deliberately lightweight**: one replica, no leader election, 20m/32Mi
  requests by default - there's no control-plane-HA case to make for a
  controller that does nothing but occasionally patch one ConfigMap per
  namespace. `leaderElection.enabled`/`replicas` exist together for the
  rare case this operator's own availability needs to match the
  active-active master tier it feeds.

## Development

```bash
go build ./...
go vet ./...
go test ./...
```

Regenerating the CRD/deepcopy code after changing `api/v1alpha1/*_types.go`:

```bash
go install sigs.k8s.io/controller-tools/cmd/controller-gen@latest
controller-gen object:headerFile="" paths="./api/..."
controller-gen crd paths="./api/..." output:crd:artifacts:config=config/crd/bases
controller-gen rbac:roleName=salt-key-operator paths="./..." output:rbac:artifacts:config=config/rbac
cp config/crd/bases/*.yaml helm/salt-key-operator/crds/
```

`config/rbac/role.yaml`'s `rules:` also has to be copied by hand into
`helm/salt-key-operator/templates/rbac.yaml` (both the `Role` and
`ClusterRole` branches) - see the comment at the top of that template.

Note `api/v1alpha1/saltminionkeystatus_deepcopy.go`: `controller-gen`
v0.22.0 under this repo's Go 1.27 toolchain does not emit a `DeepCopyInto`
for `SaltMinionKeyStatus` even though it correctly determines one is needed
(confirmed reproducible even with `Conditions` reduced to a plain
`[]string`, so it isn't specific to `metav1.Condition`) - that file is a
hand-maintained supplement working around it, kept out of
`zz_generated.deepcopy.go` so regenerating doesn't need to remember to
restore it. If a future toolchain combination fixes this upstream, the file
becomes redundant rather than incorrect.

**Helm does not manage CRD upgrades** after first install (a
[documented Helm limitation](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)
for anything under a chart's `crds/` directory) - to pick up a CRD schema
change on an existing install, apply it directly:

```bash
kubectl apply -f helm/salt-key-operator/crds/
```

## CRD reference

```yaml
apiVersion: salt.saltstack.io/v1alpha1
kind: SaltMinionKey
metadata:
  name: <minion-id>       # object name - can differ from spec.minionId,
  namespace: <namespace>  # which is unconstrained by RFC 1123 (may be an FQDN, etc.)
                           # - and must be the same namespace as the target
                           # salt-master-kubernetes release
spec:
  minionId: <minion-id>
  publicKey: |
    -----BEGIN PUBLIC KEY-----
    ...
    -----END PUBLIC KEY-----
status:
  conditions:
    - type: Accepted
      status: "True"
  observedMasterConfigMap: <configmap-name>   # auto-discovered, not user-set
```
