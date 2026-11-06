> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# 2.0 DEV3 — test-only development notes

Checkpoint: `checkpoint/pre-dev3-gui-app-storage-20261030` at tested DEV2
`ba22274`. Development stays on `dev/simple-2.0`; nothing is published.

Overview now combines the selected drive, model/capacity, connection, actual
mount location, monitoring, recovery state and manual controls. Technical details
expand below. Hub connections show a prominent warning and disabled reconnect;
ordinary monitoring/mounting remain available. Flash devices have no HDD controls.
Setup, Email, Prepare drive and Advanced each own their settings; the old five-step
wizard is removed from normal navigation. The existing visual design and login
security remain. SMTP Save/Test are separate, blank passwords are preserved and
SMTP acceptance is not described as confirmed inbox delivery.

The bounded primary recovery sequence, USB identity/namespace/isolation guards,
notification queue, Docker stopped-container/health checks, standby function and
Bitfocus Companion endpoint are reused. The single-image guards now operate over
an ordered list of required ext4 images. Legacy single-image configuration still
loads without modifying its saved values. Failed required storage prevents app
restarts; individual image/container outcomes remain visible in partial recovery.

Advanced provides guided new/existing image setup, automatic UUID detection,
configuration editing/removal without deleting data, automatic Docker discovery,
multiple selections and service settings. Image creation formats only a newly
created, exclusively opened regular file. Prepare drive can explicitly reformat
the selected unused physical device, with pre-erasure backups and fresh identity;
only its exact primary/dependent entries are retired. Installation and recovery
never format anything. Authenticated HTTPS can use a discovered private LAN IP
and a generated local trust certificate; manual certificate settings are collapsed.

The DEV2 generic reconnect error discarded the underlying exception. Linux's
`disable` readback reports the hub POWER bit; it is not proof of logical attachment.
A completed disable write can disconnect the drive even when power readback stays
on. DEV3 retains precise errors, always re-enables, and verifies the returning
physical drive/UUID before reporting success. Failed enable and changed identity
remain failures. Cancellation does not resume recovery. This defect is reproduced
with synthetic sysfs; the exact ADATA incident cause remains unconfirmed without
its saved `io_error`/kernel evidence. Electrical power removal is never claimed.
Kernel reference: https://github.com/torvalds/linux/blob/master/drivers/usb/core/port.c

Validation: 475 automated tests, including 26 Chromium workflows, passed on the
Ubuntu 24.04.4 development VM. Coverage includes multiple images/containers,
required-parent and partial failures, legacy configuration, moved ports, hubs,
reconnect verification, standby safeguards, SMTP credentials, image consent and
LAN certificate generation/validation. Browser workflows use isolated OS boundaries.
Two real disposable ext4 image files were imported without changing their bytes.
An isolated QEMU guest used only two regular backing files, with no physical USB
passthrough or network. Real Linux utilities exercised image creation, two loop
mounts, primary-then-image recovery, partial failure, selected-drive reformat,
configuration/state backups, new UUID selection, and busy/namespace/swap/loop/
device-mapper refusals. The unrelated virtual disk's SHA-256 stayed unchanged.
The minimal guest stubs systemctl; it is not a full target-distribution install.
One rapid-remount run reached the existing three-second loop metadata deadline
and safely refused verification; the final run passed. No UUID check or deadline
was bypassed. Rapid remount timing still needs testing with the target udev/kernel.

Remaining acceptance: install/upgrade and reboot on Ubuntu Studio; direct-port
reconnect and port moves on the ADATA hardware; hub refusal; mechanical HDD/bridge
standby and Bitfocus Companion over trusted HTTPS; real Docker bind/health recovery;
SMTP submission and actual receipt; explicitly authorized physical preparation.
Image paths/mount folders must be inside the primary ext4 drive, without spaces.
The GUI imports/creates images directly on that drive; existing nested dependency
configurations are restored in order. Primary location changes with configured
images/container paths require reviewing those paths first. Unknown HDD power
state remains Unknown; idle counters alone cannot establish spun-down state.
LAN server certificates last one year; regenerating requires renewed client trust.
No physical USB disk was formatted or reset. Zorin and physical Ubuntu Studio
were not accessed. Packaging checks are recorded in the transfer bundle.
