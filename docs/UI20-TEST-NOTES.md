> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI20 — Disk failure and container recovery

Version: `2.0.0~ui20`. Test release.

## What changed

For each container, the selected drive switches now mean:

1. Detect failure and stop the selected container.
2. Wait for the drive to return and recover its mounted filesystem.
3. Mount the virtual images explicitly selected for the container.
4. Start the container after its selected disks/images are verified mounted.
5. Queue the outcome email, when notifications are enabled.

Stopping begins at the first failed observation, without the recovery delay.
The default observation interval is 15 seconds; existing saved timings remain.
The container stop uses its configured graceful shutdown timeout. An unavailable
or uncertain Docker response is checked again without blindly repeating a command.

Disk absence no longer consumes the normal mount attempt. Retained managed image
mounts are verified and normally unmounted before their retained parent shutdown
mount. Returned disks are identified independently of USB port and device name.
A new attachment can resume a settled failure with no uncertain storage writes.
The reported UI19 conflict is eligible when its healthy mount proof still matches.
Busy or foreign mounts remain refused; there is no force/lazy unmount or repair.

Only explicitly selected images are prerequisites for a container. With **None**,
it waits for the disk only. Inferred Docker storage remains advice. Unrelated
Mount-on-recovery images can fail without preventing that container from starting.
Multiple selected drives are checked before a shared container starts. If disk
failure recurs during startup, another stop/recovery sequence is created.

Manual Start/Stop/Restart and settings remain available independently of monitoring.
The app does not install/recreate containers or edit Compose files. A selected
container that was already stopped before an outage can start after recovery.
Turn off the drive switch to exclude it from automatic control.

## Interface and diagnostics

- Dark green Start monitoring button, with its visible border retained.
- Dark blue container header only; the rest of the card retains its layout.
- 24-hour time everywhere, including `00:00` at midnight.
- One current result beneath a button group, without duplicate Last operation.
- Live stop/wait/mount/start progress replaces historical manual feedback during recovery.
- Docker daemon refusals explain recognized missing-folder, unavailable-IP,
  occupied-port and permission failures; unknown responses remain identified as uncertain.
- USB descriptor inspection recognizes real kernel inotify handles and can prove
  unrelated descriptors through stable mount/inode metadata. Unverifiable handles
  still refuse reconnect, now identifying the process and descriptor.

## Verification and limits

The release checks cover actual monitor/storage/Docker coordination with synthetic
kernel and Docker boundaries, including port changes, retained images, long absence,
UI19 incident migration, multiple selected drives, repeated outages and email order.
HTTP framing is exercised against a real local test server; no real Docker daemon
is controlled. Chromium checks run against the installer payload at mobile/tablet
and desktop widths. Detailed executed results are in the release TEST-RESULTS.txt.

This environment cannot perform real kernel mounts or operate the user's physical
USB drives. A passing simulation is not proof of physical recovery. The previously
reported manual Erugo start failure cannot be assigned a definite host cause from
its screenshot alone; UI20 preserves and explains recognized daemon refusal causes.
No Ubuntu-host installation or SMTP message was performed while building.
