> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI22 recovery and Zorin reference comparison

The supplied installed Zorin reference identifies itself as Example drive Watch 3.2.1.
Its application helper supports start/restart, not stop. Failure detection only
inspects containers. Storage recovery mounts and verifies the main filesystem,
restores the Codex image, then handles application restarts before notification.
Its application directories are directly on the main filesystem. The code has
no unmount step and refuses an already occupied main mount.

The Ubuntu failure being corrected is an old disconnected shutdown mount left
at the configured path. The returned drive has a new device number. UI21 could
stop containers but require a historical healthy mount identity before releasing
the old mount, leaving the user to unmount it. That manual prerequisite is removed
for a verified disconnected shutdown mount owned by the configured recovery tree.

## Automatic sequence

1. Stop the selected Docker containers and verify the result.
2. Verify their current stopped state while holding the app's container-control
   locks, then normally unmount configured failed child images and the main mount.
3. Recover and mount the physical drive, using its configured identity.
4. Mount the selected virtual images.
5. Start selected containers and verify their state and required storage.
6. Queue the final result email when notifications are enabled. A failed stage
   must not be presented as a successful recovery.

Cleanup can run while the disk is absent, before reconnection and mounting.
The old healthy-mount record is supporting evidence, not a prerequisite for this
automatic normal-unmount path. Current mount IDs and the configured target/image
relationships are checked. An unrelated live filesystem, unknown child mount,
changed container or uncertain unfinished operation is not silently acted upon.

The supplied Zorin scripts were read as reference only. They are not included
in the release, and their production paths, device identities and application
configuration are not copied into the distributable.

## Verification boundary

Automated tests exercise real application state machines with simulated kernel,
USB and Docker boundaries. This environment cannot perform the user's physical
USB failure, a real kernel mount/unmount, or production Docker/SMTP operations.
A passing test verifies the stated control flow, not recovery on every device.
