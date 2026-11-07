# Registering an existing fstab-managed image

Beta 2 introduced **reviewed GUI adoption** of a valid, already-mounted ext4 loop
image. Registration preserves the backing file, mountpoint, mount, fstab bytes and
options, ownership, permissions and contents. It does not unmount, format, copy,
remount or stop FTP. The CLI/configuration path remains available separately.

## Recommended GUI procedure

1. Register the physical drive through Setup, keeping its verified existing mount.
2. Open **Virtual Disk Images → Add existing image** for that drive. Scan for the
   `.img` file, or enter its full path in Advanced. Choose **Add selected image**
   or **Review existing image**.
3. Review **Adopt existing mounted image?**. Check the detected backing path,
   filesystem UUID, existing mountpoint and Mount on recovery preference.
4. Confirm once. The backend rechecks the physical filesystem, image superblock,
   loop backing file/device/inode, zero offset/size limit, mount and exact fstab
   entry under the existing locks. It backs up the old configuration privately,
   saves only the image registration and verifies readback. A fresh repeated
   adoption is a no-op that retains saved names and recovery choices.
5. Check the registered image's verified status. Select it for each app only when
   required; ordinary-folder apps do not need a virtual image.
6. After recovery ownership is agreed, start monitoring and review **Automatic
   recovery** in Manage Drive. Beta 3 accepts verified registered child image
   mounts while rechecking filesystem UUIDs, loop backing identity and topology.
   Unknown, stacked, shared or changed mounts still refuse activation. Actual
   recovery/remount operations retain their separate cleanup and safety guards.
7. Configure and explicitly test SMTP in **Email & Notifications**, then enable
   the drive's notifications. Missing or unreadable email settings refuse this
   preference change without stopping monitoring or saving it.

The existing mount must be unambiguous ext4, read/write and healthy. Paths must be
normalized, inside the verified physical mount, and free of symlinks. Duplicate
fstab entries/aliases, conflicting registrations, unsupported options, changed
identity or active storage/recovery operations refuse adoption without changing
storage. The existing absolute backing-file fstab source and supported options are
retained verbatim; UUID/label-only loop definitions need administrator review.
An already-active USW monitor is briefly paused under the existing image-setup
locks and resumed with the new configuration; an inactive monitor stays inactive.
No other service is stopped. Configuration backup is under that drive's private
`image-backups` state directory. Do not detach storage to bypass a refusal.

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

## Optional CLI procedure for a new, otherwise unconfigured drive

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
For an established profile, use reviewed GUI adoption above; it preserves other
settings. Do not populate both `dependent` and `images` with the same identity.

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

Source: `web_images.mounted_adoption`, `web_protection.planning_backing`, `cli.setup`,
`settings.storage_images` and `engine.dependent_metadata`. Automated checks use
disposable ext4 files, real probes/configuration locks and simulated refusal cases.
Beta 3 also tests the full setup sequence on actual disposable loop mounts in a
private mount namespace, with simulated USB discovery and service control.
Target-host image adoption, recovery and consumer readiness still require operator
acceptance; no such acceptance is claimed by the release tests.
