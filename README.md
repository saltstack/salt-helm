# salt-helm

Helm charts for deploying different flavours of Salt images to Kubernetes.

## Charts

| Chart | Description |
| --- | --- |
| [salt-minion-kubernetes](salt-minion-kubernetes) | Installs Salt Minion and RBAC. Has built-in support to run CIS Kubernetes compliance assessments via kube-bench on-demand Jobs. Supports in-cluster (minion runs as a pod) and external (RBAC only) modes. |

## Usage

```bash
helm install salt-minion-kubernetes ./salt-minion-kubernetes -f my-values.yaml
```

See each chart's `values.yaml` for configurable parameters.
