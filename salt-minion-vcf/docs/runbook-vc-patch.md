# Runbook: Patch the vCenter Server Appliance (VCSA Self-Update)

This runbook walks through patching the vCenter Server Appliance itself
(VAMI's `/rest/appliance/update/...` self-update workflow: configure a
repository, stage a build, precheck, install), using the `salt-minion-vcf`
container/Pod. `saltext-vcf` is already embedded in the image, so the
`vcf_vc_patch` module used below is available as soon as the minion starts.

**Prerequisite:** complete [`runbook.md`](external-minion-configuration) first. The minion
container/Pod needs a Salt master to start against (`SALT_MASTER`) even if
every command below is run locally with `salt-call --local` - there is no
masterless mode for this image.

This runbook shows Docker commands throughout. Everything works
identically from a Kubernetes Pod - swap `docker exec salt-minion-vcf ...`
for `kubectl exec -n <namespace> <pod> -- ...`, and see `runbook.md` Part 2
for the Kubernetes Secret equivalent of the pillar pushes below.

---

## Step 1 - Point the minion at your vCenter

Same vCenter pillar block every other runbook in this series uses - skip
if already done:

```bash
cp pillar/vcenter.sls.example pillar/vcenter.sls
```

```yaml
# pillar/vcenter.sls
saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test
    username: administrator@vsphere.local
    password: secret
    verify_ssl: false
```

```bash
./scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls
docker exec salt-minion-vcf salt-call --local pillar.get saltext.vcf:vcenter
```

`vcf_vc_patch` reuses this same vCenter session for its `/rest/...` calls -
no separate login step.

## Step 2 - Set the patch target (pillar)

Everything specific to this patch run - which build to install, the
repository it comes from, and the SSO admin password required to actually
install - goes under `saltext.vcf.vc_patch`, as a peer of `vcenter` in the
same pillar tree:

```bash
cat > pillar/vc_patch.sls <<'EOF'
saltext.vcf:
  vc_patch:
    repository_url: http://repo.example.com/vcsa/
    version: "9.0.1.0.12345"
    sso_password: secret          # the vCenter SSO admin password - VAMI
                                   # requires re-confirming it for install,
                                   # even though the session above is
                                   # already authenticated
    auto_stage: false
    certificate_check: true
EOF
./scripts/pillar-push.sh salt-minion-vcf pillar/vc_patch.sls
```

`sso_password` is as sensitive as the `vcenter.password` above - never
commit `vc_patch.sls`, same as `vcenter.sls`.

Every command below falls back to these pillar values for any argument you
don't pass explicitly, so once this is set you generally don't need to
repeat `version=`/`repository_url=` on the command line.

## Step 3 - Check current state before touching anything

Read-only:

```bash
docker exec salt-minion-vcf salt-call --local vcf_vc_patch.get_update_policy
docker exec salt-minion-vcf salt-call --local vcf_vc_patch.list_pending_updates
docker exec salt-minion-vcf salt-call --local vcf_vc_patch.get_update_status
```

Confirm the version you set in Step 2 actually shows up as a pending
update before continuing.

## Step 4 - Configure the update repository

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.repository_configured name=vc-repo test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.repository_configured name=vc-repo
```

This always re-applies (VAMI's policy-set replaces the whole policy each
time), but re-running with the same inputs is a safe no-op in effect.

## Step 5 - Stage the update

Downloads and stages the resolved build, then runs a precheck. Idempotent -
a no-op if this version is already staged:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.update_prepared name=vc-staged test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.update_prepared name=vc-staged
```

This step can legitimately take a while (default timeout: 1 hour, via
`stage_timeout_seconds`). Check `changes.precheck` in the output for
warnings/errors before proceeding - a failed precheck here (disk space,
compatibility) means Step 6 will fail too.

## Step 6 - Install

**This is the disruptive step** - see [Risk summary](#risk-summary) before
running it for real. Take a vCenter backup/snapshot first; there is no
automated rollback.

```bash
# Dry run - only reports what would happen, no install call is made
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.update_installed name=vc-installed test=True

# Real install
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vc_patch.update_installed name=vc-installed
```

The appliance reboots as part of this. The command will block (or the
minion's own connection to the master may briefly appear to drop, if the
Salt master's network path routes through the same vCenter environment)
until the install/monitor cycle completes or `install_timeout_seconds`
(default: 2 hours) is hit.

## Step 7 - Verify

```bash
docker exec salt-minion-vcf salt-call --local vcf_vc_patch.get_update_status
docker exec salt-minion-vcf salt-call --local vcf_vc_patch.get_update_history
```

Confirm the installed version matches Step 2's `version`, and the history
entry for this install shows success.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `precheck.not_allowed_error` during Step 5 | Staging is still in progress; VAMI refuses a precheck concurrently | The state already retries this internally while polling stage progress - if it still fails, staging likely didn't complete; check `changes.stage`/`changes.monitor_stage` in the Step 5 output |
| Step 5 reports a client-side timeout but the update later shows staged anyway | A slow link can time out the stage call itself even though VAMI's job kept running server-side | The state already falls back to polling `get_staged_update` after a stage-timeout error - re-run Step 5 once if it still reports failure, it should now see the completed stage |
| `401`/`403` from any `vcf_vc_patch.*` call | This vCenter build doesn't accept the `/api/session` token on the legacy `/rest/...` namespace | Verify with a read-only call (`get_update_policy`) first; if it fails, this vCenter build isn't supported for self-patching over this API |
| Step 6 fails with an authentication/password error | `sso_password` in `pillar/vc_patch.sls` is wrong or wasn't pushed | Re-check Step 2's pillar push, re-verify with `pillar.get saltext.vcf:vc_patch` (redact before sharing output - this echoes the password back) |
| Step 4/5/6 pick up the wrong `version`/`repository_url` | An explicit CLI argument or a stale pillar push is overriding what you expect | Explicit command-line args always win over pillar - drop them from the command to use Step 2's pillar values, and re-push if the pillar itself is stale |

---

## Risk summary

- **Appliance downtime.** The vCenter Server Appliance restarts its
  services (and the appliance OS itself, for many updates) during install.
  Plan a maintenance window - vCenter-dependent operations (this minion's
  own vCenter-backed states included) are unavailable for the duration.
- **No automated rollback.** If the install fails partway or the result is
  unacceptable, recovery is via your own pre-patch backup/snapshot, not
  anything this module provides.
- **Always run Step 5 and Step 6 with `test=True` first**, and read
  `changes.precheck` before the real install.
- `sso_password` is a credential with the same sensitivity as the vCenter
  admin password - never commit it, same handling as `pillar/vcenter.sls`.

See [`docs/security.md`](security.md) for general credential-handling
reminders.
