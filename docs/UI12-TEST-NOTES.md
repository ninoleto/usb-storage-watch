> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI12 — TEST ONLY

Version: `2.0.0~ui12`. Includes the UI11 controls and UI10 FIX1 behavior.
This is a test-machine build, not a production release.

## Network settings consistent with RF Button Manager

Advanced Settings now uses the same interaction model: a local-network switch,
separate saved Network URL and Localhost URL cards, HTTP/HTTPS selection cards,
a grouped server-address/ports section, and certificate setup guidance.
The address picker is touch friendly; both ports have − / value / + / Reset.
USB Watch keeps its own defaults: HTTP/localhost 8765 and LAN HTTPS 8766.
Existing saved listener settings are retained on upgrade.

The server address is selected from private IPv4 addresses already assigned to
the computer, including VPN and clearly labelled virtual interfaces. This does
not assign a new OS IP address or change the router, firewall or VPN.

1. Edit the settings. The saved URL cards keep showing current connections.
2. Select Apply network settings. The app checks temporary proposed listeners
   while leaving the saved listeners available.
3. Open the generated link in a new tab. Sign in with the existing management
   token if prompted, then open Advanced Settings.
4. Confirm connection **from that proposed URL** within three minutes.
   The old tab cannot confirm a different endpoint.
5. The server commits and verifies the selected listeners. The new tab may
   briefly reconnect while temporary listeners are replaced by saved services.

Cancel, expiry, or a broker restart before confirmation retains the old settings.
An interrupted commit restores the previous files/listeners at broker startup.
Failure to verify restoration is reported for local administrator review.
A monotonic deadline prevents a backward system-clock adjustment from extending
an in-progress confirmation window. Mutation responses are never automatically
replayed after a connection loss; the browser reads the durable operation status.

Disabling LAN access requires confirmation through the proposed localhost URL
in a browser **on the Linux server**. Localhost on a phone/remote PC refers to that
device. Keep the current tab open during testing. Changing the HTTP port changes
the localhost port too; the application-menu launcher follows confirmed changes.
A same-address/same-port change to a different protocol is refused while that
port serves the old connection; choose an unused port for the test.

For HTTPS, use Prepare HTTPS certificate, verify its fingerprint on the server,
and trust the downloaded public certificate on the client before applying.
A persistent private issuer permits subsequent IP changes without creating a
new trust root each time. Older UI11 certificates remain untouched until an
explicit change; the first UI12 HTTPS change may require trusting its new issuer.
Private keys and management tokens are never included in links or downloads.

## Required Docker storage

Each container's requirements are inferred from its bind folders. The UI shows
Required storage. A manual switch cannot bypass a real dependency.

| Container storage | Recovery waits for |
| --- | --- |
| Program on internal SSD, uploads bound to a folder on the USB drive | The USB filesystem |
| Container data bound to a folder inside a configured virtual image | USB filesystem and that image |
| Several bind folders on the drive, including an image | All the images those folders use |
| Separate backup image unused by the container | No dependency on that backup image |

Nested image prerequisites and recursive bind submounts are included. An absent
or disabled required image is not replaced by the ordinary directory beneath its
mountpoint. A bind of an ancestor directory containing the entire drive is
refused; use specific storage folders. Guarded recovery uses explicit bind
folders for storage on the watched drive.

If the main filesystem recovered but an unrelated image failed, independent
containers can still recover. The overall event remains a partial-storage result;
it does not falsely report the unavailable image as recovered.

A container known to have been running before the outage is restarted even if
its process is still running. This covers a file-upload service whose web UI
remains available while its external upload folder is unavailable. A container
known to have been stopped stays stopped. Container identity, saved bind
configuration, main filesystem identity, required images, namespace mount
identity, health and read-only inside-container access are checked. The existing
one-action-per-container-per-incident budget and no-retry-on-uncertain-response
rules remain in force. This is not a general Docker crash watchdog.

A backup image used by another program can recover independently. USB Watch does
not automatically rerun that program's failed backup job.

## Ubuntu acceptance sequence

Use disposable test files and retain the existing Erugo container's restart
policy of `no`. Do not alter a production service for this test.

1. Install UI12 and hard-refresh the dashboard. Verify the current URL still works.
2. Network: change a spare port, cancel once; repeat and let the countdown expire;
   repeat and confirm from the new link. Check saved URLs and the menu launcher.
   Test LAN disable/enable from the server browser. Then test HTTPS after trusting
   its certificate. Keep a working SSH/local terminal available for observation.
3. Docker & Applications: stop monitoring for the selected drive, refresh
   containers, select the test container and its folder, enable Docker recovery,
   save, and run Check storage access. Restart drive monitoring.
4. For the existing image-based Erugo test, ensure its required image has Mount
   on recovery enabled. Wait at least two monitoring intervals for the running
   baseline. Test an outage and reconnect; confirm the drive, required image,
   one container restart, and upload/download of a fresh disposable file.
5. Test the direct-folder case separately: configure a disposable container bind
   to an ordinary folder on the USB drive. Keep a separate unused backup image
   unmounted/disabled. That image must not block the container's access check or
   its recovery after the drive returns.
6. Stop the test container intentionally, let monitoring observe the stopped
   baseline, and repeat an outage. It must remain stopped.
7. Confirm messages remain nonblocking, saved timing/standby buttons disable,
   inline Refresh events feedback appears, and Ready has no spinner.

Automated validation uses isolated files, simulated service/Docker boundaries,
real certificate generation, and Chromium with synthetic API responses. Actual
network listener replacement on Ubuntu, certificate trust in client devices,
physical USB recovery and live Docker outage behavior still need acceptance.
Existing kernel safety checks can refuse recovery when a container retains an
unsafe old mount namespace; this build does not stop a container merely to
release that mount or bypass the refusal. Filesystem access verification alone
does not prove file integrity or complete application health.
