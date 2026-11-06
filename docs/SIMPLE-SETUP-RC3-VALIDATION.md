> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 1.1.1~rc3 — simple setup candidate

**Not release-ready. Physical Ubuntu Studio acceptance remains pending.**
Work and tests are confined to the development project. Neither production
Zorin nor the physical Ubuntu Studio computer was accessed. Nothing was published.

## Causes and changes

The previous five-step wizard exposed implementation details and required
separate recovery consent, mount preparation, email save and final validation.
RC2's reuse fix did not simplify that experience. RC3's normal Setup screen
contains drive names/capacities, automatic recovery, optional email and one
Activate protection button. Technical controls, migration and hardware
qualification are accessed through Advanced settings.

The backend checks the selected identity, existing connection entry and live
filesystem before offering activation. A unique valid entry is reused without
changing its path, even under `/run/media`. A new mounted drive can be registered
at its current safe location without unmounting it. A new unmounted drive gets
a protected location under `/mnt`. The plain-language preview explains any new
permanent registration, and the explicit activation binds consent to that plan.
Changed settings require another review/click. Email validates and saves as
part of activation, with exact-field errors and no separate save step.

Inspection exposed a further RC2 gap: the recovery worker required an unmounted
target on the system root filesystem, so accepting an entry under the host's
`/run` tmpfs in setup alone did not make it recoverable. A narrowly scoped fix
now supports `/run/media` on the actual host `/run` tmpfs. It retains the ordinary
mount operation and all disk, namespace, direct-probe and post-mount checks.
The root filesystem remains the only other allowed backing storage. State
storage restrictions are unchanged.

Desktop parents must be root-owned and not writable by other accounts. A
descriptor walk refuses symlinks and unexpected backing filesystems. Missing
desktop directories may be recreated safely; existing files, permissions and
ownership are never changed. This accounts for desktop cleanup of old transient
directories. [UDisks documents cleanup state](https://storaged.org/doc/udisks2-api/latest/UDisksState.html)
and [reuse of permanent entries](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Filesystem.html).
Concurrent desktop mounts are rechecked before save and by the recovery worker.
Setup does not disable desktop automounting or alter its internal state.

Activation takes the existing monitor lock and refuses unfinished recovery.
It keeps a private configuration backup before changes; failed writes restore
only content still matching this operation. Unrelated concurrent changes are
preserved. Optional migration retains its separate consent, durable backup,
resume and rollback. No setup action unmounts, repairs, formats or resets a disk.

Docker/dependent settings, incident state, retry budgets, queued notifications,
security checks and existing hardware profiles are retained. The new normal
flow never requests USB qualification. RC2's accurate peer explanation and
later [offline qualification procedure](USB-PEER-QUALIFICATION.md) remain intact;
no paired reset executor is enabled. Earlier physical results are historical,
not evidence that RC3 was tested on that hardware.

## Local validation

- 413 automated tests, including 23 Chromium browser workflows, pass without skips.
- Basic browser cases cover new unmounted and desktop-mounted drives, the
  existing configured entry, upgrade state preservation, optional email, changed
  consent, useful conflict handling, mobile width and accurate protection state.
- Advanced cases retain migration, rollback, virtualization and peer diagnostics.
- Directory tests cover tmpfs/root backing, readonly/nested/stacked rejection,
  symlinks, writable parents, missing-directory recreation and data preservation.
- The installed-package browser suite is also run with the exact UUID and
  `/run/media` path supplied in the Ubuntu Studio report, including its ext4
  options and `0 0` fields. The private identity file is not shipped.
- Private Debian installation/lifecycle, source archive, package lint, privacy
  scan and reproducible builds are recorded in `dist/validation-1.1.1-rc3`.

Browser tests use real Chromium, HTTP, authentication/session/CSRF handling,
broker validation and private configuration writes. PAM credentials, systemd,
disk discovery, live mount metadata and device probes are isolated fixtures.
They do not prove actual Ubuntu Studio desktop permissions, systemd startup,
Python 3.14 compatibility or physical recovery. No real disk recovery ran here.

## Physical GUI acceptance — still required

After installing this candidate locally on Ubuntu Studio:

1. Open `http://localhost:8765` and sign in with your Linux administrator account.
2. Open Setup and select the test drive by its name and capacity.
3. Leave Automatic recovery selected. Leave email off unless testing it.
4. For the existing test drive, confirm the explanation says its existing
   connection settings will be used. No location change should be requested.
5. Click Activate protection once. Confirm Protection is on and the drive is
   available. Existing files and applications using the drive should still work.
6. Reopen the browser and confirm the displayed protection state remains accurate.
7. Repeat on a fresh configuration with a new eligible USB drive: the explanation
   should ask to remember where to reconnect it, followed by the same one button.

Do not enter Advanced or use terminal commands to complete these basic cases.
If a case fails, record the short message and stop that case; do not manually
edit connection settings to make the test pass. A later supervised recovery test
must verify actual desktop reconnect/cleanup behavior. Never disconnect a busy
drive or run hardware qualification as part of ordinary setup acceptance.
