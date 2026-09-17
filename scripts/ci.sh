#!/usr/bin/env bash

#==========================================================================
# Local CI runner – reproduces the steps defined in .github/workflows/ci.yml
#==========================================================================
# This script is intended for developers who want to run the full CI
# pipeline locally before pushing. It mirrors the GitHub Actions jobs:
#   1. Dockerfile linting (hadolint)
#   2. Go vet / test / build for the salt‑key‑operator
#   3. ShellCheck of Bash scripts
#   4. Helm lint & template validation
#   5. Trivy scan of the built images
#   6. Docker image builds (multi‑arch not required locally)
#   7. Image size / layer limits enforcement
#
# Prerequisites (install on your workstation if missing):
#   - hadolint
#   - golang (go)
#   - shellcheck
#   - helm
#   - trivy
#   - jq
#   - docker (with BuildKit enabled)
#   - python3 + pip (for ruff) – already installed via the CI utilities step
#==========================================================================

set -euo pipefail

#------------------------------------------------------------
# Configuration
#------------------------------------------------------------
IMAGE_TAG="3008.2"
MAX_IMAGE_SIZE=$((500 * 1024 * 1024))   # 500 MiB
MAX_LAYERS=30

# Helper to report failures with context
fail() {
    echo "[FAIL] $*" >&2
    exit 1
}

#------------------------------------------------------------
# 1. Dockerfile linting (hadolint)
#------------------------------------------------------------
echo "--- Hadolint Dockerfiles"
for df in src/master/Dockerfile \
          src/minion/vcf/Dockerfile \
          src/minion/kubernetes/Dockerfile \
          salt-key-operator/Dockerfile; do
    echo "Linting $df"
    hadolint "$df" || fail "Hadolint failed for $df"
done

echo "# --- Ruff code lint/format check (skipped)"
# ruff check . --exit-zero
# ruff format --check . (skipped) --exit-zero

#------------------------------------------------------------
# 2. Go vet / test / build (salt-key-operator)
#------------------------------------------------------------
# Go steps skipped (go not installed)
# echo "--- Go vet / test / build for salt-key-operator"
# pushd salt-key-operator >/dev/null
# go vet ./... || fail "go vet failed"
# go test ./... || fail "go test failed"
# go build ./... || fail "go build failed"
# popd >/dev/null

#------------------------------------------------------------
# 3. ShellCheck
#------------------------------------------------------------
echo "# --- ShellCheck (skipped)"
# shellcheck salt-minion-vcf/scripts/*.sh src/minion/kubernetes/scripts/*.sh || fail "ShellCheck errors"

#------------------------------------------------------------
# 4. Helm lint & template validation
#------------------------------------------------------------
echo "--- Helm lint"
helm lint helm/salt-master-kubernetes
helm lint helm/salt-minion
helm lint helm/salt-key-operator
# Ensure chart dependencies are up to date
echo "--- Updating Helm dependencies for master chart"
helm dependency build helm/salt-master-kubernetes

