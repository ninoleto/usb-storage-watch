> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI16 — Container-first Docker restart settings

Version: `2.0.0~ui16`. Test release. This replaces the Docker policy and layout
documented in UI11–UI15. Network settings, drive removal and other existing
interface improvements remain.

## Container cards

Every detected container appears in Docker & Applications, regardless of where
its files are stored. Its header shows its name, runtime status and an
expand/collapse arrow. The whole header is keyboard and touch accessible.
Collapsing hides its settings, keeps unsaved changes and remembers the choice.

Each container card lists the configured drives. Enable a drive switch to
restart this container after that drive recovers. Beneath an enabled drive,
choose no image or the registered virtual images to attempt to mount first.
The same container may be selected for multiple drives.

Each card has its own Save restart settings button and adjacent feedback.
Saved settings, dirty changes and errors are visible beside the action.
Monitoring on/off never prevents editing or saving Docker settings. Saving
choices neither starts monitoring nor immediately restarts a container.
An image stage already in progress finishes using its captured image choices.
Container deselection is checked again before sending a new restart request;
saving cannot cancel a request Docker has already accepted.

## Recovery behavior

1. Detect a drive outage and run its configured recovery attempt.
2. Require successful verification of the physical filesystem.
3. Attempt images with Mount on recovery enabled, and any additional images
   explicitly selected for the container on that drive.
4. Restart the selected container. Image mount failures are warnings; they do
   not block this restart. Detected Docker bind paths are advisory only.
5. Report drive recovery, image warnings, and each container's actual restart
   and runtime/health result separately.

A selected container can be restarted even when it was previously stopped.
Turn off all its drive switches if it should remain excluded. Actual Docker
errors or changed container identity are reported; no repeated request is
issued just because a response was lost. Drive recovery failure prevents the
Docker stage. Saving settings is independent of monitoring; automatic outage
detection still depends on the relevant drive's monitor running.

## Upgrade and existing data

Existing configured containers and drive registrations are preserved. Legacy
bind paths remain advisory metadata; they do not impose a restart prerequisite.
No virtual-image choice is silently inferred from an existing Docker bind.
Existing Mount-on-recovery image settings still apply independently.

The app does not install containers, edit Compose, move Docker files, change
volumes or restart the Docker daemon. Erugo does not need to be recreated.
Removing an image registration clears its explicit image choices while keeping
the container's drive restart selection. Removing a drive keeps files and
mounts, with the existing removal confirmation and worker cleanup checks.

Actual filesystem and USB isolation checks remain in place. A busy or unsafe
mount can still prevent drive recovery. Container runtime/health status is not
a file-integrity or end-to-end upload test.

## Verification

See the release's TEST-RESULTS.txt for exact automated checks. Tests use mocked
devices/Docker and private installation roots. This release is not installed
on the user's Ubuntu or Zorin host by the build process.
