# Kubernetes Compliance Guide

End-to-end walkthrough for running CIS Kubernetes Benchmark compliance
assessments via a Salt master/minion deployed into Kubernetes:

1. [Build the Docker images](#1-build-the-docker-images)
2. [Install the Helm charts](#2-install-the-helm-charts)
3. [Run a compliance assessment](#3-run-a-compliance-assessment)

This guide is scoped specifically to that workflow (`salt-master-kubernetes`
+ `salt-minion-kubernetes` + kube-bench), not the other charts/projects in
this repo (e.g. `salt-minion-vcf`).

## Prerequisites

- Docker, for building the images
- Helm 3+ and `kubectl` pointed at your target cluster
- A registry (or another way to get images onto your nodes, e.g. `ctr images
  import` for air-gapped clusters with no registry configured)
- A checkout of
  [`saltext-kubernetes`](https://github.com/saltstack/saltext-kubernetes) —
  the minion image is built *from* that repo (see below)

## 1. Build the Docker images

### 1a. salt-master (self-contained)

The master image needs nothing outside this repo — build it directly:

```bash
docker build -t salt-master:3007.1 docker/salt-master
```

Override `SALT_VERSION` to pin a specific Salt release (defaults to
`latest`):

```bash
docker build --build-arg SALT_VERSION=3007.1 -t salt-master:3007.1 docker/salt-master
```

### 1b. salt-minion (built from saltext-kubernetes)

Unlike the master, the minion image installs `saltext.kubernetes` from a
local source tree, so it must be built with a `saltext-kubernetes` checkout
as the build context — not this repo:

```bash
git clone https://github.com/saltstack/saltext-kubernetes.git
cd saltext-kubernetes

docker build -f docker/salt-minion/Dockerfile \
  --build-arg SALT_VERSION=3007.1 \
  --build-arg SALTEXT_KUBERNETES_VERSION="$(git describe --tags --always --dirty | sed -E 's/^v//; s/-/+/')" \
  -t salt-minion:3007.1 .
```

If you're behind a proxy/VPN that blocks public PyPI, route the
`saltext.kubernetes` install through an internal mirror instead:

```bash
docker build -f docker/salt-minion/Dockerfile \
  --build-arg SALT_VERSION=3007.1 \
  --build-arg SALTEXT_KUBERNETES_VERSION="$(git describe --tags --always --dirty | sed -E 's/^v//; s/-/+/')" \
  --build-arg PIP_INDEX_URL=<your-mirror-pypi-simple-url> \
  --build-arg PIP_TRUSTED_HOST=<your-mirror-host> \
  --build-arg PIP_ONLY_BINARY=:all: \
  -t salt-minion:3007.1 .
```

See [`docker/salt-minion/README.md`](../docker/salt-minion/README.md) and
[`docker/salt-master/README.md`](../docker/salt-master/README.md) for the
full build-arg reference for each image.

### 1c. Get the images onto your cluster

- **With a registry:** tag and push both images, then reference
  `<registry>/salt-master`/`<registry>/salt-minion` in the Helm values below.
- **Without a registry** (air-gapped/test clusters): `docker save` each
  image and `ctr -n k8s.io images import` it directly into every node's
  containerd store, then set `image.pullPolicy: Never` in the Helm values so
  Kubernetes doesn't try to pull.

## 2. Install the Helm charts

### 2a. salt-master-kubernetes

```bash
helm install salt-master-kubernetes ./salt-master-kubernetes -f my-master-values.yaml
```

Key values (see [`salt-master-kubernetes/values.yaml`](../salt-master-kubernetes/values.yaml)
for the full list):

| Value | Purpose |
| --- | --- |
| `agent.image.repository` / `agent.image.tag` | The `salt-master` image built in step 1a. |
| `agent.autoAccept` | Set `true` for dev/test to skip manual `salt-key -a` per minion. Leave `false` in production. |
| `agent.persistence.enabled` | Persist `/etc/salt/pki` (master keypair + accepted-minion list) across restarts. Strongly recommended — without it, every restart forgets every accepted minion key. |
| `service.type` | `NodePort` if minions connect from outside the cluster's pod network (e.g. bare containerd, not cluster pods); `ClusterIP` if minions are pods in the same cluster. |
| `service.nodePorts.publish` / `service.nodePorts.ret` | NodePort values forwarding to the master's `4505`/`4506`, when `service.type=NodePort`. |

Verify the master came up healthy:

```bash
kubectl -n kube-system get pods -l app=salt-master-kubernetes
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- salt-key -L
```

### 2b. salt-minion-kubernetes

```bash
helm install salt-minion-kubernetes ./salt-minion-kubernetes -f my-minion-values.yaml
```

Key values (see [`salt-minion-kubernetes/values.yaml`](../salt-minion-kubernetes/values.yaml)
for the full list):

| Value | Purpose |
| --- | --- |
| `agent.image.repository` / `agent.image.tag` | The `salt-minion` image built in step 1b. |
| `agent.saltMasterHost` | The master's address. If `salt-master-kubernetes` uses `service.type=NodePort`, this is any node's IP — the NodePort is open on every node regardless of which one runs the master pod. |
| `agent.saltMasterPort` | Master's "ret" port. **Must be the NodePort value** (e.g. `30506`), not `4506`, when the master uses `service.type=NodePort`. |
| `agent.saltPublishPort` | Master's "publish" port. **Must be the NodePort value** (e.g. `30505`), not `4505`, same reasoning. |
| `agent.persistence.enabled` | Persist the minion's own keypair across restarts — without it, every restart regenerates a fresh key and the master rejects it as a mismatch. |

Both `saltMasterPort` and `saltPublishPort` need to change together — Salt's
minion↔master protocol uses two separate ports (the "ret" channel for the
initial handshake/job returns, and the "publish" channel for broadcasting
jobs), and both must be reachable at whatever address you set
`saltMasterHost` to.

Accept the new minion's key from the master:

```bash
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- salt-key -L
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- salt-key -a <minion-id>
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- salt '<minion-id>' test.ping
```

`test.ping` returning `True` confirms both ports are wired up correctly.

### 2c. kube-bench

The `kube-bench-job` chart installs a *suspended* CronJob that acts as a
pod-spec template — `kube_bench_cache.run_assessment` (below) creates
on-demand Jobs from it; the CronJob itself never fires on its own schedule.
It's published as a reference chart in
[`salt-k8s-compliance`](https://github.com/saltstack/salt-k8s-compliance)
rather than this repo:

```bash
git clone https://github.com/saltstack/salt-k8s-compliance.git
helm install kube-bench-job salt-k8s-compliance/helm/kube-bench-job -f my-kube-bench-values.yaml
```

> Treat this chart as a **reference**, not a drop-in production install.
> Review [`values.yaml`](https://github.com/saltstack/salt-k8s-compliance/blob/main/helm/kube-bench-job/values.yaml)
> before installing — in particular `nodeMounts.*` (host paths differ across
> distros; kubeadm defaults won't match RKE2/k3s), `tolerations` (if
> control-plane nodes should be assessed too), and `cronJob.parallelism`
> (set to your actual node count) — and adapt it to your cluster rather than
> installing it as-is.
>
> **All `nodeMounts.*` paths must be correct for your distro, or assessment
> results will be wrong, not just incomplete.** kube-bench checks that rely
> on a missing/mismatched host path (e.g. the etcd data directory checks)
> come back as an outright **FAIL**, not "skipped" or "not applicable" —
> so a wrong mount silently produces false-negative compliance results
> rather than an obvious error. Verify every path against the actual node
> before trusting the assessment output.

Two values **must** match the corresponding `salt-minion-kubernetes` values,
or `run_assessment` won't find the CronJob it's looking for:

| `kube-bench-job` value | Must match `salt-minion-kubernetes` value |
| --- | --- |
| `namespace` | `namespace` |
| `cronJob.name` | `kubeBench.cronJobName` |

See [`salt-k8s-compliance/helm/kube-bench-job/README.md`](https://github.com/saltstack/salt-k8s-compliance/blob/main/helm/kube-bench-job/README.md)
for the full configuration reference, including host-path mounts for
non-kubeadm distros (RKE2/k3s) and the RBAC gaps to watch for on multi-node
clusters.

## 3. Run a compliance assessment

Assessments are triggered from the Salt master, via the `kube_bench_cache`
execution module (installed on the minion as part of `saltext.kubernetes`).

Force a fresh assessment right now, regardless of any cached result:

```bash
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- \
  salt '<minion-id>' kube_bench_cache.run_assessment
```

Returns `{"result": true, "message": "<cache_path>"}` on success (or
`{"result": false, "message": "<error>"}` on failure) once the on-demand Job
completes and results are written to the minion's local cache.

Look up a specific CIS control's aggregated status (collects a fresh
assessment first only if the cache is stale — see `pillar.ttlSeconds`
below):

```bash
kubectl -n kube-system exec -it deploy/salt-master-kubernetes -- \
  salt '<minion-id>' kube_bench_cache.status_for_check test_number=1.1.11
```

Returns `{"status": "PASS"|"WARN"|"FAIL"|"ERROR", "comment": "<per-node detail>"}`.
kube-bench runs the full check set on every node regardless of role, so a
multi-node cluster can have multiple results for the same control —
`status_for_check` aggregates worst-status-wins (`FAIL` if any node fails,
`PASS` only if every node passes) and lists each node's result in `comment`.

### Configuration

`kube_bench_cache`'s behavior (namespace, cache TTL, Job vs. DaemonSet
collection strategy, auth mode, etc.) is driven by the `kube_bench` pillar
key, rendered into `/srv/pillar/kube_bench.sls` by the `pillar.*` values in
`salt-minion-kubernetes/values.yaml` — these must stay in sync with the
`kube-bench-job` chart values from step 2c (namespace, CronJob name, label
selector).
