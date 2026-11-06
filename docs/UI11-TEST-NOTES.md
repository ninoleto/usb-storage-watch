> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI11 — TEST ONLY

Version: `2.0.0~ui11`. This build includes UI10 FIX1 and exposes the existing
guarded Docker recovery engine through the dashboard. It also completes the five
UI changes recorded during the last acceptance session.

## Interface changes

- Timing and HDD standby Save buttons are disabled when their own form has no
  unsaved changes. Confirmed saves reset that form's baseline; failed saves keep
  its edits. Changing drives or saving the other form preserves pending edits.
  Edits made while a save is in progress remain unsaved and visible afterward.
- Messages has a Clear messages button. It clears this browser session's
  notifications, not the drive's persistent Event History.
- Change mount location is disabled while the drive is mounted, with an
  explanation beside the controls. The server retains its own mounted-drive
  and active-worker checks.
- Refresh events shows Refreshing, Updated, or an error beside the clicked
  button on both Recent events and Event History.
- Start monitoring has a thicker light-green border on Overview, Manage Drive,
  and Docker & Applications.

## Docker controls

Docker & Applications now discovers containers and eligible writable bind
folders for the selected drive. Select containers, choose their storage folder,
and explicitly enable recovery. Stop only that drive's monitoring before saving
configuration, then start it again afterward. This does not stop containers.

The server rechecks container identity, storage ownership, the configuration
revision, mounted filesystems, image dependencies, and writable private bind
options before saving. A directory underneath an absent or disabled image is
not accepted as that image's storage. A container can belong to only one drive's
recovery configuration. Saved selections are retained when Docker discovery
fails; disabling recovery with an unchanged selection works while Docker is
unavailable.

Current state for selected containers refreshes every 15 seconds while this
page is open. It is separate from the last incident's recovery result. The poll
only reads metadata; it does not start, stop, restart, or execute inside a
container. Failed reads show unknown state rather than retaining a green result.

Check storage access explicitly runs the existing bounded preflight in a worker
with a 30-second limit. It verifies storage and performs a read-only access
check inside running containers. A stopped container stays stopped and is
reported as not access-tested. This check does not upload files, write test
files, or restart containers. An application-level upload/download remains a
separate acceptance test.

## Ubuntu acceptance with the existing Erugo test

The test container is already running and its upload/download check passed.
Keep its Compose restart policy set to `"no"` for this test.

1. Upgrade to UI11 and hard-refresh the dashboard. Confirm UI11 in the sidebar.
2. Confirm the example drive drive and `sample-volume` image are mounted and their automatic
   recovery preferences are enabled.
3. Open Docker & Applications and select example drive. Stop monitoring with the
   button on this page. The container should keep running.
4. Refresh containers and select `sample-app`. Its host folder should be
   `/mnt/storage/usb-storage-watch-volumes/sample-volume/erugo-test-storage` and its
   container folder `/var/www/html/storage`. Enable Recover selected containers
   after a drive outage, then Save Docker recovery.
5. Run Check storage access. Continue only after this container reports Storage
   access verified. If refused, retain the message for diagnosis.
6. Start monitoring for example drive. Leave Erugo running and the drive connected
   for at least two monitoring checks (30 seconds with a 15-second interval) so
   monitoring can record an application baseline.
7. With no upload in progress, perform one controlled disconnect/reconnect of
   this test drive. Confirm the main filesystem and `sample-volume` recover before an
   application result is reported. Wait for the final result; do not repeatedly
   issue manual reconnects during recovery.
8. Check Docker & Applications and Event History, then download the previously
   uploaded test file and compare it with the original. Upload/download a new
   small disposable file. Other drives' settings and monitors must be unchanged.
9. Separately stop Erugo intentionally, leave it stopped for at least two
   monitoring checks, and repeat an idle-drive outage. The container
   should remain stopped. Restart it explicitly afterward when needed.

Only use disposable test data for outage acceptance. This workflow does not
reformat drives or alter the existing Compose project.

## Boundaries and result interpretation

Docker recovery is recovery after a storage incident. It is not a general
watchdog for unrelated container failures. Existing runtime rules still apply:
only the incident-time selected container identity may receive a bounded
recovery action, intentionally stopped containers stay stopped, and final
verification checks the recovered bind and inside-container access.

A retained container mount namespace can prevent safe filesystem recovery. The
engine refuses that case and does not stop containers merely to release storage.
An image whose recovery preference is disabled cannot support enabled Docker
recovery. Replacing/recreating a container may require refreshing and saving its
selection again. Containers require `timeout`, `sh`, and `find` for the access
check. There is no container installation, deletion, or unrelated lifecycle
control in this page.

Automated results use synthetic devices and Docker responses. Live Docker outage
recovery on the Ubuntu test host remains an acceptance step, not a claimed pass.
See the release's TEST-RESULTS.txt for test counts and unresolved test limits.
Software USB reconnect still requires verified port isolation and does not
establish electrical power removal. This is not a production deployment.
