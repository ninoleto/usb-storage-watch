> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

> Historical RC1 report. The later physical Ubuntu Studio test failed because
> RC1 rejected an existing UUID entry at a desktop path without offering migration.
> Superseded by [RC2 migration validation](MIGRATION-RC2-VALIDATION.md). The automated
> results below remain valid only within their recorded fixture scope.

# Setup wizard correction candidate: 1.1.1~rc1

Status: **not release-ready; fresh Ubuntu Studio acceptance pending**.
Development validation date: 2026-10-29. No GitHub publication, production-server
access or access to the physical Ubuntu Studio computer was performed.

## Causes and corrections

| Reported failure | Cause in 1.1.0 | Correction |
| --- | --- | --- |
| Physical computer shows VM warning | Advanced contained unconditional VM text; no virtualization detection fed the GUI | A bounded systemd-detect-virt call distinguishes detected virtualization, no virtualization detected, and unavailable detection. Physical hosts still need independent qualification. |
| USB recovery greyed out without useful guidance | The checkbox only tested profile.qualified and displayed a generic instruction | Separate labels/explanations for normal filesystem remounting and USB hardware port resetting. Explain missing saved qualification and how to continue with resetting off. Advanced reports the exact candidate refusal or the need to save a disk first. |
| Final Save unexpectedly demands permanent entry consent | Step navigation checked only disk selection; it did not run backend prerequisites. The broker copied the current desktop mountpoint | Read-only mount proposal and preflight, stable UUID-derived path, visible permanent-entry consent, field errors before Review, and fresh validation on Save. Explicit preparation handles a currently mounted desktop disk without unmounting it. |
| Monitoring off and stop-monitoring warning together | Setup always rendered the stop warning/button | Banner and badge use actual service state, refresh while editing, and update after stopping. Enabling verifies the service became active. |

`web_broker.py` supplies the read-only mount proposal, consent-bound preparation,
preflight and field metadata. `web.py` carries field/step errors through the
existing authenticated HTTP boundary. `web_static/app.js` blocks forward
navigation until prerequisites pass and focuses the identified field. The Apps
step performs no Docker discovery when Docker recovery is off.

## Permanent mount and desktop transition

For a clean configuration, an existing supported UUID entry is reused unchanged.
Otherwise a mounted stable path is retained; an unmounted disk or temporary
`/run/...` or `/media/...` mount proposes `/mnt/usb-storage-watch-<UUID>`.
The display includes the exact identity, path and options. New entries use
`defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s` and require explicit
consent. Changed proposals require renewed consent. Entries are appended with
an original-table backup; they are never silently replaced. A failed reload
restores the table when it has not been changed by another writer.

When the disk is still desktop-mounted, the approved permanent entry can be
created in Recovery before final configuration is saved. The GUI explains that
this entry persists if setup is abandoned. The user closes applications and
safely unmounts/ejects in the desktop file manager; if ejected, reconnects it.
**Check mountpoint again** verifies the transition. Setup refuses to continue
while the disk is still mounted elsewhere. If the disk is present and unmounted,
the existing monitor can perform its usual guarded mount after monitoring starts.
No setup action unmounts, mounts, repairs, formats or resets the disk. No terminal
commands or knowledge of the mount-table syntax are needed in this workflow.

