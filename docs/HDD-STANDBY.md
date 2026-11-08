# Mounted HDD standby

Sleep HDD now bypasses the configured idle timer, not storage safeguards. Apps
stay running, filesystems remain mounted, and monitoring is unchanged. Future
reads or writes may wake the drive. Automatic idle standby uses the same worker
checks after its idle timer expires. Idle handles, working directories and inactive
mappings are not activity and do not block sleep. Safe unmount, reset, removal and
recovery retain their separate strict consumer checks.

The action verifies the live UUID, stable USB identity, whole physical device,
mechanical-media evidence and OS-disk exclusion under the storage operation lock.
It refuses active swap. It flushes mounted loop-image filesystems before their
backing filesystem (even when mounted outside the parent's directory), then waits
up to 15 seconds for three continuous quiet seconds. Whole-drive reads, writes,
discards, flushes and in-flight requests, plus dependent-loop I/O, are checked.
Identity, mount IDs/options and loop backing/offset/size information are rechecked
before the command. Flushes have bounded timeouts and failure refuses standby.
The supervised worker has an overall timeout; an uncertain command is not replayed.

Only `hdparm -y` is sent, never ATA deep sleep `-Y`. The action uses `-C` to verify
standby if supported. A command rejection, unavailable verification and activity
that resumes during the command are distinct results. Software cannot prevent a
new application access immediately after a check; subsequent access waking the
drive is normal. Adapter compatibility requires a physical test. Routine power
status uses only kernel/cached metadata and the last confirmed state plus unchanged
I/O counters; it does not issue power or SMART queries.

## What is using this drive?

Manage Drive provides an explicit read-only sample (at least two seconds; bounded
Docker inventory acquisition can extend it). The displayed timestamp and actual
interval describe that sample, not current continuous monitoring. Refresh it for a
new observation. Sampling never flushes filesystems or queries device power.

The Linux whole-drive block counters are authoritative for standby. Container
attribution uses current Docker IDs/PIDs and host cgroup v2 `io.stat` with stable
process/cgroup identity across samples. It works independently of recovery selections.
A missing or unreadable counter, cgroup v1, shared/nested cgroups, identity changes
or incomplete Docker inventory are reported as unavailable, not zero. All known
running containers are sampled; activity can reveal a consumer beyond bind mounts.

Physical disk counters are preferred over partition counters. Loop counters are
reported as logical only when physical accounting is absent; physical and loop
bytes are never summed. The approximate unattributed physical remainder may include
native processes, filesystem initialization/journal work, writeback attributed to
another cgroup, unobserved containers and sampling skew. Buffered writes and shared
files do not permit exact attribution. A suspected ext4 initializer is not named as
the cause without evidence. Missing attribution does not itself block standby;
whole-drive and pending-I/O checks still apply.

Linux references: [cgroup v2 I/O](https://docs.kernel.org/admin-guide/cgroup-v2.html#io)
and [block I/O counters](https://docs.kernel.org/admin-guide/iostats.html).

## Hardware acceptance still required

Use an authorized test HDD with a verified backup; keep apps/monitoring running.
Record its live UUID/device and mounted image identities before testing.

1. With all consumers idle (including an idle open file), request Sleep HDD now.
   Verify standby if supported, unchanged mount IDs and container start times.
2. Read an existing file; verify its hash and normal wake/access. Do not treat a
   successful command or simulated power result as physical evidence.
3. During a disposable upload/read stream, check measured whole-drive I/O and
   per-container rates; sleep should wait/refuse while I/O continues. Repeat with
   image-backed data. Unattributed/background writes must not blame an app.
4. Check automatic standby after its configured idle interval, unsupported bridge
   reporting, and passive status observation without waking the disk.
5. Confirm existing safe-unmount/recovery safeguards in a separate authorized test.

Automated tests simulate block devices, Docker and power commands; browser/service
fixtures run locally against isolated configuration. No production permission,
container, mount, power or service change is part of candidate preparation.
