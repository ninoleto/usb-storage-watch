> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI8 — TEST ONLY: manual sleep preserves monitoring

This build continues UI7. It corrects the manual Sleep HDD now path, which
previously stopped monitoring before running the standby worker. Some failures
could leave the monitor stopped. Sleep now issues no service stop/start or
enable/disable command. A monitor that was already off remains off.

The older three-second quiet check ran before flushing pending filesystem
writes. For an explicit sleep request, UI8 flushes pending writes first and
allows up to 15 seconds for three consecutive quiet seconds. A transient write
can settle within the same request. Continued activity returns a clear refusal
without sending standby or changing monitoring. This is a candidate correction
for the reported refusal; the screenshot alone does not identify its I/O source.

## Expected behavior

- Sleep now skips the configured automatic idle timer.
- A successful request leaves the filesystem mounted and monitoring on when
  it was on. The drive is labelled Spun down only after bridge confirmation.
- Active applications, continuing I/O, another storage operation, a changed
  device, an unhealthy mount or an unsupported bridge can still prevent sleep.
  The reason stays visible; monitoring is unaffected by the request.
- Filesystem access can wake the HDD. Routine monitoring and standby status
  observation continue using cached/kernel metadata rather than power queries.
- An already stopped monitor must be started separately with Start monitoring.
  This build does not override the user's existing monitoring preference.
- The automatic idle standby policy is unchanged.

## Implementation and verification scope

The broker routes sleep separately from mount/unmount/reconnect. Success,
refusal, worker timeout, failed worker creation and unreadable worker results
leave the service untouched. Readback failures do not turn a confirmed standby
result into a failed operation. Failed receipt writes return a separate warning.

The manual worker takes only the per-drive recovery lock, shared with other
storage-changing operations. It can run while monitor.lock is held. It refuses
pending USB cleanup and never tries a reconnect as part of sleep. Inherited
lock descriptors are restored even when an operation refuses or fails.

Existing active-user, raw-device, Docker, swap, mount and stable-identity checks
remain enforced. The command stays normal ATA standby (`hdparm -y`), followed
by verification. ATA deep sleep (`-Y`), unmounting, killing applications and USB
power cycling are not used by this operation.

Automated tests use synthetic disks, services and API responses. Real advisory
locks verify that live monitoring can coexist with sleep while storage actions
remain exclusive. Browser tests exercise success, busy refusal, unsupported
bridges, timeout and monitoring on/off at four viewport widths. See the bundle's
TEST-RESULTS.txt for the completed checks and environment limitations.

## Install and accept on the Ubuntu Studio test machine

Keep the UI7 archive available. Install the UI8 Debian package using the bundle's
INSTALL-FIRST.txt. Existing profiles, image files and settings are retained.
Refresh the browser with Ctrl+Shift+R and confirm the sidebar says UI8.

1. Check the selected drive's monitoring status. If UI7 left it off, click
   Start monitoring once before testing sleep.
2. Close applications using the test HDD, then request Sleep HDD now.
3. Verify monitoring stays on throughout the request and after its result.
   Success should report standby confirmed and show HDD: Spun down.
4. If the request refuses or the bridge cannot confirm standby, preserve the
   exact visible result for diagnosis. Monitoring should still be on.
5. A later deliberate file access can wake the drive. Continue normal monitoring.

No physical drive or host service was operated while developing this build.
Physical spindle stop and wake-up remain unverified here. Production Zorin has
not been accessed or changed; this package is for the Ubuntu Studio test machine.
