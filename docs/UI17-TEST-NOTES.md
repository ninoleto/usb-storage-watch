> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI17 — Image operations and feedback at the action

Version: `2.0.0~ui17`. Test release. This keeps UI16's container-first Docker
restart choices and corrects image-operation failures reported during testing.

## Image operations

Manual image mounting uses the same configuration-lock owner as the enclosing
administration transaction. The app no longer mistakes its own settings lock
for another save. An explicit Mount image command is independent of the drive's
automatic-recovery switch; the existing device identity and filesystem checks
still apply.

Successful image creation closes its confirmation and shows the result with
the configured images. If creation changes the filesystem but later setup
fails, the result explains what was created or registered and what still needs
attention. It never silently formats the retained file again.

An image that another process is using can still refuse an unmount. The UI
shows that reason at the action so users can close the application or stop the
container using the image before trying again. It does not kill processes or
force an unmount.

## Feedback

Actions show progress and their final result beneath the relevant control.
Confirmation dialogs keep errors inside the dialog. The Messages history
remains available, but opening it is not required to discover an action error.

Pending actions prevent duplicate submissions. Interrupted or unanswered
requests are reported as unconfirmed; they are not automatically sent again.
Readback can update displayed state without repeating a storage command.

Image removal is placed separately on the right, matching physical-drive
cards. It still removes only the registration and keeps the image file and
its contents.

## Docker explanations

When detection finds that a container uses an image, the advisory names the
disk and image and explains the order: recover the disk, mount the image,
then restart the container. Without the image, a restarted application may
still be unable to access its files or accept uploads.

Detection remains advice. The user's disk and image selections control
automatic restarts, and mounting an optional image unsuccessfully does not
block a selected restart. Docker settings remain editable while monitoring
is on or off. This update does not add manual Docker Start/Stop controls.

## Verification and installation

See the release's TEST-RESULTS.txt for executed checks and limitations. Tests
use synthetic devices and Docker responses plus private installation roots;
the release builder has not installed or operated hardware on the user's
Ubuntu or Zorin server.

Existing configuration is retained by the package upgrade. The release ZIP's
INSTALL-FIRST.txt contains the installation command and version check.
