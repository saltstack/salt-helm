# Salt Minion VCF

A reusable Salt Minion container that can be built with **one or more Salt extension packages** and used as a centralized execution worker for VMware Cloud Foundation automation.

`saltext-vcf` is the default extension in this repository, but the image is **not restricted to saltext-vcf**.

## Goal

Use one common Salt Minion image as a remote automation worker.

```text
Any Salt-aware client
(Salt Config CLI, RaaS UI/API, CI/CD pipeline, custom automation, ...)
      |
      v
RaaS / Salt Master
      |
      v
Salt Extension Minion
      |
      +--> saltext-vcf
      +--> another saltext package
      +--> customer/community Salt extension
      |
      v
Target infrastructure APIs
```

Nothing about this image is tied to a specific dispatching client — anything that
can talk to a Salt Master (a CLI, a REST API caller, a CI/CD job, a custom
orchestration platform) works identically, since the Minion only ever sees
Salt jobs, never the caller.

The same image supports:

- Docker
- Docker Compose
- Kubernetes
- Helm
- future OVF/OVA appliance deployment

---

## Quick Start

Two build paths, identical runtime behavior — only where build-time packages
come from differs. Pick one based on whether the build host can reach the
public internet.

### A. Standard build (internet access available)

**1. Build**

```bash
docker build --build-arg SALT_VERSION=3008.2 -t salt-minion-vcf:0.1.0 .
```

