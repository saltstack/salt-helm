# Runbook: Remove Unauthorized/Unused USB Controllers from VMs (KB-316384)

This runbook walks through removing USB 2.0 (EHCI+UHCI) / USB 3.x (xHCI)
controllers from VMs managed by vCenter, using the `salt-minion-vcf`
container/Pod. `saltext-vcf` is already embedded in the `salt-minion-vcf`
image, so the `vcf_vim_vm_devices` module used below is available as soon
as the minion starts - no extra install step.

**Prerequisite:** complete [`runbook.md`](external-minion-configuration) first. The minion
container/Pod needs a Salt master to start against (`SALT_MASTER`) even if
every command below is run locally with `salt-call --local` - there is no
masterless mode for this image. `runbook.md` Part 1 brings the minion up and
connects it to a master; Part 2 is the general pillar pattern this runbook
reuses in Step 1 below.

This runbook shows Docker commands throughout. Everything here works
identically from a Kubernetes Pod - swap `docker exec salt-minion-vcf ...`
for `kubectl exec -n <namespace> <pod> -- ...`, and see `runbook.md` Part 2
for the Kubernetes Secret equivalent of the pillar push in Step 1.

---

## Step 1 - Point the minion at your vCenter (pillar data)

`saltext.vcf` reads the vCenter to scan from Salt Pillar under
`saltext.vcf.vcenter`. Copy the example and fill in your vCenter's details:

```bash
cp pillar/vcenter.sls.example pillar/vcenter.sls
```

```yaml
# pillar/vcenter.sls
saltext.vcf:
  vcenter:
    host: mgmt-vc.example.test          # your vCenter FQDN/IP
    username: administrator@vsphere.local
    password: secret
    verify_ssl: false
```

Push it into the running container:

```bash
./scripts/pillar-push.sh salt-minion-vcf pillar/vcenter.sls
```

(Running on Kubernetes instead: update the pillar Secret in place - see
`runbook.md` Part 2, Path 1, for the exact `kubectl create secret ...
--dry-run=client -o yaml | kubectl apply -f -` command. Kubelet re-syncs the
mounted Secret automatically, no Pod restart needed.)

Confirm the minion can see it:

```bash
docker exec salt-minion-vcf salt-call --local pillar.get saltext.vcf:vcenter
```

**Have more than one vCenter to target?** Add extra targets under a
`profiles` key in the same file, then pass `profile=<name>` on any command
below to point it at that one instead of the default:

```yaml
saltext.vcf:
  vcenter:                 # default target
    host: mgmt-vc.example.test
    ...
  profiles:
    dr-site:
      vcenter:
        host: dr-vc.example.test
        username: administrator@vsphere.local
        password: secret
        verify_ssl: false
```

## Step 2 - (Optional) Set the removal behavior

By default, VMs that aren't in the vSphere "connected" state are reported
but left alone (their hardware can't be reconfigured anyway). This is
controlled by one pillar key, `usb-controller-removal.connected_only`
(default `true`). Only change it if you've confirmed disconnected VMs in
your environment are safe to reconfigure:

```bash
cat > pillar/usb-controller-removal.sls <<'EOF'
usb-controller-removal:
  connected_only: false
EOF
./scripts/pillar-push.sh salt-minion-vcf pillar/usb-controller-removal.sls
```

Skip this step to keep the safe default.

## Step 3 - Audit: see what would be affected

Read-only - lists every VM that currently has a USB controller, with no
changes made:

```bash
docker exec salt-minion-vcf salt-call --local vcf_vim_vm_devices.list_vms_with_usb_controllers
```

Review this list before continuing.

## Step 4 - Dry run

Confirms exactly what the real run will do, without touching anything
(`test=True`):

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vim_vm_devices.usb_controllers_absent \
  name=usb-controllers-absent \
  connected_only=True \
  test=True
```

Check `changes.would_remove` in the output - it lists each affected VM and
the exact device(s) that would be removed. **Removing a USB controller
disconnects any USB device currently passed through to that VM** (license
dongles, smartcard readers, USB storage) - review this list carefully
before Step 5.

## Step 5 - Apply

Once you've reviewed the dry-run list, run the same command without
`test=True`:

```bash
docker exec salt-minion-vcf salt-call --local state.single \
  vcf_vim_vm_devices.usb_controllers_absent \
  name=usb-controllers-absent \
  connected_only=True
```

`changes.removed` lists each VM the controller was actually removed from.
If `changes.errors` appears, those specific VMs failed (e.g. permissions,
VM mid-migration) and were not touched - see Troubleshooting below.

## Step 6 - Verify

```bash
docker exec salt-minion-vcf salt-call --local vcf_vim_vm_devices.list_vms_with_usb_controllers
```

Should now be empty, or only list VMs intentionally skipped in Step 1/2
(disconnected, with `connected_only: true`).

---

## Optional - Act on a single VM

If Step 3's audit flags one specific VM you'd rather handle by itself
instead of the fleet-wide sweep in Steps 4-5:

```bash
docker exec salt-minion-vcf salt-call --local vcf_vim_vm_devices.usb_controllers_list <vm>
docker exec salt-minion-vcf salt-call --local vcf_vim_vm_devices.usb_controllers_remove <vm>
```

These are direct calls, not state functions - there is no `test=True`
dry-run gate here, so always check with `usb_controllers_list` first.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pillar.get saltext.vcf:vcenter` returns empty | Pillar not pushed yet, or `top.sls` doesn't reference it | Re-run Step 1's push command; see `runbook.md` Part 2 if still empty |
| Dry run shows VMs, but apply's `changes.removed` is shorter | A VM's USB controller changed between the two runs | Re-run Step 3 immediately before Step 5 |
| `changes.errors` lists a VM after apply | `ReconfigVM` failed for that VM specifically | Fix the underlying issue (permissions, VM state) then re-run `usb_controllers_remove` for just that VM |
| Command reports the wrong VMs / wrong vCenter | Targeting the default vCenter instead of a `profiles` entry | Add `profile=<name>` to the command, matching Step 1 |

---

## Risk summary

- Fleet-wide by default: every VM visible to the targeted vCenter is
  scanned and, on apply, has its USB controller removed if present and
  connected.
- No rollback - if a VM needs its USB controller back, it must be re-added
  manually.
- Always run Step 4 (dry run) and review the list before Step 5 (apply).

See [`docs/security.md`](security.md) for general credential-handling
reminders - this use case doesn't require any credentials beyond the
vCenter pillar block set up in Step 1.
