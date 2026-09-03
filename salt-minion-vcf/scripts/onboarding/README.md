# VCF Operations Onboarding Script

`vcf-ops-onboard.py` is an interactive tool for managing `salt-minion-vcf`
instances (Docker **or** Kubernetes/Helm) against a Salt master managed by
VMware VCF Operations - without the minion's private key ever leaving the
minion, and without VCF Operations credentials ever reaching the minion
itself. It supports three actions, picked with `--action` or interactively:

- **configure** (default) - bring up a *new* minion, already trusted on first
  connect.
- **rotate** - rotate the key of an *already-onboarded* minion.
- **list** - read-only listing of trusted minions (master, key/presence
  state, resourceKind), handy before rotating one.

## configure: what it does

```text
1. Log in to VCF Operations
2. List every Salt master VCF Operations knows about and pick one, by FQDN -
   masters that aren't ACCEPTED/PRESENT are flagged so you don't pick one
   that won't actually work
3. Generate a fresh RSA keypair for the minion locally, via `openssl` - the
   private key never leaves this process
4. Register the minion's public key as trusted against the selected master.
   The minion ID is assigned by VCF Operations here, not chosen up front -
   this is the first point the ID is known
5. Start the minion (docker run, or helm upgrade --install), pre-seeded with
   that exact keypair and minion ID. Docker minions are also pre-seeded with
   the master's actual public key (not just its fingerprint) so they trust
   it directly on first connect - the same approach VCF's own internal
   component minions use
6. Poll until the master accepts the connection
```

Because trust is established in step 4 *before* the minion ever starts,
there's no waiting-for-acceptance window and no human needing to run
`salt-key -a` by hand.

Steps 3-6 can be repeated for multiple minions in one session without
re-entering VCF Operations credentials or re-listing masters.

## rotate: what it does

```text
1. Log in to VCF Operations
2. Identify the running minion (container name, or Helm release/namespace)
   and read its CURRENT public key straight off its PKI dir - this is how
   the minion is identified server-side too, since the rotate API never
   accepts a minion ID as input. Then pick the Salt master to rotate
   against (normally the SAME one the minion is already configured for -
   picking a different one re-associates the minion's trust record with it,
   and the script warns before letting that happen)
3. Generate a fresh RSA keypair locally, and call the rotate API
   (POST /api/salt/minions/rotate) with the current and new public keys.
   VCF Operations resolves the existing trust record from the current key
   and re-registers it in place with the new one
4. Push the new keypair into the running instance and restart it:
   - Docker: the container is recreated (env vars holding the keypair are
     fixed at container creation, so this is the only way to feed it a new
     one); the PKI volume's old key files are cleared first so the fresh
     env vars actually get picked up
   - Kubernetes: the minion's key Secret is updated, any persisted PKI files
     on the Pod are cleared (relevant when `persistence.enabled=true`), and
     the Pod is deleted so it's recreated with the new key
   Then poll until the master accepts the new connection, same as configure.
```

## list: what it does

A single read-only call to `GET /api/salt/minions`, printed as a table of
minion ID, master ID, key state, presence, and resourceKind (the minion's
`vcfops_resource_kind` grain, if it has reported one - null for a freshly
configured minion until its own bootstrap sets that grain). Use `--state` to
filter by trust state.

## Interactive features

- **Master picker**: every Salt master VCF Operations knows about is listed
  with its key/presence state; deployment type is also a numbered menu, not
  free text.
- **Review before acting**: a summary of every setting (minion ID, image,
  container/release name, target master, ...) is shown before the minion's
  key is registered as trusted, and again before the minion is started -
  nothing consequential runs without an explicit confirmation.
