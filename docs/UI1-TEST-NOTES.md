> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch — UI1 TEST-ONLY integration

**Baseline**: DEV9 backend, unchanged recovery engine. **UI**: user-approved standalone graphite/teal/purple design adapted to real management-token authentication and live HTTP endpoints. **Target**: disposable Ubuntu Studio test machine. **Zorin** production system is excluded from deployment/testing.

## Integrated in this package

- Global Overview: configured drives, physical connection/mount state, monitoring and recovery badges; manual refresh/add drives.
- Per-drive Manage Drive: current status; start/stop monitoring; guarded mount/unmount/reconnect; independent automatic recovery and notification preferences.
- Global Event History: aggregated incidents with stable per-drive filter.
- Virtual Disk Images: view/mount/unmount/unregister existing images, plan and explicitly approve new images, scan selected USB drive read-only for orphaned `.img` files, review registration.
- Prepare Drive: target by physical disk identity; show real eligibility; server-issued review token; explicit checkbox and exact typed `ERASE ...` phrase before starting. Backend rechecks identity, busy state, permissions and target.
- Email & Notifications: shared SMTP settings/test mail, per-drive switches in Manage Drive.
- Bitfocus Companion: restricted token creation/revocation using existing module API.
- Advanced: local/LAN access switch and selectable connection mode; per-drive monitoring/recovery interval editing.

## Limitations — not accepted as production functionality

1. The `Reconnect USB port` action still depends on host `/proc/<pid>/fd` permissions. The previous `EACCES` failure on Ubuntu Studio has **not** been reproduced or corrected by this cloud build. The existing fail-closed behavior remains.
2. Mount-location changes with dependent virtual disk images/Docker settings may be refused to prevent broken paths; no automated dependency migration was implemented.
3. Docker & Applications shows existing configurations read-only; Docker recovery is still executed by the existing backend, but UI editing needs separate integration tests.
4. Existing `.img` files are discovered on the **host's selected USB drive**; browser upload, arbitrary network-copy and resuming large transfers are not implemented. The new server-side scanner is bounded and read-only; registration still requires backend verification.
5. Mechanical-HDD standby, physical multi-drive disconnect/reconnect, and scoped Companion status have **not been tested on physical hardware** for this package.
6. No destructive physical disk operation, USB port reset or real SMTP call was made during preparation here.
7. Full Flask HTTP-server tests could not run in the cloud container because its Python environment lacks Flask. The Debian package declares `python3-flask`; HTTP endpoint behavior still needs physical Ubuntu Studio acceptance.

## Test-first installation guidance

Use **only** on Ubuntu Studio after keeping a copy of its working configuration and previous `.deb`. Verify ZIP and enclosed checksums before installing. Do not format disks as part of the installation test. Start by checking dashboard login and drive status for both ADATA and SanDisk, then non-destructive per-drive settings. Independently review any mounted drives, dependency paths, and service state before attempting USB reset or formatting.

## Test gates

- [ ] Existing settings and separate drive profiles load after upgrade.
- [ ] Web login and switching between drives work through actual authenticated Flask broker.
- [ ] Browser matches approved desktop/mobile layout without duplicate sections.
- [ ] Mounting and monitoring on each physical test drive do not affect the other.
- [ ] Recovery refusal and errors are displayed precisely; no unexpected port reset.
- [ ] Image import/creation preserves original files and access permissions.
- [ ] Only after these pass: test physical recovery and Docker dependencies.

Do not deploy to production Zorin OS.

## Cloud verification performed for UI1

- Real Chromium (mock transport, authentic UI JavaScript) at 320, 390, 768 and 1440px: token login, two drive IDs, independent notification/recovery/monitoring controls, two-step recovery and virtual-image creation, history filtering, all screen navigation, cancel-before-format, and no horizontal page overflow — passed.
- Python backend isolated suites: 23 multi-drive, 88 recovery, 83 USB recovery, 5 prepare, 28 notification, 15 protection, 10 mount-directory tests; one new image-discovery test — **253 passed in those selected suites**.
- Private Debian/portable smoke validation: 12 isolated lifecycle checks passed (private dpkg root, upgrade/preservation, removal, staged services). Only synthetic test data was used.
- JavaScript syntax, Python module compilation and privacy audit passed.
- Flask HTTP integration tests were **not executed** in this cloud environment. Two historical test groups also require missing Flask or `mkfs.ext4`, so their environment-specific errors were not counted as passing results.

These checks authorize a **test build only**, not an acceptance claim for physical USB reconnect, drive formatting, HDD standby or Docker recovery.