Extensions listed in `salt-extensions.txt` (see
[Flexible Salt Extension Installation](#flexible-salt-extension-installation))
install straight from PyPI during this step.

**2. Test — run it and connect to a Salt Master**

```bash
docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=<salt-master-host-or-ip> \
  -e SALT_MINION_ID=vcf-docker-executor-01 \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  salt-minion-vcf:0.1.0

docker logs -f salt-minion-vcf
```

On the Salt Master, accept the new key:

```bash
salt-key -L
salt-key -a vcf-docker-executor-01
salt 'vcf-docker-executor-01' test.ping
```

Don't have a real Master to test against yet? Run the exact same flow
against a throwaway local one instead — see
[Running the POC locally without a customer Salt Master](#running-the-poc-locally-without-a-customer-salt-master).

**3. Verify**

```bash
docker exec salt-minion-vcf salt-call --local test.version
docker exec salt-minion-vcf salt-pip freeze | grep -i vcf
docker exec salt-minion-vcf salt-call --local sys.list_modules | grep -i vcf
docker exec salt-minion-vcf salt-call status.master   # true once the key is accepted
```

### B. Air-gapped build (internal mirrors only)

Same image, same runtime behavior — only the build step changes. A standard
build reaches three external endpoints: Ubuntu's apt mirrors (base OS
packages), `packages.broadcom.com` (Salt's own apt repo + GPG key), and PyPI
(extension packages). Redirect each to an internal mirror independently —
set only the ones your network actually blocks, the rest keep their public
defaults:

**1. Build**

```bash
docker build \
  --build-arg APT_MIRROR=http://mirror.internal.example.com/ubuntu/ \
  --build-arg SALT_GPG_KEY_URL=https://artifactory.internal.example.com/artifactory/api/security/keypair/SaltProjectKey/public \
  --build-arg SALT_APT_REPO_URL=https://artifactory.internal.example.com/artifactory/saltproject-deb \
  --build-arg PIP_INDEX_URL=https://artifactory.internal.example.com/artifactory/api/pypi/upstream-pypi-virtual/simple \
  --build-arg PIP_TRUSTED_HOST=artifactory.internal.example.com \
  -t salt-minion-vcf:0.1.0 .
```

Equivalently, via `make` (or the same variables in `.env` for `docker compose build`):

```bash
make build \
  APT_MIRROR=http://mirror.internal.example.com/ubuntu/ \
  SALT_GPG_KEY_URL=https://artifactory.internal.example.com/artifactory/api/security/keypair/SaltProjectKey/public \
  SALT_APT_REPO_URL=https://artifactory.internal.example.com/artifactory/saltproject-deb \
  PIP_INDEX_URL=https://artifactory.internal.example.com/artifactory/api/pypi/upstream-pypi-virtual/simple \
  PIP_TRUSTED_HOST=artifactory.internal.example.com
```

See [Building in an air-gapped / restricted-network environment](#building-in-an-air-gapped--restricted-network-environment)
for exactly what each variable controls.

**2. Test — run it and connect to a Salt Master**

Identical to the standard path. Building air-gapped only changes where
*packages* come from at build time — it has no bearing on where the *Salt
Master* lives at runtime. If the Master is also on the isolated network,
this works the same way:

```bash
docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=<internal-salt-master-host-or-ip> \
  -e SALT_MINION_ID=vcf-docker-executor-01 \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  salt-minion-vcf:0.1.0

docker logs -f salt-minion-vcf
```

```bash
salt-key -L
salt-key -a vcf-docker-executor-01
salt 'vcf-docker-executor-01' test.ping
```

**3. Verify**

Same commands as the standard path:

```bash
docker exec salt-minion-vcf salt-call --local test.version
docker exec salt-minion-vcf salt-pip freeze | grep -i vcf
docker exec salt-minion-vcf salt-call --local sys.list_modules | grep -i vcf
docker exec salt-minion-vcf salt-call status.master
```

**Moving the built image into the air-gapped network without a registry**
(e.g. for an OVF/OVA pipeline) — see
[Offline / Air-Gapped Image Export](#offline--air-gapped-image-export):

```bash
make save    # docker build + docker save -> dist/salt-minion-vcf_0.1.0.tar
make load    # docker load on the target host
```

---

## Flexible Salt Extension Installation

Salt extensions are defined in:

```text
salt-extensions.txt
```

Default:

```text
saltext.vcf[all]
```

Customers can add any other pip-installable Salt extension package.

Example:

```text
saltext.vcf[all]
saltext.example==1.2.3
another-salt-extension==2.0.0
```

Version pinning is recommended for reproducible/open-source releases.

A package can also come from a Git repository if supported by `pip`, for example:

```text
git+https://github.com/example/saltext-example.git@v1.2.3
```

Then build the same image:

```bash
docker build -t salt-minion-vcf:0.1.0 .
```

All listed extensions are installed with `salt-pip` into the Salt runtime.

For quick experimentation, additional packages may be supplied at build time:

```bash
docker build \
  --build-arg 'EXTRA_SALT_EXTENSIONS=saltext.example==1.2.3' \
  -t salt-minion-vcf:0.1.0 .
```

For production, prefer `salt-extensions.txt` so the exact extension set is source-controlled and reproducible.

### Building behind a corporate PyPI proxy

If the build host cannot reach public PyPI (e.g. an internal Artifactory
mirror), pass the proxy configuration as build args. They are only used
during the extension-install step and are not persisted into the final image:

```bash
docker build \
  --platform linux/amd64 \
  --build-arg SALT_VERSION=3007.1 \
  --build-arg PIP_INDEX_URL=https://packages.example.com/artifactory/api/pypi/upstream-pypi-virtual/simple \
  --build-arg PIP_TRUSTED_HOST=packages.example.com \
  --build-arg PIP_ONLY_BINARY=:all: \
  -t salt-minion-vcf:3007.1 .
```

### Building in an air-gapped / restricted-network environment

Building this image normally reaches three external endpoints: Ubuntu's apt
mirrors (base OS packages), `packages.broadcom.com` (Salt's own apt
repository + GPG key), and PyPI (extension packages, see above). If the build
host can only reach internal mirrors, redirect each of these independently
with build args — none are required, and each defaults to its public
endpoint when omitted:

```bash
docker build \
  --build-arg APT_MIRROR=http://mirror.internal.example.com/ubuntu/ \
  --build-arg SALT_GPG_KEY_URL=https://artifactory.internal.example.com/artifactory/api/security/keypair/SaltProjectKey/public \
  --build-arg SALT_APT_REPO_URL=https://artifactory.internal.example.com/artifactory/saltproject-deb \
  --build-arg PIP_INDEX_URL=https://artifactory.internal.example.com/artifactory/api/pypi/upstream-pypi-virtual/simple \
  --build-arg PIP_TRUSTED_HOST=artifactory.internal.example.com \
  -t salt-minion-vcf:0.1.0 .
```

The same variables can be set via `make build APT_MIRROR=... SALT_APT_REPO_URL=...`
or in `.env` for `docker compose build`. `APT_MIRROR` only needs to be a
mirror of Ubuntu's own repositories (unrelated to Salt); `SALT_GPG_KEY_URL`/
`SALT_APT_REPO_URL` need to mirror Broadcom's Salt Debian repository
specifically — most internal Artifactory setups proxy the public repo at an
equivalent path, in which case only the hostname changes.

### Important Design Principle

Extensions are installed **when the image is built**, not every time a container or Pod starts.

```text
salt-extensions.txt
        |
        v
docker build
        |
        v
Immutable Salt Minion image
        |
        +--> Docker
        +--> Kubernetes
        +--> Helm
        +--> future OVF
```

This keeps Docker and Kubernetes behavior identical.

---

## Image Contents

The image contains:

- Salt Minion
- packages defined in `salt-extensions.txt`
- dependencies required by those extensions
- startup and health-check scripts

The image does **not** contain:

- Salt Master
- RaaS
- any dispatching client (Salt Config CLI, RaaS UI/API, custom automation, etc.)
- customer credentials
- hardcoded VCF endpoint details

---

## Docker Deployment

```bash
docker run -d \
  --name salt-minion-vcf \
  -e SALT_MASTER=salt-master.example.com \
  -e SALT_MINION_ID=vcf-docker-executor-01 \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  salt-minion-vcf:0.1.0
```

Important runtime parameters:

```text
SALT_MASTER
SALT_MASTER_PORT
SALT_PUBLISH_PORT
SALT_MINION_ID
SALT_MASTER_FINGER
SALT_LOG_LEVEL
```

Extension selection is an **image build concern**; Salt Master/minion connectivity is a **runtime configuration concern**.

---

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

---

## Offline / Air-Gapped Image Export

Some downstream consumers (e.g. an OVF/OVA build pipeline) load the image
from a tarball instead of pulling it from a registry:

```bash
make build save               # docker build, then docker save into dist/
make load                     # docker load a previously exported tarball
```

This is equivalent to:

```bash
docker save salt-minion-vcf:0.1.0 -o dist/salt-minion-vcf_0.1.0.tar
docker load -i dist/salt-minion-vcf_0.1.0.tar
```

---

## Runtime User

The container runs as a dedicated non-root user (uid/gid `10000`), not root.
`saltext-vcf` calls remote APIs (vCenter/NSX/SDDC-M/Ops) rather than managing
local host state, so the minion does not need root inside the container.
Kubernetes/Helm set matching `runAsUser`/`runAsGroup`/`fsGroup` so the PKI PVC
is writable by that user.

Minion logs are routed to stdout (`log_file: /dev/stdout`) so `docker logs` /
`kubectl logs` show minion activity instead of only the container's log file.

---

## Kubernetes Deployment

Kubernetes uses the exact same image.

```text
Helm values
    |
    v
ConfigMap
    |
    v
Salt Master configuration

StatefulSet
    |
    +--> stable Pod identity
    |
    +--> persistent PVC
           |
           v
     /etc/salt/pki/minion
```

The ConfigMap contains only non-sensitive Salt Minion/Master configuration.

Example:

```yaml
master: salt-master.example.com
master_port: 4506
publish_port: 4505
master_tries: -1
retry_dns: 30
```

Do not put VCF or other target-system credentials in the ConfigMap.

---

## Helm Deployment

```bash
helm upgrade --install vcf-executor \
  ./helm/salt-minion-vcf \
  --namespace vcf-salt \
  --create-namespace \
  --set salt.master=salt-master.example.com \
  --set image.repository=my-registry/salt-minion-vcf \
  --set image.tag=0.1.0
```

Default:

```yaml
workload:
  kind: StatefulSet
  replicas: 1
```

StatefulSet is recommended because Salt Minions have persistent PKI and identity.

---

## Verify Installed Extensions

Inside the container:

```bash
salt-pip freeze
```

Inspect available Salt execution modules:

```bash
salt-call --local sys.list_modules
```

Inspect available state modules:

```bash
salt-call --local sys.list_state_modules
```

This verification is intentionally generic and does not assume only `saltext-vcf` is present.

---

## Salt Master Registration

```bash
salt-key -L
salt-key -a <minion-id>
salt '<minion-id>' test.ping
```

---

## Pillar Data for saltext.vcf Credentials

`saltext.vcf` reads vCenter/NSX/SDDC-M/etc. credentials from Salt Pillar
under `saltext.vcf.<target>`, e.g.:

```yaml
saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test
    username: administrator@vsphere.local
    password: secret
    verify_ssl: false
```

The full set of targets (`vcenter`, `nsx`, `sddc_manager`, `esxi`, `vcfa`,
`vcf_installer`, `vcf_ops`) is documented with working examples in
[`pillar/`](pillar/) — copy the ones you need from `*.sls.example` to `*.sls`
(gitignored) and fill in real values. Never commit the real files.

**Where this data needs to live depends on how VCF operations are
triggered against this minion:**

### Path 1 — locally inside this container (`salt-call --local`)

Use this for the POC's read-only VCF step, ad-hoc testing, or if scripts
inside the container/pod call saltext.vcf directly. The minion always has
`pillar_roots` pointed at `/etc/salt/pillar`; a `top.sls` matching `'*'` is
auto-generated from whatever `*.sls` files are present.

**At container/Pod start:**

```bash
# Docker / Compose - bind-mount the directory (see the commented example
# in docker-compose.yml):
docker run -d --name salt-minion-vcf \
  -e SALT_MASTER=<host> \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  -v "$(pwd)/pillar:/etc/salt/pillar" \
  salt-minion-vcf:0.1.0
```

```bash
# Kubernetes / Helm - create a Secret containing your *.sls files PLUS a
# top.sls matching '*' (a Pod only ever runs one Minion ID, so a wildcard
# is always sufficient here - this is NOT the same top.sls as Path 2 below):
cat > top.sls <<'EOF'
base:
  '*':
    - vcenter
EOF
kubectl create secret generic salt-minion-vcf-pillar \
  --from-file=top.sls \
  --from-file=vcenter.sls=pillar/vcenter.sls
helm upgrade --install vcf-executor ./helm/salt-minion-vcf \
  --set salt.master=<host> \
  --set pillar.secretName=salt-minion-vcf-pillar
```

**Into an already-running container/Pod, no restart required** — `salt-call
--local` recompiles pillar from disk on every call, so an update is visible
immediately:

```bash
# Docker: push files in and regenerate top.sls in one step
./scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls pillar/nsx.sls

# Kubernetes: update the Secret object itself - kubelet re-syncs the
# mounted volume automatically (typically within ~60-90s), no exec needed
kubectl create secret generic salt-minion-vcf-pillar \
  --from-file=top.sls \
  --from-file=vcenter.sls=pillar/vcenter.sls \
  --dry-run=client -o yaml | kubectl apply -f -
```

**Verify:**

```bash
docker exec salt-minion-vcf salt-call --local pillar.items
docker exec salt-minion-vcf salt-call --local vcf_vcenter_vm.list_   # example read-only call
```

### Path 2 — dispatched from the Salt Master (`salt '<minion-id>' ...`)

This is the architecture in [Goal](#goal): RaaS/Salt Master dispatches jobs
to the minion. Jobs run this way are compiled using the **Master's own**
`pillar_roots` — a file mounted into this container is invisible to them.
The customer's Salt Master admin needs pillar data on the Master side
(e.g. `/srv/pillar`), targeted by this minion's ID:

```yaml
# /srv/pillar/top.sls on the customer's Salt Master
base:
  'vcf-docker-executor-01':
    - vcenter
```

using the identical `saltext.vcf.<target>` structure — see
[`pillar/master-top.sls.example`](pillar/master-top.sls.example). This is
outside this repo's control; for production, prefer an `ext_pillar` backed
by a secrets manager (e.g. Vault) over plain files in `/srv/pillar`.

---

## Vault Integration

[`saltext.vault`](https://github.com/salt-extensions/saltext-vault) is
included in `salt-extensions.txt` by default, providing an `sdb` driver so
pillar *values* can reference Vault instead of containing plaintext:

```yaml
saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test
    username: sdb://vault_sdb/secret/vcenter/username
    password: sdb://vault_sdb/secret/vcenter/password
```

The URI is **slash-delimited**: `sdb://<profile>/<vault-kv-path>/<key>` — not
colon-delimited (`path:key`). This was wrong in an earlier draft of this
doc and only caught by actually running it against a real Vault (see below):
`sdb://vault_sdb/secret/vcenter:password` silently resolves to `None`
instead of erroring, so it's easy to end up with a minion that "works" but
sends an empty credential. If you copy an example from elsewhere, double
check it uses slashes.

`sdb://` URIs resolve **wherever that pillar file happens to be rendered** —
this is the important part to get right, and it's worth being precise about
two genuinely different things this repo supports:

### What's confirmed

Verified against a real local Vault dev server (see
[Testing locally with a dev Vault](#testing-locally-with-a-dev-vault) below),
not just a fake address — AppRole login scoped by a least-privilege policy,
`sdb.get` resolving the real secret, a pillar file containing only the
`sdb://` reference (never the plaintext value, confirmed by reading the file
back off disk), and a real `saltext.vcf` module (`vcf_vcenter_vm.list_`)
correctly using the resolved credential to attempt a live vCenter API call
(only failing because the test vCenter address is fake). The `vault:`
auth/server config and `sdb` profile are wired into the entrypoint, gated on
`VAULT_ADDR` being set — `saltext.vault` installs cleanly via the normal
extension mechanism (see
[Flexible Salt Extension Installation](#flexible-salt-extension-installation)),
nothing custom needed there.

- Per the [official auth FAQ](https://salt-extensions.github.io/saltext-vault/topics/auth_faq.html),
  even the "master issues minion-scoped tokens" broker pattern still has the
  **Master** perform the Vault fetch and render the pillar — the secret
  value transits the Master's process (encrypted in transit to the minion,
  never written to disk on the Master, but not zero master involvement).
  Only `token`/`approle` auth methods are supported by `saltext.vault` (no
  Kubernetes ServiceAccount auth), so a real secret — the AppRole
  `secret_id`, or a Vault token — has to reach the minion somehow regardless
  of which path below you pick.

### What needs YOUR validation before relying on it

**`SALT_FILE_CLIENT_LOCAL=true`** sets `file_client: local` on the minion.
Salt's own pillar-fetch code branches on this setting to decide whether to
render pillar locally (this minion's `pillar_roots`, resolving `sdb://` here
too) or remotely via the Master — and that branch is independent of whether
the *job* was dispatched from the Master or run via `salt-call --local`. If
that holds, `sdb://` in local pillar resolves entirely on the minion, the
Master never touches the secret at all, and RaaS/Master-dispatched jobs
still work unchanged. This is a genuinely non-standard minion configuration
(most guides only document it for fully masterless setups), and **I could
not get a clean empirical confirmation in my own sandbox** — an ad-hoc
master+minion test there stalled during key registration for both a
`file_client: local` minion and a plain control minion, which points at
sandbox/emulation flakiness rather than the setting itself, but I don't want
to assert this works without a clean test. Please validate on your own
infrastructure before depending on it for production RaaS jobs:

```bash
# 1. Enable it and start the minion against your real (or dev) master
docker run -d --name salt-minion-vcf \
  -e SALT_MASTER=<host> \
  -e SALT_FILE_CLIENT_LOCAL=true \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  -v "$(pwd)/pillar:/etc/salt/pillar" \
  salt-minion-vcf:0.1.0

# 2. Accept the key as usual
salt-key -a <minion-id>

# 3. The critical check: run this FROM THE MASTER, not salt-call --local
salt '<minion-id>' test.ping         # should still work - job dispatch is unaffected
salt '<minion-id>' pillar.items      # does this return the minion's LOCAL pillar,
                                      # or the Master's (likely empty/different)?
```

If step 3's `pillar.items` returns the minion's local data, the design
works as intended. If it returns something else (or errors), `file_client:
local` isn't a safe substitute for real Master-side pillar for your Salt
version, and Path 2 (Master-side `ext_pillar: vault`) is the fallback -
still real defense-in-depth over static plaintext files, just not "the
Master never sees it."

### Testing locally with a dev Vault

`docker-compose.yml` includes a throwaway HashiCorp Vault dev server (same
`profiles: ["dev"]` pattern as the dev Salt Master) — in-memory, ephemeral,
auto-unsealed, with a well-known root token. Never use `-dev` mode outside
testing.

```bash
docker compose --profile dev up -d vault
```

Write a test secret and set up least-privilege AppRole auth (matching the
default `VAULT_AUTH_METHOD=approle`):

```bash
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault kv put secret/vcenter host=mgmt-vc.example.test \
    username=administrator@vsphere.local password=SuperSecretPassw0rd verify_ssl=false

docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault auth enable approle

echo 'path "secret/data/vcenter" { capabilities = ["read"] }' > /tmp/vcf-minion-policy.hcl
docker cp /tmp/vcf-minion-policy.hcl salt-minion-vcf-dev-vault:/tmp/vcf-minion-policy.hcl
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault policy write vcf-minion-policy /tmp/vcf-minion-policy.hcl

docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault write auth/approle/role/vcf-minion token_policies="vcf-minion-policy" token_ttl=1h

docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault read -field=role_id auth/approle/role/vcf-minion/role-id
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=root salt-minion-vcf-dev-vault \
  vault write -f -field=secret_id auth/approle/role/vcf-minion/secret-id
```

Start the minion pointed at it (same Docker network as the compose project;
role_id/secret_id from the previous step):

```bash
docker run -d --name salt-minion-vcf --network salt-minion-vcf_default \
  -e SALT_MASTER=127.0.0.1 \
  -e VAULT_ADDR=http://vault:8200 \
  -e VAULT_AUTH_METHOD=approle \
  -e VAULT_ROLE_ID=<role-id-from-above> \
  -e VAULT_SECRET_ID=<secret-id-from-above> \
  --no-healthcheck \
  salt-minion-vcf:0.1.0
```

(`--no-healthcheck` avoids the built-in `status.master` healthcheck piling
up retries against the fake `SALT_MASTER=127.0.0.1` used here for a
pillar-only test — omit it once pointed at a real reachable Master.)

```bash
docker exec salt-minion-vcf salt-call --local sdb.get 'sdb://vault_sdb/secret/vcenter/password'
# -> SuperSecretPassw0rd

echo 'saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test
    username: sdb://vault_sdb/secret/vcenter/username
    password: sdb://vault_sdb/secret/vcenter/password' > pillar/vcenter.sls
./scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls

docker exec salt-minion-vcf salt-call --local vcf_vcenter_vm.list_
# -> fails on DNS resolution for the fake host, proving it got past
#    credential resolution and attempted a real vCenter API call
```

Tear down with `docker compose --profile dev down -v` (drops the ephemeral
Vault data too).

### Configuration

All optional, disabled unless `VAULT_ADDR` is set:

```bash
VAULT_ADDR=https://vault.example.com:8200
VAULT_AUTH_METHOD=approle          # or: token
VAULT_ROLE_ID=<role-id>            # not sensitive
VAULT_SECRET_ID_FILE=/run/secrets/vault-secret-id   # prefer this over VAULT_SECRET_ID
VAULT_TOKEN_FILE=/run/secrets/vault-token           # if using token auth instead
```

`VAULT_SECRET_ID`/`VAULT_TOKEN` (plain env vars) are supported too, but the
`_FILE` variants are strongly preferred — plain env vars are visible via
`docker inspect`/`kubectl get pod -o yaml`, whereas a `_FILE` path lets you
mount the actual secret via a Docker secret or Kubernetes Secret instead
(the Helm chart's `vault.secretName` does this automatically — see
`helm/salt-minion-vcf/values.yaml`).

---

## Security

- Never bake customer credentials into the image.
- Do not store passwords in Kubernetes ConfigMaps.
- Persist `/etc/salt/pki/minion`.
- Use `master_finger` for trusted Salt Master validation.
- Prefer Salt Pillar or an approved secrets system for target credentials.
- Pin extension versions for released images.
- Review third-party extension packages before including them in an open-source image.

---

## Future OVF / OVA

The future appliance should use the same prebuilt image:

```text
OVF / OVA
   |
   v
Linux VM
   |
   v
Docker / Podman
   |
   v
Salt Extension Minion image
```

Changing the extension set should require building a new versioned image, not modifying the OVF runtime logic.

---

## First POC

```text
Choose extension packages
        |
        v
Build image
        |
        v
Run Docker/Kubernetes Minion
        |
        v
Connect to Salt Master
        |
        v
Accept Minion key
        |
        v
test.ping
        |
        v
verify extension modules
        |
        v
execute one read-only operation
```

### Running the POC locally without a customer Salt Master

A throwaway dev Salt Master (see `docker/dev-master/`, DEV/TEST ONLY) drives
the same flow end-to-end for local validation or CI:

```bash
make dev-poc
```

This builds the minion image, starts both containers on an isolated Compose
network, waits for the minion's key to register, accepts it, runs `test.ping`
from both the master and the minion, and lists the installed `saltext-vcf`
modules. The final "execute one read-only VCF operation" step still requires
real vCenter/NSX/SDDC-M/Ops credentials supplied via Salt Pillar against a
real target, which this harness intentionally does not fake.

Tear down with:

```bash
make dev-down
```