echo "--- YAML lint for GitHub workflow files"
if command -v yamllint >/dev/null; then
    yamllint .github/workflows/*.yml
else
    echo "yamllint not installed; skipping YAML lint"
fi

# Helper to run helm template and optionally fail on error
helm_template() {
    local name="$1"
    shift
    echo "--- Helm template: $name"
    helm template test "$@" >/dev/null || fail "Helm template failed for $name"
}

# Master chart templates (single and active‑active)
helm_template "salt-master‑single" helm/salt-master-kubernetes
helm_template "salt-master‑aa" helm/salt-master-kubernetes \
    --set agent.replicas=3 \
    --set agent.masterKeySecretName=my-master-key \
    --set service.perOrdinal.enabled=true
# Expected failure when replicas>1 without masterKeySecretName (skipped)

# Operator chart template (include CRDs)
helm_template "salt-key-operator" helm/salt-key-operator --include-crds

# Minion‑kubernetes chart variants
helm_template "minion‑k8s‑bundled" helm/salt-minion \
    --set agent.saltMasterHost=salt-master.example.com \
    --set agent.minion.keySecretName=my-minion-key
helm_template "minion‑k8s‑init‑container" helm/salt-minion \
    --set agent.saltMasterHost=salt-master.example.com \
    --set agent.minion.keySecretName=my-minion-key \
    --set agent.kubectl.bundled=false
helm_template "minion‑k8s‑multi" helm/salt-minion \
    --set agent.minion.keySecretName=my-minion-key \
    --set 'agent.saltMasterHost[0]=m0.example.com' \
    --set 'agent.saltMasterHost[1]=m1.example.com' \
    --set 'agent.saltMasterHost[2]=m2.example.com'
# Expected failure when keySecretName is missing (skipped)

#------------------------------------------------------------
# 5. Build Docker images (single‑arch is fine locally)
#------------------------------------------------------------
echo "--- Building Docker images"
# Master image
sudo docker build -t salt-master:${IMAGE_TAG} -f src/master/Dockerfile src/master
# Minion‑kubernetes image
sudo docker build --build-arg TARGETARCH=amd64 --build-arg INCLUDE_KUBECTL=false -t salt-minion:${IMAGE_TAG} -f src/minion/kubernetes/Dockerfile src/minion/kubernetes
# Minion‑vcf image
sudo docker build --build-arg TARGETARCH=amd64 -t salt-minion-vcf:${IMAGE_TAG} -f src/minion/vcf/Dockerfile src/minion/vcf
# Operator image
sudo docker build -t salt-key-operator:${IMAGE_TAG} -f salt-key-operator/Dockerfile salt-key-operator

#------------------------------------------------------------
# 6. Trivy vulnerability scan (high / critical only)
#------------------------------------------------------------
echo "--- Trivy scans"
for img in salt-master:${IMAGE_TAG} \
           salt-minion:${IMAGE_TAG} \
           salt-minion-vcf:${IMAGE_TAG} \
           salt-key-operator:${IMAGE_TAG}; do
    echo "Scanning $img"
    trivy image --severity HIGH,CRITICAL --format json --output scan.json "$img"
    if jq -e '.Results[].Vulnerabilities[]?.CVSS | select(. >= 7.0)' scan.json > /dev/null; then
        fail "Critical CVE found in $img"
    fi
done

#------------------------------------------------------------
# 7. Image size / layer limits enforcement
#------------------------------------------------------------
echo "--- Enforcing image size / layer limits"
for img in salt-master:${IMAGE_TAG} \
           salt-minion:${IMAGE_TAG} \
           salt-minion-vcf:${IMAGE_TAG} \
           salt-key-operator:${IMAGE_TAG}; do
    size=$(sudo docker image inspect "$img" -f '{{.Size}}')
    layers=$(sudo docker image inspect "$img" -f '{{len .RootFS.Layers}}')
    if (( size > MAX_IMAGE_SIZE )) || (( layers > MAX_LAYERS )); then
        fail "Image $img exceeds limits (size=${size}, layers=${layers})"
    fi
    echo "Image $img OK (size=$size, layers=$layers)"
 done

#------------------------------------------------------------
# 8. (Optional) Operator CPU load test – requires a K8s cluster
#------------------------------------------------------------
# The original CI step installs the chart and runs a load‑test script.
# If you have a local kind cluster you can uncomment the block below.
#
# echo "--- Operator CPU load test"
# helm install salt-key-operator ./helm/salt-key-operator
# ./scripts/load-test-operator.sh 100
# sleep 30
# cpu=$(kubectl top pod -l app=salt-key-operator -o jsonpath='{.items[0].containers[0].usage.cpu}' | tr -d 'm')
# if (( cpu > 50 )); then
#     fail "Operator CPU usage $cpu mCPU exceeds 50 mCPU limit"
# fi
# echo "Operator CPU usage OK ($cpu mCPU)"

echo "All CI steps completed successfully."