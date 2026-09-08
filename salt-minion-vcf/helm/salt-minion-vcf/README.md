# Salt Minion VCF Helm Chart

## Minion identity (required)

`salt.minionKeySecretName` is required for both workload kinds below - the
chart fails to render otherwise (set `salt.allowSelfGeneratedKey: true` to
explicitly opt out; see `values.yaml` for why that's discouraged). Create
the Secret out-of-band first:

```bash
kubectl create secret generic vcf-executor-key \
  --namespace salt \
  --from-literal=private-key-b64="$(base64 < minion.pem)" \
  --from-literal=public-key-b64="$(base64 < minion.pub)"
```

The minion's public key also needs to already be registered as trusted
with the target master - either via `vcf-ops-onboard.py` (see
`../../scripts/onboarding/README.md`), or via a `SaltMinionKey` if the
target `salt-master-kubernetes` release uses `salt-key-operator` (see
`../../../salt-key-operator/README.md`).

## Recommended mode: StatefulSet

Salt Minion has a long-lived Minion ID. StatefulSet therefore maps
naturally to the runtime - and is now fully stateless
(`persistence.enabled: false` by default): the pre-seeded keypair above is
handed to the minion on every start, so there's nothing left to persist.

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace salt \
  --create-namespace \
  --set salt.master=salt-master.example.com \
  --set salt.minionKeySecretName=vcf-executor-key \
  --set image.repository=registry.example.com/salt-minion-vcf \
  --set image.tag=0.1.1
```

The first Minion ID will be:

```text
vcf-executor-salt-minion-vcf-0
```

Scale to three independent Minions (each needs its own
`minionKeySecretName` - see `salt.minionId`'s own doc in `values.yaml` for
why a shared ID/key can't be reused across StatefulSet replicas):

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace salt \
  --set workload.kind=StatefulSet \
  --set workload.replicas=3 \
  --set salt.master=salt-master.example.com \
  --set salt.minionKeySecretName=vcf-executor-key
```

## Singleton Deployment mode

A Deployment is also supported when exactly one Minion is wanted.

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace salt \
  --set workload.kind=Deployment \
  --set workload.replicas=1 \
  --set salt.master=salt-master.example.com \
  --set salt.minionKeySecretName=vcf-executor-key
```

Deployment mode intentionally fails Helm rendering if replicas > 1.

## Master configuration

The chart creates a ConfigMap containing `/etc/salt/minion.d/10-master.conf`.

Example:

```yaml
master: salt-master.example.com
master_port: 4506
publish_port: 4505
master_tries: -1
retry_dns: 30
```

`salt.master` also accepts a YAML list, for Salt's native
[multi-master mode](https://docs.saltproject.io/en/3006/topics/tutorials/multimaster.html)
against an active-active `salt-master-kubernetes` release - one
independent, simultaneous connection per address, not failover:

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace salt \
  --set salt.minionKeySecretName=vcf-executor-key \
  --set 'salt.master[0]=salt-master-kubernetes-0.salt-master-kubernetes-headless.salt-master.svc.cluster.local' \
  --set 'salt.master[1]=salt-master-kubernetes-1.salt-master-kubernetes-headless.salt-master.svc.cluster.local' \
  --set 'salt.master[2]=salt-master-kubernetes-2.salt-master-kubernetes-headless.salt-master.svc.cluster.local'
```

The container generates only the dynamic Minion ID/runtime config.

## Credentials

Do not place VCF credentials in `values.yaml` or the ConfigMap.

Use Salt Pillar or an approved secret-management integration so target
credentials remain under the Salt control plane.
