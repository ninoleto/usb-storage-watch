> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# Physical reconnect investigation — 2026-10-28

Status: physical reconnect acceptance passed, including two consecutive complete
storage-plus-Docker recoveries after correcting the defects below. Publication
still requires owner approval. No production system was accessed or modified.

## Evidence collected before changes

The investigation preserved the complete service/kernel journals, original
configuration, persistent state and receipts, SQLite history backup, fstab,
mountinfo, block-device discovery and systemd state in a private VM evidence
directory. No state was cleared and no filesystem was manually mounted.

The kernel recorded a real USB disconnect at 01:25:56 and return at 01:26:00,
with the expected ext4 UUID available at 01:26:01. The filesystem was unmounted,
had the normal journal-recovery flag and zero recorded superblock errors.
An exclusive read-only block-device open succeeded: retained mounts were not
preventing recovery. The disk identity, model, capacity and USB topology matched
the disposable test drive; the operating-system disk remained separate.

The monitor ran from 01:23:37 to 01:23:48 and again from 01:25:51 to 01:28:47.
It was disabled when the investigation began. There was no recovery worker or
pending recovery wait for the reported reconnect. Its persistent state instead
held an already completed October 27 failure, with both attempts exhausted and
main mounting blocked for that incident. No new incident was recorded after the
physical return.

The preceding validation cleanup had incorrectly restored that obsolete failed
state over a saved, confirmed healthy state completed at 01:10:22. This was a
cleanup error. Starting the monitor briefly did not supply the two healthy
observations plus direct proof needed to re-arm the old incident before the
next unplug. The engine then treated the new physical attachment as part of the
old exhausted outage. Its normal same-outage retry suppression was working,
but it lacked a separate transition for a new attachment after exhaustion.

The dashboard's unavailable-disk observation was accurate. The history's
AUTO-RECOVERED entry described the earlier 01:10 validation incident. History
and current status lacked a sufficiently explicit distinction, and the broker
did not expose pending/running/exhausted recovery progress to the dashboard.
No evidence attributes this failure to VMware or an ext4 mount refusal.

## Changes

