# Helm Test Workflow

This document outlines a reproducible workflow to **test Helm charts on a real Kubernetes cluster** using the local Harbor registry.

## Prerequisites
- Access to the Kubernetes cluster (`kubectl` configured).
- `helm` version 3 installed.
- Docker (or an OCI builder) on the machine where the commands run.
- Harbor registry reachable from the cluster (service name `harbor-core` on port `5000`).
- The Helm chart you want to test (e.g., `salt-master-kubernetes`).

## Steps
1. **Build the Docker image**
   ```bash
   docker build -t salt-master:ci-test docker/salt-master
   ```
2. **Tag & push the image to Harbor**
   ```bash
   HARBOR=harbor-core:5000
   IMAGE=salt-master
   TAG=ci-test
   docker tag ${IMAGE}:${TAG} ${HARBOR}/${IMAGE}:${TAG}
   docker push ${HARBOR}/${IMAGE}:${TAG}
   ```
3. **Render the chart (optional sanity check)**
   ```bash
   helm template test ./salt-master-kubernetes \
     --set agent.image.repository=${HARBOR}/${IMAGE} \
     --set agent.image.tag=${TAG} \
     --set agent.trustedMinions.enabled=false \
     --set service.gateway.enabled=false \
     --set service.perOrdinal.gateway.enabled=false
   ```
4. **Install/upgrade the chart**
   ```bash
   helm upgrade --install salt-master-test ./salt-master-kubernetes \
     --set agent.image.repository=${HARBOR}/${IMAGE} \
     --set agent.image.tag=${TAG} \
     --set agent.trustedMinions.enabled=false \
     --set service.gateway.enabled=false \
     --set service.perOrdinal.gateway.enabled=false \
     --wait --timeout 5m
   ```
5. **Verify the deployment**
   ```bash
   kubectl get pods -l app=salt-master-kubernetes -o wide
   ```
6. **Cleanup (optional)**
   ```bash
   helm uninstall salt-master-test
   ```

You can invoke this workflow by asking the assistant to **execute the steps in `docs/helm-test.md`** on your target environment.
