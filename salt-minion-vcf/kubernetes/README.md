# Raw Kubernetes deployment

The same `salt-minion-vcf` container image can run in Kubernetes.

## Recommended: StatefulSet

Use StatefulSet when you want the strongest mapping between Salt identity and
persistent storage, or when you may scale to multiple execution Minions.

```bash
kubectl create namespace vcf-salt
kubectl -n vcf-salt apply -f configmap.yaml
kubectl -n vcf-salt apply -f service.yaml
kubectl -n vcf-salt apply -f statefulset.yaml
```

The first Minion ID is the stable Pod name:

```text
salt-minion-vcf-0
```

## Optional: singleton Deployment

A normal Deployment is supported for exactly one Salt Minion. The explicit
Minion ID plus PVC keep its Salt identity stable even when the Pod name changes.

```bash
kubectl create namespace vcf-salt
kubectl -n vcf-salt apply -f configmap.yaml
kubectl -n vcf-salt apply -f pvc.yaml
kubectl -n vcf-salt apply -f deployment.yaml
```

The example Minion ID is:

```text
vcf-k8s-executor-01
```

Do not scale this raw Deployment above one replica. Use StatefulSet for multiple
independent Salt Minions.

## Master ConfigMap

Edit `configmap.yaml` before deployment. It is mounted as:

```text
/etc/salt/minion.d/10-master.conf
```

After changing the raw ConfigMap, restart the workload so Salt reloads it:

```bash
kubectl -n vcf-salt rollout restart statefulset/salt-minion-vcf
# or
kubectl -n vcf-salt rollout restart deployment/salt-minion-vcf
```

## Accept the Minion

```bash
salt-key -L
salt-key -a '<minion-id>'
salt '<minion-id>' test.ping
```

The headless Service in StatefulSet mode exists for stable StatefulSet identity.
Salt Minion traffic itself is outbound to the Salt Master.