- **Live progress**: waiting for the master to accept the connection shows
  an animated spinner with a countdown (falls back to periodic plain-text
  lines if output isn't a TTY, e.g. when redirected to a file).
- **Onboard multiple minions in one session**: after each successful
  onboarding you're asked whether to onboard another against the same
  master - container/volume/release names are auto-suggested with a `-2`,
  `-3`, ... suffix so they don't collide with the previous minion.
- **`-y`/`--yes`** skips all confirmations for scripted/CI use, and
  **`--dry-run`** previews every command and API call without executing
  anything.

## Logging

Every run writes a full step-by-step audit log to
`vcf-ops-onboard-<timestamp>.log` in the current directory (override the path
with `--log-file`). It captures every prompt, shell command, and API call/
response - passwords and auth tokens are never written to it. Pass
`-v`/`--verbose` to also mirror that detail live on the console.

## Requirements

- Python 3.8+ (standard library only - no `pip install` needed)
- `openssl` on PATH (generates the minion's own RSA keypair)
- `docker` on PATH (Docker mode), or `helm` + `kubectl` on PATH (Kubernetes mode)
- Network access from wherever you run this script to your VCF Operations
  instance's Suite API

## Usage

Fully interactive - just run it and answer the prompts:

```bash
python3 scripts/onboarding/vcf-ops-onboard.py
```

Or supply anything up front via flags (anything omitted is still prompted for):

```bash
# Docker
python3 scripts/onboarding/vcf-ops-onboard.py \
  --ops-host vcfops.example.com \
  --ops-user admin \
  --deployment docker \
  --image salt-minion-vcf:0.1.0

# Kubernetes / Helm (run from the salt-minion-vcf repo root, so
# --chart-path's default of ./helm/salt-minion-vcf resolves correctly)
python3 scripts/onboarding/vcf-ops-onboard.py \
  --ops-host vcfops.example.com \
  --ops-user admin \
  --deployment kubernetes \
  --namespace vcf-salt \
  --release-name vcf-executor

# Skip the interactive master picker if you already know the master ID
python3 scripts/onboarding/vcf-ops-onboard.py \
  --ops-host vcfops.example.com \
  --ops-user admin \
  --master-id salt-master-7a1b2c3d-4e5f-6789-abcd-ef0123456789 \
  --deployment docker

# Rotate an already-onboarded Docker minion's key
python3 scripts/onboarding/vcf-ops-onboard.py \
  --action rotate --deployment docker \
  --ops-host vcfops.example.com --ops-user admin \
  --container-name salt-minion-vcf

# Rotate an already-onboarded Kubernetes minion's key
python3 scripts/onboarding/vcf-ops-onboard.py \
  --action rotate --deployment kubernetes \
  --ops-host vcfops.example.com --ops-user admin \
  --namespace vcf-salt --release-name vcf-executor

# List trusted minions
python3 scripts/onboarding/vcf-ops-onboard.py \
  --action list --ops-host vcfops.example.com --ops-user admin
```

See `--help` for the full flag list (container/release naming, image
repository/tag, connect timeout, `--log-file`/`-v` for audit logging,
`--dry-run` to preview every command and API call without executing
anything, `-y` to skip confirmation prompts).

## Things to validate in your own environment

- **PKI volume reuse (Docker)**: a named Docker volume outlives `docker rm` - if you
  reuse the same `--volume` (or the default `salt-minion-vcf-pki`) across separate
  `configure`/`rotate` runs, `docker-entrypoint.sh`'s own guard (only seed the
  keypair if `minion.pem` doesn't already exist, so a genuine restart keeps its
  identity) would otherwise silently keep an OLD, unrelated keypair instead of the
  one just registered via the API. The script now clears any leftover
  `minion.pem`/`minion.pub` from the volume immediately before every container
  start, so this can't happen - no action needed on your part, just worth knowing
  why a fresh run always gets a fresh identity even if you reuse the same volume
  name.
- **Master FQDN resolution (Docker)**: many on-prem/lab masters have internal-only
  hostnames (e.g. `*.vrack.vsphere.internal`) that only resolve via a static entry
  in the *host's* `/etc/hosts`, not real DNS - and Docker containers don't inherit
  that file automatically, which surfaces as the minion logging
  `Master hostname: '<fqdn>' not found or not responsive` even though the host
  itself can ping it fine. The script resolves the master's FQDN on the host
  (the same way `getent hosts`/`ping` would) and automatically passes it to the
  container via `--add-host`, so this is handled for you for any master FQDN -
  no manual IP lookup needed. If the host itself can't resolve it either, this
  is silently skipped and the container falls back to its own DNS as before.
- **VCF Operations auth flow**: the script logs in via
  `POST /suite-api/api/auth/token/acquire` and sends
  `Authorization: OpsToken <token>` on subsequent calls - the same pattern
  used by other existing tooling against this backend. If your deployment
  fronts VCF Operations with SSO/CSP instead, adjust `OpsClient.login()`.
- **`master_finger` algorithm**: defaults to `sha256` (matches the Salt
  version this image bundles). Override with `--master-finger-algo md5` if
  your Salt master needs the legacy default. Only used by the
  Kubernetes/Helm path today - Docker minions are pre-seeded with the
  master's actual public key instead (see "What it does" above).
- **Minion keypair Secret (Kubernetes)**: the generated keypair is written
  to a Kubernetes Secret named `<release-name>-minion-key`
  (`kubectl apply`'d directly, not through Helm values, so it never lands
  in `helm get values`/release history) and referenced by the chart's new
  `salt.minionKeySecretName` value. Delete it yourself if you remove the
  release and don't intend to reuse that identity.
- **RSA key size**: defaults to 2048 bits (Salt's own default). Override
  with `--key-size 4096` if your security policy requires it.
- **FIPS mode**: enabled by default (`fips_mode: True`,
  `encryption_algorithm: OAEP-SHA224`, `signing_algorithm: PKCS1v15-SHA224`)
  since VCF-managed Salt masters are typically FIPS-enforced and reject
  SHA-1-based crypto with an unhandled error rather than a clean rejection.
  Set `SALT_FIPS_MODE=false` on the minion only if you've confirmed your
  target master is not FIPS-enforced.

## Known limitation

There is currently no API to *revoke* a trusted key (deregistration), so this
script covers onboarding (`configure`), key rotation (`rotate`), and listing
(`list`), but not removal. To remove a minion, use your master's own
key-management tooling directly for now.
