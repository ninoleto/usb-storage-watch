> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 1.1.1~rc2: migration and USB peer correction

**Not release-ready. Real Ubuntu Studio configuration acceptance is pending.**
All work was local to the development project. Neither the production Zorin
server nor the physical Ubuntu Studio computer was accessed or modified.
Nothing was published to GitHub.

## Why RC1 failed and what changes

RC1 classified paths under `/run` or `/media` as unsuitable without distinguishing
an existing valid UUID mount-table entry from a transient desktop automount.
It rejected the entry before creating any usable migration proposal. Repeated
refreshes could therefore never resolve the reported condition. Its clean
browser fixture did not exercise a legacy entry already at that location.

RC2 validates the actual UUID/type/options/path entry. A valid unique entry can
be kept unchanged, including a desktop-style path, and ordinary remounting can
be saved and monitoring enabled. This path needs neither new fstab consent nor
an unmount. New configurations without a permanent entry still propose `/mnt`.

An optional **Review migration to /mnt** flow previews the existing and proposed
entries and requires separate consent. It changes only the selected entry's
mountpoint field. All other fields, comments, formatting and unrelated entries
are preserved. It does not assume that a comment proves who created an entry.
The same validated, unique UUID relationship must hold at the final write.

Before migration, a mode-0600 backup in a private directory records the original
fstab, configuration and recovery state. The root-owned state directory holds
a durable migration journal. A monitor lock and stopped-service/incident checks
protect mutation. Pending migration blocks monitoring through the GUI. A browser
or broker restart does not lose the Continue/Rollback controls.

No migration action unmounts, mounts, repairs, formats, changes file ownership or
resets a disk. While the filesystem is mounted at the old location, the GUI
instructs the user to close consumers and safely release it in the desktop file
manager, reconnect if ejected, then **Check mountpoint again**. A busy filesystem
must not be forced or unplugged. Review/Save remain blocked until it is at the
new path or present and unmounted. Existing engine guards still govern any later
normal mount. The user can instead roll back and keep the valid original entry.

Final Save updates an established configuration and the recovery state's target
path without resetting incident budgets, queued notifications or history.
An interrupted multi-file commit remains recorded and blocks monitor activation;
rollback accepts known before/after file versions. It refuses to overwrite newer
settings, newly changed recovery state, an independently edited selected entry
or an old target claimed by another fstab entry. Unrelated later table edits
survive rollback. Backups are retained. Existing dependent-image and Docker bind
paths are never silently rewritten: the GUI can keep their valid original path
while a separate path migration is reviewed.

## USB peer investigation outcome

The earlier wording incorrectly implied that any peer proves hardware isolation
impossible. Kernel documentation describes USB2/USB3 peers as interfaces of one
physical connector. RC2 now assesses reciprocal direct root ports, controller,
speed classes, separate controls and peer occupancy read-only. Its diagnosis
separates a recognized unqualified pair from missing or inconsistent evidence.
The detailed findings, primary sources and proposed later operator-supervised
procedure are in [USB-PEER-QUALIFICATION.md](USB-PEER-QUALIFICATION.md).

**Paired resetting is still unsupported in this candidate.** The current
executor and cleanup ledger own only one logical port. A safe future pair-aware
operation needs two durable restoration obligations, correct ordering, fallback
identity checks and physical proof that no unrelated connector is affected.
No peer pair is enabled merely by passing discovery. No root-hub, shared-hub or
controller reset was introduced. The reported Ryzen hardware has not been
established either capable or incapable of independent electrical control.

## Development evidence

- 376 source tests pass, including the retained RC1 suite, 16 migration tests,
  9 USB peer tests and 4 additional Chromium workflows (13 browser tests total).
- The migration fixtures use the exact reported fstab entry shape and options,
  with a synthetic UUID and username. Actual disk identity is not distributed.
- Saved-state tests exercise the real engine state reader after migration and
  compare queues, incidents and exhausted USB budget fields before/after.
- Private Debian installation/browser, package lifecycle, privacy, lint and
  reproducibility results are recorded with the candidate in `dist/validation-1.1.1-rc2/`.

Chromium exercises actual pages, HTTP, session/CSRF handling, broker validation
and private filesystem writes. PAM, systemd, discovery and mount observations
remain synthetic OS boundaries. Safe desktop release/reconnect is simulated;
no physical user workflow or electrical USB behavior is claimed. Python 3.14,
systemd 259 and real Ubuntu Studio desktop behavior still require acceptance.
The recovery engine changes only its version. USB execution guards remain in
place; USB changes add read-only diagnosis and correct refusal wording. Docker,
notification logic, settings schema and prior physical-test reports are retained.

## Next real GUI acceptance test

Use the RC2 package on the same test installation with the existing entry
preserved. Do not delete configuration, state or fstab entries to make this test
look clean. A separate clean-install check is also useful, but does not replace
this migration regression. The following setup steps require no terminal or
manual fstab editing. Keep email, Docker and USB resetting disabled.

1. Install RC2 with the normal desktop package installer. Open
   `http://localhost:8765`, log in, and stop monitoring through the GUI if active.
2. Select the intended external ext4 disk and enable ordinary automatic
   filesystem remounting with its authorization checkbox. Verify that the
   existing UUID entry is shown as valid, with a **Review migration to /mnt**
   alternative. It must not require administrator review merely for `/run`.
3. First test **keeping the existing entry**: continue through Review, save and
   enable monitoring. Confirm accurate service and read/write disk status,
   unchanged entry and readable existing files. Stop monitoring in the GUI.
4. Return to Recovery, review migration, compare the exact old/new entry, and
   provide explicit migration consent. Verify the protected-backup location is
   shown. The filesystem should remain mounted at its current path until you
   release it yourself. It must not be automatically unmounted.
5. Optionally reload the browser now: **Mount migration pending**, **Continue
   migration** and **Roll back migration** must remain available. Test rollback
   with explicit consent while monitoring is off. The old entry/configuration
   should be restored; unrelated entries and data must remain unchanged. A disk
   that is already at the new path is not automatically moved back.
6. Review and consent to migration again. Close applications and files using the
   disk, safely unmount/eject in the desktop file manager, reconnect if ejected,
   and select **Check mountpoint again**. Never force an unmount or unplug a busy
   disk. If desktop mounting returns it to the wrong location, remain in Recovery
   or roll back; do not bypass the conflict check.
7. Continue to Review, verify the stable `/mnt` path, save and enable monitoring.
   Confirm accurate status and readable unchanged data. Previously recorded
   history and pending notification state must remain present.
8. In Advanced, check hardware support. A peer must be explained as a possible
   USB2/USB3 connector relationship, with the actual missing proof or software
   limit. USB resetting stays off. Do not attempt the separate offline hardware
   procedure during this setup test.

Record package SHA256, exact GUI messages and results privately. Do not loosen a
safeguard to obtain a pass. This candidate remains unproven on real hardware until
these configuration steps succeed. No publication or release-readiness claim is
made from the automated results alone.
