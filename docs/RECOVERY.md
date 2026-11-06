# Recovery, notification and persistence behavior

The service checks mount/device metadata every 15 seconds by default. This is
how it detects a failure; stopping cannot happen before that observation.
Selected containers begin stopping on the first bad observation, without waiting
for the disk recovery timer. Existing installations retain their saved interval
and recovery delay. A brief failure that stops a container still completes the
storage verification and start stages when the disk returns.

1. Save the incident, known healthy storage identity and selected-container state
   on the internal root filesystem. Request a graceful stop of each selected
   container and verify that Docker reports it stopped. Other containers remain
   untouched. A lost acknowledgement is checked by reading state; the same
   uncertain stop command is not blindly repeated.
2. After the configured recovery delay, verify the selected containers are still
   stopped and hold the app's shared container-control locks. Capture the exact
   current configured mount tree. A detached ext4 shutdown mount is eligible for
   ordinary unmount without an older healthy observation. Configured child image
   mounts must match their loop backing file/device, UUID and current mount ID.
   Unmount those children first, then the failed main mount. This can happen while
   the drive is still absent. No force/lazy unmount or filesystem repair is used.
3. Identify the returned filesystem by UUID and hardware identity. A new USB
   port or device name does not change the configured mount location. An absent
   drive does not use up the normal mount attempt; completed cleanup is recorded
   separately. A separately enabled and qualified USB reconnect can run once.
   Waiting for return continues without another reset. Current container state
   is rechecked before storage-changing actions; an old stop receipt alone is
   insufficient. Unknown/live foreign mounts and uncertain unfinished commands
   remain protected.
4. Mount the verified returned disk through its existing fstab entry. Verify
   the filesystem identity, read/write state and access. Normal journal replay
   is allowed when appropriate; automatic fsck/repair and forced rw remount are
   not performed. If automatic disk mounting is disabled, selected containers
   remain stopped while the service waits for the disk to be mounted.
5. Mount images with **Mount on recovery** enabled and any images explicitly
   selected for a container. Before starting that container, verify every disk
   and image explicitly selected for it. An unrelated global image failure is
   reported separately and does not block that container. Detected Docker bind
   folders provide advice, never automatic configuration or extra prerequisites.
6. Start the selected containers using their exact Docker identities. Verify
   running state and health checks when configured. A selected container already
   stopped before the outage is also eligible to start. Shared-container locks
   and saved action receipts coordinate multiple watched drives. Containers stay
   stopped while another selected drive/image is unavailable.
7. Queue the final outcome email after storage and container stages complete,
   when email notifications are enabled. The outcome distinguishes successful
   recovery, partial recovery and failures. Notification delivery uses the
   existing SMTP configuration and persistent queue.

If the drive fails again while containers are starting, record the interrupted
outcome and begin a new stop/recovery sequence. A genuinely new attachment can
re-arm a settled, unsuccessful no-write incident. Uncertain storage writes are
never replayed merely because monitoring restarts or the USB port changes.
UI22 resumes eligible settled older failures and the UI21 legacy wait through
the automatic stop/unmount/recover/start sequence. It uses current mount evidence
for a verified disconnected shutdown mount; it does not manufacture a historical
healthy observation or reset an already consumed USB reconnect budget.

Each cleanup and Docker action records its intent before I/O. A later run checks
actual state and preserves the old evidence. Repeated observations do not grant
repeated mutations. A stop that has not yet been verified is checked again at
the monitoring interval; disk recovery waits. Errors include the responsible
stage rather than reporting old successful operations as current health.

Manual Docker Start/Stop/Restart remains independent of automatic settings and
monitoring. Saving a container's drive/image choices does not control it now.
Automatic failure detection requires monitoring of the selected drive. The
container settings remain editable while monitoring is off.

## Crash and overlap protections

A singleton lock and separate operation locks prevent overlapping workers.
Atomic, fsynced state and receipts are stored on the internal root disk. Running
attempts without a complete receipt are consumed after restart; uncertain mounts
are blocked. Application intents are never replayed: restart resumes verification
only. Configuration fingerprints prevent a worker from applying a newly selected
disk/configuration to an old request. Do not change configuration during an active
incident. State from another target UUID/mountpoint is rejected.

The USB ledger carries the qualified profile needed to **enable only** an owned
pending port even if the main configuration is changed/removed. Cleanup must
revalidate the controller and physical port before writing. Service start/stop,
a separate guardian and bounded enable retries preserve the obligation. A failed
re-enable remains recorded and blocks new recovery actions. No software can
promise electrical re-enable after hardware failure, power loss, a kernel hang or
changed/missing topology. Manual intervention can still be necessary. Linux has
no atomic “disable only if absent” operation: guards are repeated immediately
before writing, but an irreducible hotplug race remains; keep USB recovery off
unless this tradeoff is acceptable on independently qualified hardware.

## Boundaries

The monitor never runs fsck/e2fsck, force-mounts, requests rw remount, automatically
unmounts unknown storage, resets a controller/shared hub, reboots, restarts Docker itself or alters
unselected containers. Recorded ext4 errors, unreplayable journals, ambiguous/stacked
mounts and wrong identities stop relevant operations. There is no automatic
repair. All subprocesses, SMTP and Docker requests are bounded. A kernel process
in uninterruptible I/O can outlive a signal; retained locks and conservative
state prevent repeated actions while monitoring continues where possible.

## Email delivery

An event is saved to the persistent FIFO before sending. Retries use a stable
Message-ID and recorded retry time; SMTP delivery has a 20-second total deadline.
Recipient credentials are never included in logs or outcomes. Outcome bodies
include mount/USB/application diagnostics, host identity and filesystem identity;
they are private operational information. An ambiguous SMTP acknowledgement can
cause duplicate inbox delivery despite one logical outcome event. No software
using ordinary SMTP can promise exactly-once inbox delivery.

## Filesystem checks

The journal and state-bit interpretation follows the [Linux ext4 superblock
documentation](https://docs.kernel.org/filesystems/ext4/super.html). Linux
[exclusive block-device opens](https://man7.org/linux/man-pages/man2/open.2.html)
reject an in-use device even when its filesystem is absent from the host mount
namespace. The kernel remains responsible for journal validation and replay;
a successful mount is followed by independent identity and error checks.

UI23 removes the cross-namespace availability prerequisite only before ordinary
unmount of the freshly verified failed configured tree. Exact local mount and
container-stop verification remain; returned-device mounting and loop detachment
retain namespace checks. A settled UI22 namespace refusal with no storage action
can resume automatically after upgrade and fresh verification.

UI24 isolates completed failed-mount cleanup history by incident, boot and
configured storage identity. A validated settled older receipt is archived;
unknown outcomes remain blocking. A new outage may legitimately reuse the old
mount number and receives its own normal-unmount retry accounting.
