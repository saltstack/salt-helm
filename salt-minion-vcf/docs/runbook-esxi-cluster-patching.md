# Runbook: Patch an ESXi Cluster via vSphere Lifecycle Manager (vLCM)

This runbook walks through patching every ESXi host in a vSphere cluster
using the desired-image vLCM workflow (configure a depot, define/commit a
desired image, set the apply policy, then check/precheck/stage/remediate),
using the `salt-minion-vcf` container/Pod. `saltext-vcf` is already
embedded in the image, so the `vcf_esxi_vlcm` module used below is
available as soon as the minion starts.

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

`vcf_esxi_vlcm` reuses this same vCenter session - no separate connection
config for this domain.

## Step 2 - Find your cluster's ID

vLCM addresses clusters by their vCenter managed-object ID (e.g.
`domain-c9`), not by display name:

```bash
docker exec salt-minion-vcf salt-call --local vcf_vcenter_cluster.list_
```

Note the `domain-c...` id for the cluster you're patching - it's used as
`cluster_id` (or as the state's `name`) in every step below.

## Step 3 - Set the patch target (pillar)

Everything specific to this cluster's patch run goes under
`saltext.vcf.esxi_vlcm`, as a peer of `vcenter`:

```bash
cat > pillar/esxi_vlcm.sls <<'EOF'
saltext.vcf:
  esxi_vlcm:
    offline_depot:
      location: http://repo.example.com/VMware-ESXi-9.2.0.0.25504872-depot.zip
    image:
      spec:
        base_image:
          version: "9.2.0.0.25504872"
    policy:
      enable_quick_boot: true
    task:
      timeout: 14400        # 4h - bump for large clusters/slow links
      poll_interval: 30
EOF
./scripts/pillar-push.sh salt-minion-vcf pillar/esxi_vlcm.sls
```

Every command below falls back to these pillar values for any argument you
don't pass explicitly. Nothing here is a credential, so this file doesn't
need the same secrecy as `vcenter.sls` - but keep it out of git anyway
(image version/URLs are still environment-specific).

## Step 4 - Configure the depot

Registers where ESXi update payloads come from. Idempotent - a no-op if a
depot at this location already exists:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.depot_configured name=patch-depot test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.depot_configured name=patch-depot
```

Using an online (vendor update repository) depot instead of an offline
ZIP? Set `saltext.vcf.esxi_vlcm.online_depot.location` in Step 3 and pass
`depot_type=online` on this command instead.

## Step 5 - Set the cluster's desired image

Replace `<cluster_id>` with the id from Step 2 in every command from here
on:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.image_configured name=<cluster_id> test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.image_configured name=<cluster_id>
```

Idempotent on the committed version - a no-op if the cluster is already at
Step 3's target version. If the cluster already has an uncommitted draft,
the default behavior (`existing_draft_action=delete`) discards it and
proceeds - pass `existing_draft_action=reuse` or `=fail` instead if that's
not what you want.

## Step 6 - Set the apply policy

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.policy_configured name=<cluster_id> test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.policy_configured name=<cluster_id>
```

Idempotent on the keys you set in Step 3's `policy` block (e.g.
`enable_quick_boot`) - other fields vCenter fills in on its own don't
trigger a spurious change.

## Step 7 - Compliance scan

Checks which hosts are out of compliance with the desired image. Always
runs (no cheap "already scanned" check) - inexpensive and non-disruptive:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.compliance_checked name=<cluster_id> test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.compliance_checked name=<cluster_id>
```

## Step 8 - Precheck

Runs vCenter's own remediation prechecks (capacity, DRS/HA constraints,
hardware compatibility) **without changing anything**. Always run this and
review the result before Step 10:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.prechecked name=<cluster_id>
```

## Step 9 - Stage

Pre-downloads the image to each host, without applying it yet - shortens
the maintenance window in Step 10:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.staged name=<cluster_id> test=True

docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.staged name=<cluster_id>
```

## Step 10 - Remediate

**This is the disruptive step** - see [Risk summary](#risk-summary) first.
Applies the desired image to every host in the cluster: hosts enter
maintenance mode, install the image, and reboot, one at a time (DRS/vMotion
evacuates VMs off each host first, if enabled and there's spare capacity).

```bash
# Dry run - only reports what would happen, no remediation call is made
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.remediated name=<cluster_id> test=True

# Real remediation
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.remediated name=<cluster_id>
```

This calls vCenter with `accept_eula=True` by default - confirm your
organization is fine with the image's EULA being auto-accepted before
running this for real. This is also the longest step; the default task
timeout (`saltext.vcf.esxi_vlcm.task.timeout`, 4 hours) is a floor for a
multi-host cluster, not a ceiling - increase it in Step 3 for larger
clusters.

## Step 11 - Verify

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_esxi_vlcm.reported name=<cluster_id>
```

Always a read-only no-op; the comment summarizes whether a last-check,
apply-impact, and last-apply report are present. Follow up with the
execution-module equivalents for the full payload if you need the details:

```bash
docker exec salt-minion-vcf salt-call --local vcf_esxi_vlcm.compliance_scan <cluster_id>
```

Then re-run Step 2's cluster list / your own host inventory check to
confirm every host is now on the target build.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Step 5 fails: "cluster already has draft ..." | A previous partial run left an uncommitted draft, and you passed `existing_draft_action=fail` | Re-run with the default (`delete`) to discard it, or `existing_draft_action=reuse` if that draft is already at your target version |
| Step 5 fails: "commit reported success but cluster version is ..." | vCenter's commit API returned success without actually moving the version | Re-run Step 5 - if it repeats, check vCenter's own recent tasks/events for the cluster before retrying again |
| Step 10 blocks for a very long time / times out | Default `task.timeout` (4h) is too short for this cluster's host count, or DRS can't evacuate VMs fast enough | Raise `saltext.vcf.esxi_vlcm.task.timeout`/`task.poll_interval` in Step 3's pillar and re-run; also check cluster capacity/HA admission control if evacuation itself is slow |
| Step 8's precheck reports failures | Real compatibility/capacity/HA issues on specific hosts | Resolve the specific host issue vCenter reports before proceeding to Step 10 - do not skip a failing precheck |
| `depot_configured` (Step 4) fails: "requires 'location'" | Pillar not pushed, or `depot_type` doesn't match which section you filled in (`offline_depot` vs `online_depot`) | Re-check Step 3's pillar push and that `depot_type` (default `offline`) matches the section you populated |

---

## Risk summary

- **Host reboots, cluster-wide.** Every host in the cluster is patched by
  Step 10 unless you scope it with `hosts=` on the compliance/stage steps
  first (`remediated` itself always targets the whole cluster - there is
  no host filter on that step).
- **VM impact depends on DRS/HA headroom.** If the cluster can't fully
  evacuate a host being patched (insufficient spare capacity, DRS
  disabled, affinity rules), VMs on that host may experience downtime
  instead of a live migration.
- **No automated rollback.** Reverting means re-running this workflow
  against a prior image version, not an undo button.
- **Always run Step 8 (precheck) and read the result before Step 10.** A
  passing precheck is the closest thing to a safety gate this workflow
  has.
- Step 10 accepts the image's EULA on your behalf by default
  (`accept_eula=True`).

See [`docs/security.md`](security.md) for general credential-handling
reminders - this use case doesn't require any credentials beyond the
vCenter pillar block set up in Step 1.
