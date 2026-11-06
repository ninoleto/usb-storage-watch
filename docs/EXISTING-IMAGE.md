# Registering an existing fstab-managed image

The CLI/configuration supports an existing ext4 loop image without creating,
formatting, copying, moving or mounting it. This is different from the dashboard's
**Add existing image** workflow: that UI refuses a mountpoint already in use, an
existing fstab entry or an attached image. Do not remove fstab entries or detach
storage to bypass that UI limitation.

## Required review before handover

- Privately back up the existing configuration, fstab, watcher/helper scripts,
  service units/drop-ins, enablement and application data. Review their stop and
  recovery behavior before disabling the old automation. Only one recovery owner
  may be active. Registration itself does not stop the old watcher.
- Confirm the physical filesystem UUID, exact mounted target and read/write ext4
  state. Confirm the image's ext4 UUID, current loop source, full backing path,
  backing inode/filesystem, zero offset/size limit and current mountpoint.
  Both image and target must be inside the selected physical filesystem, without
  symlinks or duplicate/conflicting identities. Identify all image users, including
  non-Docker services: registering an image does not authorize stopping them.
- Review the exact main and image fstab lines. Each target must have exactly one
  entry. The main source must be `UUID=<physical UUID>`; the image source must be
  its absolute backing-file path; both must declare ext4. Record the existing
  comma-separated options, including `loop` for the image. Do not substitute
  example options or silently change fstab. Unsupported options need review first.
- Keep USW monitoring inactive and ensure no active incident or pending USB-enable
  obligation. Leave boot/app automation unconfigured until storage and policy
  ownership have been reviewed. Registration is configuration-only, so the
  existing healthy mount can remain mounted.

## CLI procedure for a new, otherwise unconfigured drive

Run on the target host only in the approved handover window:

```sh
sudo -n usb-storage-watch setup
```

Choose the disk by its verified UUID, not a remembered device name. Answer:

| Prompt | Answer |
| --- | --- |
| Permanent mountpoint | Existing physical mountpoint |
| Email label | A readable drive label |
| Configure email notifications? | No for initial storage handover; configure separately |
| Enable automatic guarded normal mounts? | Yes only after fstab/ownership review |
| Exact comma-separated options from the disk fstab entry | Existing physical entry's exact options |
| Monitor an existing dependent ext4 loop image? | Yes |
| Loop filesystem UUID | Verified existing image UUID |
| Loop mountpoint under the primary disk | Existing image mountpoint |
| Backing image path under the primary disk | Existing backing-file path |
| Exact loop fstab options | Existing image entry's exact options, including `loop` |
| Restart selected Docker containers after this drive recovers? | No; select exact IDs later in Docker Apps |
| Customize monitoring/recovery timing? | No unless separately reviewed |
| Save this configuration? | Yes after reviewing the summary |

This saves the `dependent` configuration and checks the reviewed fstab entries.
It does not start monitoring, mount/unmount, format the image, edit fstab or start
containers. `dependent.enabled=true` includes this existing image in the drive's
monitoring and guarded mount recovery. It is not an implied dependency of every app.

Then validate configuration and inspect existing storage:

```sh
sudo -n usb-storage-watch validate
sudo -n usb-storage-watch diagnose
```

Diagnosis reads storage and can record USW identity metadata; it does not operate
storage or containers. Require the expected main **and image** status, not just its
exit code. Check the backing-file/inode identity against the earlier loop inventory;
registration alone is not proof that the supplied UUID belongs to that file.
The recovery engine re-verifies UUID/ext4/mount and loop backing identity before use.

The commands above target the original `legacy` drive profile. If a profile was
already created through the dashboard, identify its exact profile UUID first and
use `sudo -n env USB_STORAGE_WATCH_DRIVE=<profile-UUID> usb-storage-watch setup`
(and the same environment for validation/diagnosis). Never create a second profile
for the same physical disk. Do not rerun the setup wizard on an established app
configuration: it resets Docker selections, USB enablement and notification choices.
For an established profile, the documented `dependent` fields may instead be edited
privately while its monitor is stopped and idle, with a configuration backup,
validation and review preserving every other field. Do not populate both
`dependent` and `images` with the same image identity.

Keep fstab as the persistent mount definition and USW as the sole outage-recovery
owner after the old watcher/helper has been safely disabled. Configure apps through
the normal exact-ID review/save flow afterward. Ordinary-folder apps should have
no image choices selected unless they actually need the image. Recovery must still
refuse unknown consumers or busy storage; do not force an unmount. Native FTP,
media servers and backup jobs need separate shutdown/reactivation coordination.
The optional systemd-service restart after recovery is not a pre-unmount stop or
boot storage guard. A point-in-time empty process scan does not prove no consumers.

## Rollback and evidence

With no active operation, disable the new automation before restoring the reviewed
old watcher/settings. Keep only one recovery owner. Restore the previous USW
configuration if needed, retaining later incident receipts. The image, fstab and
data never moved, so no image copy-back is required.

Source: `cli.setup`, `settings.storage_images`, `engine.fstab_check` and
`engine.verify_dependent`. A synthetic CLI regression exercises existing fstab
identity/options and verifies configuration-only registration with no OS/storage
command. Actual target-host options, permissions, consumers and readiness still
require review; no target-host migration is claimed tested.
