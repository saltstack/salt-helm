# Salt Minion VCF Helm Chart

## Recommended mode: StatefulSet

Salt Minion has persistent PKI and a long-lived Minion ID. StatefulSet therefore
maps naturally to the runtime.

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace vcf-salt \
  --create-namespace \
  --set salt.master=salt-master.example.com \
  --set image.repository=registry.example.com/salt-minion-vcf \
  --set image.tag=0.1.0
```

The first Minion ID will be:

```text
vcf-executor-salt-minion-vcf-0
```

Scale to three independent Minions:

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace vcf-salt \
  --set workload.kind=StatefulSet \
  --set workload.replicas=3 \
  --set salt.master=salt-master.example.com
```

Each replica receives:
- its own stable Pod identity
- its own persistent PKI volume
- its own Salt Minion key

## Singleton Deployment mode

A Deployment is also supported when exactly one Minion is wanted.

```bash
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --namespace vcf-salt \
  --set workload.kind=Deployment \
  --set workload.replicas=1 \
  --set salt.master=salt-master.example.com
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

The container generates only the dynamic Minion ID/runtime config.

## Credentials

Do not place VCF credentials in `values.yaml` or the ConfigMap.

Use Salt Pillar or an approved secret-management integration so target
credentials remain under the Salt control plane.