UDisks documents that its mount method uses the existing fstab entry for a
referenced device. This supports the proposed desktop transition; actual Ubuntu
Studio desktop behavior still needs the fresh-install test below.
[UDisks Filesystem API](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Filesystem.html).
Virtualization detection follows the systemd tool's documented output and exit
status, with unexpected results treated as unknown.
[systemd-detect-virt documentation](https://www.freedesktop.org/software/systemd/man/259/systemd-detect-virt.html).

Conflicting aliases/entries, unsafe options, temporary established mount
configurations, symlinks, occupied targets and nonempty proposed unused targets
fail closed with guidance. Existing configurations needing migration remain
preserved and may require administrator review; the normal clean-install case
does not require editing fstab. The new target-content check applies to setup
proposals only; the recovery engine's existing nonempty-directory behavior is
unchanged.

## Validation evidence

| Check | Result |
| --- | --- |
| Complete source regression suite | 347 tests pass, no skips with development browser dependencies installed |
| Added backend setup regressions | 16 pass: virtualization, preview without writes, consent, stale plans, desktop conflicts, exact field errors, preserved entries/files, symlinks, concurrent edits and rollback |
| Added real Chromium regressions | 9 pass: clean login/setup/save/enable, disabled optional features, physical/virtual/unknown explanations, exact topology failure, pre-Review errors/focus, state banners, post-Review race and renewed consent |
| Installed Debian payload browser suite | 9 Chromium tests pass against code/assets from the actual deb installed into a clean private dpkg root |
| Private package lifecycle and extracted-source tests | 13 checks pass, including all 347 tests from the extracted source archive |
| Privacy audit and Debian lint | Privacy audit passes; Debian lint has zero errors and four existing absolute-executable-path style warnings |
| Reproducible build and SHA256SUMS | Two builds match byte for byte; final hashes are in dist/SHA256SUMS |

The Chromium tests use actual HTTP pages/assets, Flask, broker sessions and CSRF,
configuration validation and isolated on-disk writes. Every case starts without
saved disk or SMTP configuration. The clean Debian test installs the actual
artifact into a private dpkg root and uses the installed broker and assets.
PAM credentials, systemd, disk discovery and mount observations are synthetic OS
boundaries. A fixture simulates safe desktop release/reconnect; no host disk,
service, container, USB port or fstab is modified. These tests are **not** a booted
Ubuntu Studio install or a real desktop automount test. Development runtime:
Python 3.12 and Chromium 156 through Playwright 1.64.1; Python 3.14/systemd 259
runtime acceptance remains pending.

The previous 322 recovery/security/lifecycle regressions are retained. Core
engine code changes only its version string. USB, Docker, notification, settings
schema and existing physical-test reports remain intact, except the settings
module also reports the new version. Earlier hardware results remain in
RECONNECT-INVESTIGATION.md and FINAL-VALIDATION.md; they do not certify this new
wizard on Ubuntu Studio.

## Fresh Ubuntu Studio acceptance: user-operated, no terminal setup

Use the candidate Debian package on a genuinely fresh test installation with no
previous USB Storage Watch configuration. This report does not authorize wiping
an existing configuration to manufacture a clean state. Do not test on the
production server. Install the package with its recommended GUI dependencies
using the desktop package installer, then:

1. Open `http://localhost:8765` in the browser and sign in with your named Linux
   administrator account. Confirm Monitoring off and no stop-monitoring warning.
2. Choose the eligible external ext4 test disk. Confirm its identity yourself;
   the package contains no preselected real disk identity.
3. Leave email off. In Recovery, enable **Automatic filesystem remounting** and
   authorize it. Leave USB hardware port resetting and Docker recovery off.
4. Review the displayed current and stable mountpoints. If a new permanent entry
   is needed, select its separate consent checkbox. Existing entries should be
   reused unchanged, without requesting permission to append another.
5. If the disk is desktop-mounted at a temporary location, select **Create
   permanent mount entry**. Close files/applications and safely unmount/eject in
   the file manager; if ejected, reconnect. Select **Check mountpoint again**.
   Do not force an unmount or unplug a busy disk. If a conflict remains, the GUI
   must identify its current path and stay in Recovery.
6. Continue through Apps (Docker off, no daemon needed), then Review. Confirm the
   stable mountpoint and disabled optional features. No missing prerequisite
   should first appear here. Earlier missing consent must keep you in Recovery
   and focus its checkbox.
7. Select **Save and enable monitoring**, or save and then select **Enable
   monitoring** on Overview. Confirm service status and current disk status
   separately. If the disk is unmounted, wait for the configured normal recovery
   timing; a starting/recovering display must not claim it is already healthy.
8. Confirm files remain intact and readable. Reopen Setup: the stop banner should
   appear only while monitoring is on. Stop using the GUI and confirm the banner
   and badge update. Advanced must show no VM warning on the physical machine;
   unqualified USB resetting must remain disabled.

Record package SHA256, OS/Python/systemd versions, the proposed/current paths,
steps passed/failed and exact GUI messages privately. Stop on any discrepancy;
do not loosen a safety restriction to get a pass. Acceptance is pending until
this complete real workflow succeeds. No USB reset, Docker action or destructive
failure test is required for this wizard acceptance.
