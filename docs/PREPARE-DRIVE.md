# Prepare drive

Open **Prepare drive** from the main navigation. Select an unused USB
drive, choose **Erase and prepare for Linux**, and optionally enter a name.
Review its model, capacity and serial number. Tick the permanent-erasure warning
and type the displayed disk-specific confirmation before proceeding.

The application creates one GPT Linux partition with `sfdisk`, creates ext4 with
`mkfs.ext4`, and adds a UUID-based mount entry without changing unrelated fstab
entries. Reformatting the selected drive retires only its own entry and the
configured image entries, after backing them up. It mounts the filesystem and gives the signed-in administrator ownership
of its new root directory. No formatter force flags or filesystem repair commands
are used. `fdisk` and `e2fsprogs` are now explicit installer dependencies.

**Drive ready** appears only after verifying the filesystem and mount. This page
has no monitoring controls. Choose the drive separately in Setup when ready to
monitor it. Preparing a different drive does not select it; reformatting the
selected drive updates its identity and leaves monitoring stopped. Existing
settings are backed up under `/var/lib/usb-storage-watch/prepare-backups/`.
SMTP settings and timings are retained. Old disk-specific USB, Docker, dependent
storage and service settings are archived rather than applied to the new disk.
Companion actions remain bound to explicitly selected drive identities.

After explicit destructive confirmation, monitoring stops and the same guards
are rechecked in a bounded worker. The dashboard stays responsive and shows
**FORMATTING IN PROGRESS — DO NOT DISCONNECT THE DRIVE!** with actual preparing,
formatting, mounting and verifying stages. Conflicting controls are disabled.
There are no fabricated percentages or automatic retries.

Preparation requires administrator authentication and CSRF protection. Confirmation
is session-bound, expires after five minutes, and can be used once. The backend
rechecks the stable USB identity, serial, capacity, attachment sequence and partition
layout before writing. Mounted storage in any visible process namespace, open
device handles, swap, loop backing storage, and RAID/LVM holders are refused.
System disks and non-USB devices cannot be selected. An already selected drive can be reformatted after stopping monitoring and
unmounting it. Unrelated permanent mounts still require administrator review.

Partitioning holds an exclusive kernel device claim. Formatting uses mke2fs's
own exclusive open and normal safety checks; a whole-disk flock excludes udev
probing during the operation. There are no automatic retries. An interrupted
operation leaves a status record and requires review. Recovery never imports
the preparation module or calls formatting tools.

Validation uses an isolated QEMU guest with two disposable USB disk images and
real Linux utilities. It checks formatting, mount/remount, non-root access,
multiple dependent filesystems and the asynchronous formatting worker. System
mounts, open device handles, other mount namespaces, device-mapper holders, swap,
loop backing files and changed partition layouts are refused. The unrelated
image's SHA256 remains unchanged. The guest stubs systemctl; full service/reboot
acceptance remains a physical testing requirement. See DEV4-TEST-NOTES.md.

Before hardware acceptance: use an explicitly authorized disposable USB drive to
check desktop automount behavior, unplug/reconnect and reboot mounting, large and
4K-sector disks, and actual LVM/RAID/Docker deployments. Test installation on each
target distribution before claiming support. No physical drive was formatted;
the attached SanDisk and production Zorin were not test targets.
