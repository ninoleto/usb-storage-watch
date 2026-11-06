# 2.0 prototype — 29 October 2026

Working branch: `dev/simple-2.0`. The entire pre-existing worktree was committed
as `05d501f`, tagged `checkpoint/pre-2.0-20261029`, before implementation.

## Reused components

- `engine.py`: filesystem UUID/superblock checks, namespace and mount guards,
  dependent ext4 loop recovery, durable incidents, worker deadlines and locks.
- `usb.py`: qualified single-port identity, reset ledger and independent re-enable
  guardian. Saved verified bindings remain usable when the expected disk is absent.
- `apps.py` and `notify.py`: selected Docker recovery, durable action receipts,
  SMTP TLS behavior and the existing persistent delivery queue.
- `web_auth.py`, Flask/broker boundary, styles and setup: PAM administrator login,
  sessions, CSRF, host/origin validation, private configuration and existing fstab reuse.

## Changed architecture

One recovery sequence per confirmed incident: normal mount if present; one safely
identified and qualified port cycle after a mount failure or device absence;
bounded return wait; one final normal mount. UUID, both read/write flags and
filesystem accessibility are checked, dependent storage is restored, selected
Docker containers and application services recover, and the final email is queued.
Failures stop the sequence. Service restarts and late USB re-enumeration cannot
renew it. Existing upgrade state and email queues remain intact.

Manual controls share the same guards and operation locks. Unmount is ordinary,
never forced, and pauses monitoring. A failed mount/reconnect leaves monitoring
paused with an explicit result. The port must qualify before manual reconnect
can unmount anything. Files underneath an unmounted mountpoint are preserved and
do not prevent mounting. No fsck, formatting, controller reset or forced mount
was added.

`standby.py` implements the requested idle-standby behavior using `/sys/block/*/stat`,
stable by-id identity plus connection sequence, process/file/mmap checks, Docker
access checks, flushing of the disk's mounted filesystems (including loops), and
`hdparm -y` with a pinned device descriptor. It verifies standby with `-C` only
at the operation, never during routine monitoring. Rejected bridge commands are
not repeatedly sent without new disk activity. Busy-user checks may retry after
60 seconds. A mounted sleeping drive remains healthy. Running Docker binds
conservatively prevent standby; containers are not stopped to make a disk sleep.

The main dashboard has the four disk buttons, automatic recovery, optional email,
idle-sleep settings, status and history. Advanced settings retains Docker and USB
qualification and adds dependent-loop/service configuration. Debian dependencies
now include the GUI, hdparm and a desktop browser launcher.

## Actual verification and remaining gates

- Ubuntu 24.04.4 VM: development monitor, broker and web services started; dashboard
  returned HTTP 200. The prior missing-drive incident and configuration survived.
- Automated suite: core filesystem, USB isolation/crash cleanup, Docker, SMTP,
  authentication, setup and Chromium workflow regressions, plus focused 2.0
  sequence/standby/manual-control tests: **435 tests passed**, including 25 real
  Chromium workflows; hardware actions in those tests are simulated.
- Live missing-device controls: Mount/Sleep refused the absent target, Unmount
  returned already unmounted, and Reconnect refused unqualified hardware. The
  monitor resumed, fstab/configuration/SMTP bytes were unchanged, and no email
  was queued. Unauthenticated HTTP status access returned 401.
- Installer payload staged into a private directory, including standby modules and
  desktop launcher. systemd unit and desktop-entry syntax checked. The privacy audit passed for 1,243 source and
  existing-package files (no new package was generated).
- No new Debian release package was built. No GitHub publication or production
  Zorin/physical Ubuntu Studio access occurred.

Physical acceptance is **unfinished**. The configured disposable ext4 USB drive
is absent; the attached drive is NTFS. The proven ext4 recovery scope is retained;
NTFS recovery is not implemented and the attached drive was not modified. No
mechanical HDD is attached. Real mount/unmount/reconnect, idle standby, bridge
compatibility and end-to-end hardware recovery must therefore be tested with the
appropriate disposable drive before packaging. USB reset remains restricted to
independently qualified single ports; VMware is not physical-port qualification.
Ubuntu Studio 26.04 and Zorin OS 18.1 have not been tested.

The original `hitachi-sleep-if-idle.sh` was not found locally. Its requested
behavior was implemented; exact equivalence to that script remains unverified.
The initial async questions request the disposable drive identity and a local
copy/path for that script; no production access was attempted.

## Running development copy and rollback

The VM dashboard is at http://localhost:8765, using the existing Linux administrator
login. Root-owned development code is under `/opt/usb-storage-watch-2-dev`.
`20-development.conf` overrides in the three `usb-storage-watch*.service.d`
directories select it without overwriting dpkg-managed code. The private archive
under `/var/lib/usb-storage-watch/backups/pre-2.0-dev-20261029T182956/` preserves the
prior code, configuration and state. Removing only these development overrides,
then reloading systemd and restarting the three services restores the installed
program. If settings were saved through 2.0, the older program also needs its
matching configuration from the backup. Restoring state/configuration is a separate deliberate
rollback operation; never overwrite a live recovery or pending USB enable ledger.