The engine records the kernel USB disk sequence together with the boot identity.
A changed sequence in the same boot, observed consistently for the configured
confirmation count after a completed incident, creates a separate incident with
its own bounded budget. Device names and major/minor numbers can be reused and
are not used as proof of a new attachment. The sequence is collected only for
USB metadata matching the configured ext4 UUID. Direct UUID/type, namespace,
exclusive-device, filesystem-state and post-mount checks still govern mounting.
See the [kernel diskseq ABI](https://docs.kernel.org/admin-guide/abi-stable.html#abi-sys-block-disk-diskseq).

Service restart, enabling monitoring, upgrading, rebooting and a transient UUID
symlink disappearance do not renew an exhausted budget. Legacy states without
an attachment identity acquire a baseline without retrying. Kernels without
diskseq retain the existing confirmed-healthy re-arming path. A device returned
by the worker's own qualified reset is consumed by the existing incident, so an
automatic reset cannot generate a new retry loop. Completed incidents are
archived before replacement, preserving their outcomes and notification queue.

The GUI adds a current-status panel to both Overview and History. It distinguishes
monitoring disabled, waiting for a fresh observation, confirming a new outage or
attachment, scheduled recovery, storage recovery, verification, application
recovery, exhausted failure and verified current health. Countdown and attempt
information come from persisted engine progress. A historical success never
overrides an unhealthy live observation; loss of the status connection removes
the previously displayed health claim. History rows are labeled recorded
incidents and remain separate from the current-status panel.

## Validation

Automated regressions cover changed-attachment re-arming, same-device and
restart duplicate suppression, absent-device late return, legacy/reboot
anchoring, worker-induced attachment consumption, per-connection exhaustion,
diskseq metadata checks, archived history and GUI state distinctions. Additional
Docker regressions cover completed older selections, unresolved historical
work, current-incident selection changes, archive write failure and unchanged
action budgets after restart. All 322 tests pass, with no skips in this VM;
all 13 isolated package lifecycle checks pass, including the suite from the
extracted portable source.

Chromium exercised live login, historical success alongside current failure,
live partial application recovery, eight recovery display states, responsive
layout and logout. Overview and History had zero axe violations and no
JavaScript errors. Installed status was observed during real waiting,
verification and successful recovery. No browser code performs recovery actions.

## Operator-performed physical cycles

The installed package was rebuilt, installed and compared byte-for-byte across
all 111 payload files before the operator was asked to unplug the drive.
Configuration, incident history, notification queue and the exhausted incident's
retry budget were independently checked unchanged. No old state was restored.

On October 28, the first physical disconnect at 02:01:33 and return at 02:01:47
(local UTC+01:00) created a distinct incident. The installed service mounted on
attempt 1 at 02:03:15; the kernel recorded journal recovery completion and an rw
mount. Direct UUID/type/rw checks and all three previously recorded file
checksums passed. Monitoring re-armed at 02:03:45, the GUI's current-status data
reported recovery success, and SMTP accepted the outcome at 02:03:47. Docker
was disabled for this first cycle.

The second physical disconnect at 02:08:45 and return at 02:08:57 again created
a distinct incident. The returned filesystem had `needs_recovery`; a selected
running container retained the old disconnected device in its namespace.
The host filesystem recovered automatically on attempt 1 at 02:10:25, with
normal kernel journal replay. The Docker stage failed before any container
action because its completed historical ledger listed a previous selection.
The reader incorrectly compared that old selection with current configuration
before checking which incident owned the ledger. The outcome email correctly
said applications required attention and SMTP accepted it at 02:10:57.

The correction validates the historical ledger's structure and action counters,
then distinguishes its incident from the current one. A valid completed older
ledger is archived intact before replacement, even if the selection changed.
Unresolved older work and a changed selection within the same incident still
block actions; archive failure also blocks actions. Reading status never writes
history. The GUI now explicitly labels storage recovery with incomplete
applications or dependent mounts as partial recovery. Failed-cycle evidence and
the old ledger remain intact; there is no manual Docker restart or budget reset.

The second cycle remains a storage pass and a Docker failure in the evidence.
It is not counted as an end-to-end pass.

## Corrected physical repeat results

Both repeats used the actual installed systemd service, the default 15-second
sampling/two-observation confirmation/60-second recovery delay, and the same
disposable ADATA drive. The operator unplugged and reconnected the USB device;
kernel disconnect/enumeration records independently corroborated each cycle.
No manual mount, Docker restart, reboot, driver detach or port-reset command was
used to obtain either result. Port resetting stayed disabled.

Times below are October 28, 2026, UTC+01:00.

| Cycle | Disconnect / reconnect | Automatic mount | Final outcome / SMTP accepted | Result |
| --- | --- | --- | --- | --- |
| 1 | 02:01:33 / 02:01:47 | 02:03:15, attempt 1 | 02:03:45 / 02:03:47 | Storage passed; Docker disabled |
| 2 | 02:08:45 / 02:08:57 | 02:10:25, attempt 1 | 02:10:55 / 02:10:57 | Storage passed; Docker ledger defect found |
| 3 | 02:20:35 / 02:20:45 | 02:22:04, attempt 1 | 02:22:35 / 02:22:37 | Complete storage and Docker pass |
| 4 | 02:26:50 / 02:26:57 | 02:28:23, attempt 1 | 02:28:54 / 02:28:56 | Consecutive complete storage and Docker pass |

For cycles 3 and 4, independent checks established:

- A distinct persistent incident and kernel attachment sequence for each return.
- The exact expected filesystem UUID, ext4 type, rw flags and zero ext4 errors;
  the kernel explicitly reported ordinary journal recovery completion.
- All six recorded data-file SHA256 values unchanged, including the three
  pre-existing validation files. The selected container's checksum matched the
  recovered host file.
- Exactly one automatic restart of the selected running container per incident.
  Its namespace device and bind inode matched the recovered filesystem; the
  stale disconnected mount was gone.
- Zero actions for the selected stopped container. The unrelated running
  container retained its original start time and process identity.
- Completed earlier application ledgers archived byte-for-byte, including the
  record from the previous container selection. No budget was reset to retry it.
- Monitoring re-armed, the GUI's live status reported success, and SMTP accepted
  the final outcome. Provider acceptance does not establish inbox receipt.

After cycle 3, restarting the monitor and observing it for 35 seconds preserved
the incident, attempt count and Docker ledger exactly. All container start times
and PIDs remained unchanged; no duplicate notification or recovery action was
created. Cycle 4 then recovered normally without another implementation change.

After the tests, only the disposable containers were removed. Their inspect
records, successful runtime state, ledgers, journals, history database and
checksums were preserved privately. All test files remain on the USB disk.
Original monitor/Docker configuration bytes and SMTP settings were restored;
the current successful incident and retry budget were retained. Monitoring is
enabled and the USB filesystem remains mounted read/write.

## Release verification and limits

The final build retains the recovery execution and web code tested in cycles
3 and 4. One subsequent read-only CLI diagnostic correction lets `status` report
a historical ledger selection warning alongside saved state instead of aborting;
it does not alter any recovery action or ledger guard. Its regression is included
in the 322-test suite. Package payload bytes, modes and root ownership are checked
against the installed files. Reinstallation preserves configuration, SMTP, current incident,
budgets, old ledgers and history. The build is reproducible from the source
archive and with a different umask. Source and unpacked artifacts pass the
privacy audit, including a private origin-value denylist kept outside Git.
Historical 1.0.0 and 1.1.0 baseline checksums remain unchanged.

The [earlier validation report](FINAL-VALIDATION.md) retains the nonempty-target
sentinel, dependent loop, mount refusal, worker timeout, SMTP failure/retry,
installation, HTTPS and security results. Those scenarios are distinguished
from these operator-performed physical cycles. Only Ubuntu 24.04 and Chromium
were validated live. Reboot recovery branches were simulated; the VM was not
rebooted. Independent electrical port reset qualification, separate power-fault
injection, other distributions/browsers and external inbox receipt are not
claimed. Active mounts of the returned device and recorded filesystem damage
still require intervention. Builds are unsigned; GitHub publication is pending
owner approval.
