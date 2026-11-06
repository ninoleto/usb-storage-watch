> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI24: successive recovery incidents

## Confirmed failure

UI23 completed one reported physical outage: the selected container stopped,
the retained disk mount was ordinarily unmounted, disk and selected image were
mounted, the container started and an outcome email arrived. The next outage
stopped the container but issued no storage command. Cleanup refused a mount
identity recorded as removed by an earlier cleanup.

The cleanup marker included an incident identifier, but its completed command
history was reused across all incidents in the same boot. That let an earlier
successful operation consume a later incident's retry budget or reject a reused
mount identity. Linux mount IDs may be reused after unmount:
https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html

## Correction

Completed cleanup history belongs to its original incident, boot and configured
storage identity. A validated settled record from an older incident is archived
and does not supply the new incident's retry counters, removed-mount checks or
pending loop continuation. Current storage and selected container stops are
freshly verified before new commands.

Legacy completed receipts can contain commands inherited from earlier captures;
those historical entries are preserved in the archive. An unreadable, malformed
or uncertain record is not silently discarded. Same-incident continuation keeps
its bounded retries and unfinished-operation protection.

The completed UI23 refusal with no storage actions is eligible for one automatic
resumption after upgrade and fresh checks. History and the USB-reset budget are
preserved; manual state-file deletion or unmount is not part of the update.

UI23's correction remains: old namespace references do not prevent an ordinary
unmount of the freshly verified local failed mount tree. Returned live-device
mounting and loop-device detachment still retain their availability checks.

## Verification boundary

Regression tests use the recovery engine and container ledgers through repeated
outages in the same persistent state directory. Kernel/device, Docker and mail
boundaries are simulated. UI23's first successful host cycle is observed user
evidence; UI24's repeated physical recovery is not established by these tests.
See TEST-RESULTS.txt in the release bundle for completed checks and limits.
