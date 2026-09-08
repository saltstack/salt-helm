# salt-helm

Helm charts for deploying different flavours of Salt images to Kubernetes.

## Charts

| Chart | Description |
| --- | --- |
| [salt-master-kubernetes](salt-master-kubernetes) | Installs a Salt master Deployment exposed via a NodePort Service, for minions connecting from outside normal pod scheduling. Deliberately minimal - no RBAC, no saltext.kubernetes install. |
| [salt-minion-kubernetes](salt-minion-kubernetes) | Installs Salt Minion and RBAC. Has built-in support to run CIS Kubernetes compliance assessments via kube-bench on-demand Jobs. Supports in-cluster (minion runs as a pod) and external (RBAC only) modes. Like `salt-minion-vcf`, this is a full project directory - its own `Dockerfile` builds a Salt minion preloaded with `saltext.vault` and `saltext.kubernetes`, with `kubectl` bundled in. |
| [salt-minion-vcf](salt-minion-vcf) | Extensible Salt Minion image (Docker, Docker Compose, Kubernetes, and Helm) preloaded with configurable Salt extensions - `saltext.vcf` (VMware Cloud Foundation automation: vCenter, NSX, SDDC-M, VCF Ops) by default, but not limited to it. Includes `saltext.vault` integration for sourcing credentials from HashiCorp Vault into Pillar instead of storing them on disk. Unlike the other entries here, this directory is the full project (Dockerfile, Docker Compose, scripts, docs), not a chart-only directory - the Helm chart itself lives at [`salt-minion-vcf/helm/salt-minion-vcf`](salt-minion-vcf/helm/salt-minion-vcf). |

## Quick install (published images/charts)

The fastest path to a working deployment: install straight from the
published GHCR OCI charts, no local Docker/Helm build required. See
[`docs/releasing.md`](docs/releasing.md) for the full list of published
artifacts, and each component's own `CHANGELOG.md` for exactly which
Salt/extension versions a given tag carries (the tag itself is just that
component's own semver, independent of Salt's version).

### salt-master-kubernetes

```bash
helm install salt-master-kubernetes \
  oci://ghcr.io/saltstack/salt-helm/charts/salt-master-kubernetes \
  --version 0.1.0 \
  --set agent.image.repository=ghcr.io/saltstack/salt-helm/salt-master \
  --set agent.image.tag=1.0.0
```

### salt-minion-kubernetes

```bash
helm install salt-minion-kubernetes \
  oci://ghcr.io/saltstack/salt-helm/charts/salt-minion-kubernetes \
  --version 0.1.0 \
  --set agent.saltMasterHost=salt-master.example.com
```

(`agent.image.repository` already defaults to the published
`ghcr.io/saltstack/salt-helm/salt-minion-kubernetes` image - no override
needed there.)

### salt-minion-vcf

```bash
helm install salt-minion-vcf \
  oci://ghcr.io/saltstack/salt-helm/charts/salt-minion-vcf \
  --version 0.1.0 \
  --set image.repository=ghcr.io/saltstack/salt-helm/salt-minion-vcf \
  --set image.tag=0.1.0 \
  --set salt.master=salt-master.example.com
```

`salt-minion-vcf` also runs as a plain Docker container, pulling the
published image directly - no Kubernetes required. See
[`salt-minion-vcf/README.md`](salt-minion-vcf/README.md) for the full guide,
including Docker Compose and the local Vault-backed testing workflow.

```bash
docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=salt-master.example.com \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  ghcr.io/saltstack/salt-helm/salt-minion-vcf:0.1.0
```

See each chart's `values.yaml` for the full list of configurable parameters.

## Building from source

Need a patched image, a different Salt version, or an air-gapped build with
no route to GHCR? See [`docs/building.md`](docs/building.md).
