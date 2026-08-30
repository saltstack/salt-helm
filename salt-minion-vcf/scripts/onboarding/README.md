# VCF Operations Onboarding Script

`vcf-ops-onboard.py` is an interactive tool that brings up a `salt-minion-vcf`
instance (Docker **or** Kubernetes/Helm) and registers it as a trusted minion
against a Salt master managed by VMware VCF Operations - without the
minion's private key ever leaving the minion, and without VCF Operations
credentials ever reaching the minion itself.

## What it does

```text
1. Log in to VCF Operations
2. Resolve the Salt master for a given VCF instance
3. Compute the master's identity fingerprint (master_finger) - used for the
   Kubernetes/Helm path and for your own reference/audit trail
4. Start the minion (docker run, or helm upgrade --install), with a freshly
   generated minion ID - the minion generates its own RSA keypair locally.
   Docker minions are pre-seeded with the master's actual public key
   (not just its fingerprint) so they trust it directly on first connect -
   the same approach VCF's own internal component minions use
5. Read back the minion's public key (never the private key)
6. Trust that key with the master
7. Poll until the master accepts the connection
```

This mirrors the manual flow documented in the top-level
[`README.md`](../../README.md#salt-master-registration), just automated and
without a human needing to run `salt-key -a` by hand - trust is established
via the VCF Operations API instead.

Steps 4-7 can be repeated for multiple minions in one session without
re-entering VCF Operations credentials or re-resolving the master.

## Interactive features

- **Input validation**: the VCF instance ID is checked against a UUID format
  and re-prompted if invalid; deployment type is a numbered menu, not free text.
- **Review before acting**: a summary of every setting (minion ID, image,
  container/release name, target master, ...) is shown before the minion is
  started, and again before its key is trusted - nothing consequential runs
  without an explicit confirmation.
- **Live progress**: waiting for the minion to generate its keypair and for
  the master to accept the connection shows an animated spinner with a
  countdown (falls back to periodic plain-text lines if output isn't a TTY,
  e.g. when redirected to a file).
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
  --vcf-instance-id <vcf-instance-resource-id> \
  --deployment docker \
  --image salt-minion-vcf:0.1.0

# Kubernetes / Helm (run from the salt-minion-vcf repo root, so
# --chart-path's default of ./helm/salt-minion-vcf resolves correctly)
python3 scripts/onboarding/vcf-ops-onboard.py \
  --ops-host vcfops.example.com \
  --ops-user admin \
  --vcf-instance-id <vcf-instance-resource-id> \
  --deployment kubernetes \
  --namespace vcf-salt \
  --release-name vcf-executor
```

See `--help` for the full flag list (container/release naming, image
repository/tag, connect timeout, `--log-file`/`-v` for audit logging,
`--dry-run` to preview every command and API call without executing
anything, `-y` to skip confirmation prompts).

## Things to validate in your own environment

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
- **FIPS mode**: enabled by default (`fips_mode: True`,
  `encryption_algorithm: OAEP-SHA224`, `signing_algorithm: PKCS1v15-SHA224`)
  since VCF-managed Salt masters are typically FIPS-enforced and reject
  SHA-1-based crypto with an unhandled error rather than a clean rejection.
  Set `SALT_FIPS_MODE=false` on the minion only if you've confirmed your
  target master is not FIPS-enforced.

## Known limitation

There is currently no API to *revoke* a trusted key (deregistration), so this
script only covers onboarding. To remove a minion, use your master's own
key-management tooling directly for now.
