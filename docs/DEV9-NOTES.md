> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# DEV9 — TEST ONLY

DEV9 corrects the multi-drive interface and routing on the existing DEV8 engine.
Overview always lists all drives. Add USB drive opens a real selection workflow.
Manage Drive has an explicit immutable drive URL, independent monitoring and
automatic recovery controls, manual operations, image/application settings,
timings, standby and that drive's history. Setup is removed from navigation.
Global Advanced, SMTP, history and physical preparation no longer depend on a
hidden browser selection. Notification preferences explicitly identify each drive.

Preparation resolves the selected by-id disk to its existing owner using UUID,
live physical identity and saved hardware checks. The reviewed confirmation binds
the operation to that owner and physical layout; the worker revalidates before
erasure. Only that monitor is stopped. Duplicate UUIDs, ambiguous ownership, busy
storage, protected system storage and changed hardware are refused. New disks do
not require removing another monitored drive. No recovery path formats storage.

Existing DEV7 root configuration/state and DEV8 per-drive directories remain in
place. Their immutable identifiers, systemd instances, locks, histories, pending
notifications, management/Companion tokens, SMTP credentials, certificates and
image locations are retained. No data conversion, image recreation or automatic
mount relocation is performed. Browser bookmarks to Setup return to Overview;
drive API calls must identify their target explicitly. Companion routes retain
their existing version and token restrictions.

Event History reads existing databases without moving records. It displays up to
200 recent incidents, bounded by response size, with an independent drive filter.
Mounted elsewhere is distinguished from mounted at the configured location.
Media icons use passive hardware evidence; ambiguous USB bridges remain unknown.

The real simultaneous-remount test reproduced a procfs EINVAL when another worker
exited during namespace inspection. Namespace checks now make at most three
metadata reads, skipping only processes confirmed exited (including unreaped
workers, verified with a process pidfd). Persistent live-process errors, permission
denials and retained mounts still block recovery. Recovery ordering, attempt
budgets and USB operations are unchanged. This matches the process-exit behavior
in [Linux mountinfo handling](https://github.com/torvalds/linux/blob/v6.17/fs/proc_namespace.c#L219-L269).

Automated verification and remaining hardware limitations are recorded in the
transfer bundle's TEST-RESULTS.txt. Physical Ubuntu Studio acceptance is still
required. No physical USB port resets, physical disk formatting, live Docker or
SMTP tests, production access, publication or separate Companion-module changes
are part of this development build.
