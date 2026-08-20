IMAGE ?= salt-minion-vcf
TAG ?= 0.1.0
HELM_RELEASE ?= vcf-executor
NAMESPACE ?= vcf-salt
SALT_MASTER ?= salt-master.example.com
EXPORT_DIR ?= dist

# Optional internal mirrors for air-gapped/restricted-network builds, and
# corporate PyPI proxy settings. Leave unset to use the public defaults.
APT_MIRROR ?=
SALT_GPG_KEY_URL ?=
SALT_APT_REPO_URL ?=
PIP_INDEX_URL ?=
PIP_TRUSTED_HOST ?=
PIP_ONLY_BINARY ?=

BUILD_ARGS := $(if $(APT_MIRROR),--build-arg APT_MIRROR=$(APT_MIRROR)) \
              $(if $(SALT_GPG_KEY_URL),--build-arg SALT_GPG_KEY_URL=$(SALT_GPG_KEY_URL)) \
              $(if $(SALT_APT_REPO_URL),--build-arg SALT_APT_REPO_URL=$(SALT_APT_REPO_URL)) \
              $(if $(PIP_INDEX_URL),--build-arg PIP_INDEX_URL=$(PIP_INDEX_URL)) \
              $(if $(PIP_TRUSTED_HOST),--build-arg PIP_TRUSTED_HOST=$(PIP_TRUSTED_HOST)) \
              $(if $(PIP_ONLY_BINARY),--build-arg PIP_ONLY_BINARY=$(PIP_ONLY_BINARY))

.PHONY: build save load compose-up compose-down compose-logs smoke \
        dev-up dev-down dev-poc \
        k8s-apply k8s-delete k8s-verify helm-lint helm-template helm-install helm-uninstall

build:
	docker build $(BUILD_ARGS) -t $(IMAGE):$(TAG) .

# Export the built image as a tarball for offline/air-gapped transfer,
# e.g. into an OVF/OVA build pipeline that does not pull from a registry.
save:
	mkdir -p $(EXPORT_DIR)
	docker save $(IMAGE):$(TAG) -o $(EXPORT_DIR)/$(IMAGE)_$(TAG).tar

load:
	docker load -i $(EXPORT_DIR)/$(IMAGE)_$(TAG).tar

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f

smoke:
	./scripts/smoke-test.sh

# Local POC harness: a throwaway dev Salt Master so the full
# connect -> accept key -> test.ping -> verify extensions flow can be
# exercised without a real customer-provided Salt Master.
dev-up:
	SALT_MASTER=salt-master docker compose --profile dev up -d --build

dev-down:
	docker compose --profile dev down -v

dev-poc: dev-up
	./scripts/poc.sh

k8s-apply:
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NAMESPACE) apply -f kubernetes/configmap.yaml
	kubectl -n $(NAMESPACE) apply -f kubernetes/service.yaml
	kubectl -n $(NAMESPACE) apply -f kubernetes/statefulset.yaml

k8s-delete:
	kubectl -n $(NAMESPACE) delete -f kubernetes/statefulset.yaml --ignore-not-found
	kubectl -n $(NAMESPACE) delete -f kubernetes/service.yaml --ignore-not-found
	kubectl -n $(NAMESPACE) delete -f kubernetes/configmap.yaml --ignore-not-found

k8s-verify:
	NAMESPACE=$(NAMESPACE) ./scripts/verify-k8s.sh

helm-lint:
	helm lint helm/salt-minion-vcf

helm-template:
	helm template $(HELM_RELEASE) helm/salt-minion-vcf \
	  --namespace $(NAMESPACE) \
	  --set salt.master=$(SALT_MASTER) \
	  --set image.repository=$(IMAGE) \
	  --set image.tag=$(TAG)

helm-install:
	helm upgrade --install $(HELM_RELEASE) helm/salt-minion-vcf \
	  --namespace $(NAMESPACE) \
	  --create-namespace \
	  --set salt.master=$(SALT_MASTER) \
	  --set image.repository=$(IMAGE) \
	  --set image.tag=$(TAG)

helm-uninstall:
	helm uninstall $(HELM_RELEASE) --namespace $(NAMESPACE)
