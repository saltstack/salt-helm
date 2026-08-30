# Runbook: Onboarding an External Minion and Connecting It to VCF Infrastructure

This runbook covers two separate procedures:

1. **Bring up a `salt-minion-vcf` instance and trust it against a VCF
   Operations-managed Salt master** (Part 1) - using
   [`scripts/onboarding/vcf-ops-onboard.py`](../scripts/onboarding/vcf-ops-onboard.py).
2. **Give that minion the credentials it needs to actually operate against
   VCF components** (vCenter, NSX, SDDC Manager, ESXi, VCFA, VCF Installer,
   VCF Operations) via Salt Pillar (Part 2).

These are independent: a minion can be connected to the master (Part 1)
before it has any pillar data configured (Part 2) - it just can't run any
`saltext.vcf` operations against a real target until Part 2 is done.

---

## Part 1 - Bring up the minion and connect it to the Salt master

### Prerequisites

- The `salt-minion-vcf` image built locally or available in a registry you
  can pull from (`docker build -t salt-minion-vcf:0.1.0 .` from the repo
  root - see the top-level [`README.md`](../README.md#quick-start) if this
  hasn't been done yet).
- `docker` on PATH (Docker mode), or `helm` + `kubectl` on PATH (Kubernetes mode).
- Network access from wherever you run the script to your VCF Operations
  instance's Suite API, and from the minion's host/cluster to the Salt
  master (`SALT_MASTER_PORT`/`4506`, `SALT_PUBLISH_PORT`/`4505`).
- Credentials for a VCF Operations user with the Salt Management view/manage
  privileges, and the resource UUID of the VCF instance whose master you
  want to attach to.

### Procedure

Run the onboarding script:

```bash
python3 scripts/onboarding/vcf-ops-onboard.py \
  --ops-host vcfops.example.com \
  --ops-user admin \
  --vcf-instance-id <vcf-instance-resource-id> \
  --deployment docker    # or: kubernetes
```

Everything not passed as a flag is prompted for interactively, with a
review/confirm summary shown before anything is actually started. The script
handles, in order:

1. Logs in to VCF Operations.
2. Resolves the Salt master governing the given VCF instance.
3. Computes the master's identity fingerprint (`master_finger`) - used for
   the Kubernetes/Helm path and for your own reference/audit trail.
4. Starts the minion (`docker run`, or `helm upgrade --install`), passing it
   the master FQDN and a freshly generated minion ID. The minion generates
   its own RSA keypair locally on first start - the private key never
   leaves it, and VCF Operations credentials never reach it. Docker minions
   are pre-seeded with the master's actual public key
   (`SALT_MASTER_PUBKEY_B64`, written to `minion_master.pub`) rather than
   just a fingerprint, so they trust it directly on first connect - the
   same approach VCF's own internal component minions use. FIPS-compliant
   crypto (`OAEP-SHA224`/`PKCS1v15-SHA224`) is on by default, matching what
   VCF-managed Salt masters require - see Troubleshooting below.
5. Reads back the minion's public key.
6. Registers that key as trusted with the master.
7. Waits until the master has actually accepted the connection.

Use `--dry-run` first if you want to preview every command and API call
without executing anything. See `--help` for the full flag list, or
[`scripts/onboarding/README.md`](../scripts/onboarding/README.md) for a
complete walkthrough of every option.

### Verification

From the Salt master:

```bash
salt-key -L                    # minion should be under "Accepted Keys"
salt '<minion-id>' test.ping   # should return True
```

From the minion side (Docker):

```bash
docker exec salt-minion-vcf salt-call --local test.version
docker logs salt-minion-vcf | grep "Minion is ready to receive requests"
```

(Kubernetes: substitute `kubectl exec -n <namespace> <pod> --` /
`kubectl logs -n <namespace> <pod>`.)

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED: self signed certificate` on login | VCF Operations uses a self-signed/internal CA cert | Pass `--insecure` |
| `pull access denied for salt-minion-vcf` | Image not built locally yet - Docker tried to pull it from Docker Hub | `docker build -t salt-minion-vcf:0.1.0 .` from the repo root first, or point `--image` at wherever you built/pushed it |
| `container name already in use` on retry | A previous failed attempt left a stopped container behind | The script now detects this and offers to remove it automatically |
| `[CRITICAL] Unable to securely set the permissions of "/etc/salt/pki/minion"` / `PermissionError: Permission denied: '/etc/salt/pki/minion/tmp...'` | The PKI volume value was a host path (bind mount), not a named Docker volume - the container runs as non-root uid `10000`, and a bind-mounted host directory doesn't inherit the image's baked-in ownership | Use a plain volume name (e.g. `salt-minion-vcf-pki`, the default) instead of an absolute path. If you specifically need a host path, `chown -R 10000:10000` it first |
| Minion key is accepted on the master (`salt-key -L` shows it), but the onboarding script (or the image's own `HEALTHCHECK`/`readinessProbe`) never reports it connected, and can even appear to hang indefinitely | `status.master`'s answer depends on `master_alive_interval` being configured on the minion, which the entrypoint doesn't set by default - it can under-report even once genuinely connected. Worse, `salt-call status.master` (without `--local`) tries to compile pillar from the master before running the check at all, which can block for a long time (or indefinitely) while the minion is still mid-handshake | The onboarding script now checks the minion's logs for the event-driven `Minion is ready to receive requests` line *first* (a plain `docker logs`/`kubectl logs` call that can't itself hang), and only falls back to a time-boxed (8s) `salt-call --local status.master` if that line hasn't appeared yet. If you're checking manually, prefer that log line or `salt '<minion-id>' test.ping` from the master over `salt-call status.master` |
| Minion loops forever on `[ERROR] Sign-in attempt failed: Some exception handling minion payload` (sometimes preceded by `{'ret': 'bad sig algo'}`), even though the key is accepted on the master and both ports (4505/4506) are reachable | The master runs FIPS-validated crypto and doesn't implement SHA-1 for RSA OAEP/PKCS1v15 at all - a minion defaulting to SHA-1 doesn't get a clean rejection, it crashes the master's payload handler on every single auth attempt (visible on the master's own log as `salt.channel.server: Some exception handling a payload from minion`) | FIPS mode (`fips_mode: True`, `encryption_algorithm: OAEP-SHA224`, `signing_algorithm: PKCS1v15-SHA224`) is on by default as of this image - see `docker-entrypoint.sh`. If you're running an older image or need to override it, set `SALT_FIPS_MODE=false` only if you've confirmed your master is *not* FIPS-enforced |
| Minion key is accepted, FIPS is enabled, `_auth` completes without crashing, but the minion still never connects, with `[CRITICAL] The specified fingerprint in the master configuration file ... Does not match the authenticating master's key` | `master_finger`, computed by the onboarding script from the same `masterPublicKey` VCF Operations returns, did not match what the live master actually presented on the wire in this deployment - the underlying cause wasn't pinned down (possibly a RaaS/SSEAPI-key-vs-Salt-PKI-key distinction specific to this environment), but VCF's own internal component minions never do this fingerprint check at all - they're handed the master's public key directly and trust it | The onboarding script now pre-seeds the master's actual public key directly (`SALT_MASTER_PUBKEY_B64`, written to `/etc/salt/pki/minion/minion_master.pub`) instead of computing/checking a fingerprint, matching how internal component minions are bootstrapped. This is the default behavior as of this image/script version - `master_finger`/`SALT_MASTER_FINGER` is only used by the Kubernetes/Helm path today |

---

## Part 2 - Pillar data for connecting to VCF components

`saltext.vcf` reads all target credentials from Salt Pillar under
`saltext.vcf.<target>`. There is **no way to pass these credentials through
the onboarding script or through `SALT_MASTER`/`SALT_MINION_ID`-style
environment variables** - they must be supplied as pillar data, by design
(see [`docs/security.md`](security.md)).

### Supported targets

| Target key | Component | Example file |
|---|---|---|
| `vcenter` | vCenter Server (REST + SOAP/pyVmomi) | [`pillar/vcenter.sls.example`](../pillar/vcenter.sls.example) |
| `nsx` | NSX Manager (Policy API) | [`pillar/nsx.sls.example`](../pillar/nsx.sls.example) |
| `sddc_manager` | SDDC Manager | [`pillar/sddc_manager.sls.example`](../pillar/sddc_manager.sls.example) |
| `esxi` | Standalone/unmanaged ESXi hosts only - a host already joined to vCenter uses the `vcenter` block instead (its REST session API is blocked once managed) | [`pillar/esxi.sls.example`](../pillar/esxi.sls.example) |
| `vcfa` | VCF Automation (Aria Automation) | [`pillar/vcfa.sls.example`](../pillar/vcfa.sls.example) |
| `vcf_installer` | VCF Installer (Day-0 bringup, formerly Cloud Builder) | [`pillar/vcf_installer.sls.example`](../pillar/vcf_installer.sls.example) |
| `vcf_ops` | VCF Operations (Suite API) | [`pillar/vcf_ops.sls.example`](../pillar/vcf_ops.sls.example) |

Each file follows the same shape - copy it, rename it (drop `.example`), and
fill in real values:

```yaml
saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test
    username: administrator@vsphere.local
    password: secret
    verify_ssl: false
```

**Never commit the real `*.sls` files** - only `*.sls.example` is tracked;
the rest are gitignored.

### Which path applies depends on how you'll run VCF operations

This is the detail most likely to cause confusion - pick the path that
matches how you intend to trigger `saltext.vcf` calls against this minion.

#### Path 1 - Locally inside the container (`salt-call --local`)

Use this if scripts inside the container/Pod call `saltext.vcf` directly, or
for ad-hoc testing. The minion always has `pillar_roots` pointed at its own
local pillar directory; `top.sls` is auto-generated to match `'*'` against
whatever `*.sls` files are present.

**Docker** - bind-mount the directory at container start:

```bash
docker run -d --name salt-minion-vcf \
  -e SALT_MASTER=<host> \
  -v salt-minion-vcf-pki:/etc/salt/pki/minion \
  -v "$(pwd)/pillar:/etc/salt/pillar" \
  salt-minion-vcf:0.1.0
```

Or push files into an already-running container (no restart needed -
`salt-call --local` recompiles pillar from disk on every call):

```bash
./scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls
```

**Kubernetes** - create a Secret containing your `*.sls` files plus a
`top.sls` matching `'*'` (a Pod only ever runs one minion ID, so a wildcard
is always sufficient here):

```bash
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

To update without restarting the Pod, update the Secret object itself -
kubelet re-syncs the mounted volume automatically (typically within ~60-90s).

**Verify:**

```bash
docker exec salt-minion-vcf salt-call --local pillar.items
docker exec salt-minion-vcf salt-call --local vcf_vcenter_vm.list_
```

#### Path 2 - Dispatched from the Salt Master (`salt '<minion-id>' ...`)

This is the intended production model: VCF Operations/RaaS dispatches jobs
to the minion from the master. **Jobs run this way are compiled using the
Master's own `pillar_roots` - anything mounted into this container (Path 1)
is invisible to them.** The customer's Salt master admin needs pillar data
on the master side (e.g. `/srv/pillar`), targeted by this minion's ID - see
[`pillar/master-top.sls.example`](../pillar/master-top.sls.example):

```yaml
# /srv/pillar/top.sls on the customer's Salt Master
base:
  '<minion-id>':
    - vcenter
```

using the identical `saltext.vcf.<target>` structure as the `pillar/*.sls.example`
files in this repo. This is outside this repo's control (it's the master
admin's own `pillar_roots`); for production, prefer an `ext_pillar` backed by
a secrets manager (e.g. Vault) over plain files in `/srv/pillar`.

**Verify (run from the master, not `salt-call --local`):**

```bash
salt '<minion-id>' pillar.items
salt '<minion-id>' test.ping
```

If you need both models at once (local ad-hoc testing *and* master-dispatched
production jobs), configure Path 1 and Path 2 independently with the same
values - they don't conflict, since each is scoped to a different pillar_roots.

### Security reminders

See [`docs/security.md`](security.md) for the full list. The two most
relevant here:

- Never put VCF credentials in a Kubernetes ConfigMap - use a Secret.
- Only `*.sls.example` files are tracked in git; never force-add or commit
  a real `*.sls` file.
