> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI21: legacy failed-incident resume

UI20 could remain attached to a completed pre-UI20 failure record. Such a record
has no container-stop stage and may have no historical mount identity. The
current drive can therefore be detected while an unavailable older mount still
occupies its configured folder. A saved old "mount disabled" result is not proof
that the current Automatic recovery setting is disabled.

UI21 preserves the old incident in history and creates a current recovery sequence
for eligible settled legacy failures. Selected containers stop first. If the old
mount cannot be matched to a healthy identity recorded earlier, recovery remains
waiting without consuming the mount attempt. After that old mount is released
normally, the same incident continues: mount disk, mount selected images, start
containers, then queue the final email if enabled.

A previously uncertain storage operation is not replayed by this migration.
No historical identity is fabricated, no unrelated filesystem is detached, and
there is no forced/lazy unmount or filesystem repair. This release retains the
UI20 Docker selection model, manual controls, button colours, 24-hour timestamps,
network interface and single local progress/result line.

## One-time release for an old unproven shutdown mount

An upgrade cannot retrospectively record the identity of a mount that already
failed. If the live mount is a disconnected ext4 shutdown mount, with no child
mounts, stop its container and release the old mount with ordinary umount. Use the
specific drive/container instructions supplied with the release. If ordinary
unmount reports that it is busy, stop there; do not use force or lazy flags.

With monitoring and automatic recovery enabled, UI21 can then continue the saved
recovery sequence. A healthy observation records the identity needed for future
automatic detached-mount cleanup during the same boot.

## Verification boundary

Tests use simulated storage and Docker boundaries. No physical USB drive,
real mount/unmount, Docker daemon or SMTP delivery was exercised in this workspace.
The supplied diagnostics identify the legacy-state dead end; they do not prove
that no other host-specific issue will occur after it is cleared.
