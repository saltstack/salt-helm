# salt-helm

Helm charts for deploying different flavours of Salt images to Kubernetes.

## Charts

| Chart | Description |
| --- | --- |
| [salt-minion-kubernetes](salt-minion-kubernetes) | Installs Salt Minion and RBAC. Has built-in support to run CIS Kubernetes compliance assessments via kube-bench on-demand Jobs. Supports in-cluster (minion runs as a pod) and external (RBAC only) modes. |
| [salt-minion-vcf](salt-minion-vcf) | Extensible Salt Minion image (Docker, Docker Compose, Kubernetes, and Helm) preloaded with configurable Salt extensions - `saltext.vcf` (VMware Cloud Foundation automation: vCenter, NSX, SDDC-M, VCF Ops) by default, but not limited to it. Includes `saltext.vault` integration for sourcing credentials from HashiCorp Vault into Pillar instead of storing them on disk. Unlike the other entries here, this directory is the full project (Dockerfile, Docker Compose, scripts, docs), not a chart-only directory - the Helm chart itself lives at [`salt-minion-vcf/helm/salt-minion-vcf`](salt-minion-vcf/helm/salt-minion-vcf). |

## Usage

### Kubernetes / Helm

```bash
helm install salt-minion-kubernetes ./salt-minion-kubernetes -f my-values.yaml
```

```bash
helm install salt-minion-vcf ./salt-minion-vcf/helm/salt-minion-vcf \
  --set salt.master=salt-master.example.com
```

See each chart's `values.yaml` for configurable parameters.

### Docker

`salt-minion-vcf` also runs as a plain Docker container or via Docker
Compose, without Kubernetes - see
[`salt-minion-vcf/README.md`](salt-minion-vcf/README.md) for the full guide,
including air-gapped builds and the local Vault-backed testing workflow.

```bash
docker build -t salt-minion-vcf:0.1.0 ./salt-minion-vcf

docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=salt-master.example.com \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  salt-minion-vcf:0.1.0
```

or with Docker Compose:

```bash
cd salt-minion-vcf
cp .env.example .env   # set SALT_MASTER, etc.
docker compose up -d --build
```
