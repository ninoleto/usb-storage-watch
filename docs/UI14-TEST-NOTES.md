> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI14 — remove drives from Storage Watch

Use **Remove from Storage Watch** on a drive's Overview card, or the
**Remove this drive** section at the bottom of Manage Drive.

1. Choose the drive you no longer want managed.
2. Check its name, filesystem UUID and mount location in the confirmation.
3. Select **Remove from Storage Watch**. The local progress message remains
   visible while the host stops that drive's monitor and verifies removal.

Disconnected drives can be removed. You do not need to reconnect an old USB
stick, unmount a connected drive or stop monitoring manually first.

## What removal does

- Stops and disables the selected drive's monitoring at startup, including its
  automatic recovery and alert delivery.
- Removes its card, count and selections from the dashboard. Its virtual-image
  registrations and application recovery choices are no longer active.
- Invalidates its drive-scoped Companion/standby access. Dashboard login,
  management token, shared network/SMTP settings and other drives are retained.
- Preserves drive contents, virtual image files, current mounts and running
  applications. Existing Linux mount entries are retained; removal does not
  prevent Linux or another application from mounting the drive independently.

Removal does not erase or format storage and does not restart containers.
If you later want Storage Watch to manage the drive again, connect it and use
**Add USB drive**. It receives a new profile with fresh settings and monitoring
off. Configure recovery, virtual images and application mappings again as needed.
Existing image files can be registered through Add existing.

Connected but unregistered drives appear only in the Add USB drive picker,
not as configured overview cards. Removing the final drive leaves a clear
**No drives configured** state and keeps the dashboard available.

## Failure and concurrency behavior

Confirmation is bound to the reviewed drive UUID and configuration revision,
scoped to the signed-in session and expires after five minutes. A changed
configuration requires a new review. Cancel sends no removal request.

The host verifies that the selected service is stopped, its main process is
gone and startup monitoring is disabled. Removal also takes the monitor,
recovery, preparation and USB worker locks, and refuses an unresolved USB-enable
obligation or pending mount-location transaction. Formatting in progress must
finish first. A refusal leaves the drive registered; if monitoring was already
stopped, it remains stopped and the message explains that.

The configuration is atomically renamed to private `removed-drive.json` beside
its old `config.json`. State, history, cleanup ledgers and file permissions are
preserved. The legacy profile's shared directory is never deleted. Retired
profile identifiers are not reused by Add, and cached/stale requests cannot
recreate the retired configuration or restart its monitor.

Complete drive lists are authoritative. A failed or incomplete list retains
existing cards; a successful list removes retired cards. Lists requested before
a removal cannot restore an old card afterward. After a lost removal response,
the browser reads the current list to verify the result without resending the
write. A refusal is displayed inside the dialog with a fresh-review option.

## Verification

`TEST-RESULTS.txt` in the release records final results. New tests exercise the
actual Flask/broker HTTP routes and real browser touch interactions at phone,
tablet and desktop widths. Disk discovery, disk contents and systemd boundaries
are isolated fixtures; no user drive, mount, container or host service is changed
by these checks. UI13's network and touch-control changes remain included.
