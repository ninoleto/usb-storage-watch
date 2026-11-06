> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# 2.0 DEV5 — test-only core corrections

Checkpoint: `checkpoint/pre-dev5-core-fixes-20261030`, at DEV4 `0c4a362`.
Development remains on `dev/simple-2.0`. No physical USB reset/format, production
access, live Docker testing or publication was performed for this build.

## Corrections

- USB: the bounded worker could be killed after a kernel disconnect but before
  recording that its sysfs write completed. Cleanup could then spend both enable
  attempts against the still-held writer lock. DEV5 records intent before the
  write, records its timeout stage, waits a bounded time for the writer, and
  independently verifies port re-enablement and the returned UUID/hardware at
  the pinned port. A previously connected disk must also have a new kernel USB
  attachment identity or an observed disconnect. Exit code zero and an unchanged
  disk are insufficient. Ambiguous power-off readback is not a reconnect failure.
  Filesystem mounting has a separate result. One disable budget, moved-port
  invalidation, hub exclusion, namespace and isolation guards remain intact.
  This code defect is reproduced synthetically; confirming the exact physical
  controller timing still requires the next Ubuntu Studio test. Electrical
  power removal is never inferred from successful logical reconnection.
- Virtual Disk Images (.img): mounted state/UUID/loop identity come from mount
  metadata, separately from local-user access. Access denied or an inspection
  error no longer becomes “Unmounted.” The observed EPERM was reproduced under
  the broker's combined systemd restrictions: CAP_SETUID was lost at exec.
  Retaining the already-bounded SETUID/SETGID capabilities fixes credential drops
  without disabling those restrictions. Non-root probes have zero effective
  capabilities and perform real create/read/modify/delete checks.
- New images default to the signed-in user's access. Explicit choices also cover
  an application group, selected local users or custom IDs. Parent traversal and
  mount-root ACL corrections require review/consent for existing images, preserve
  ownership and existing access, and never recursively modify files or lost+found.
  Backing files remain private. Existing image paths/configurations are retained.
- Management token: strong independent random token, private hash-only storage,
  rate-limited login, expiring sessions, CSRF and origin checks. Initial setup or
  recovery still permits named administrator login locally or over HTTPS, never
  over LAN HTTP. Token replacement revokes the old token and other sessions.
- LAN: one inline switch; localhost HTTP remains a separate service. Optional
  HTTP requires a management token and explicit unencrypted-network warning.
  HTTPS/certificate settings remain under Technical network settings with full
  verification. Only assigned private IPv4/VPN addresses can be enabled. Invalid
  settings and failed restarts roll back without restarting localhost. Existing
  DEV4 HTTPS configurations remain HTTPS; network access still defaults off.
- One graphite dark theme, retained mobile drawer/sidebar, compact spinner-free
  numeric controls with 44-pixel targets and deliberate phone wrapping. Existing
  defaults, resets and backend validation remain. Confirmed flash storage shows
  “Not applicable” and hides mechanical standby controls.

The automatic recovery sequence, SMTP, Docker/application ordering, deliberately
stopped-container handling, formatting engine and scoped Bitfocus Companion
endpoint are reused. The recovery engine itself changes only its version string.

## Validation

Focused regressions extend the existing unit/browser suite: USB lost-receipt and
ambiguous-readback success, genuine failure/timeout and bounded cleanup; independent
image mount/access states; token authentication/rotation/CSRF and private LAN;
existing configuration preservation; hub/port-change and formatting safeguards;
35 Chromium workflows including 320/390/768/1280-pixel layout, numeric defaults,
text contrast, one LAN switch, token login and explicit permission consent.

Isolated real Linux tests also passed:

- Separate Gunicorn listeners in a private network namespace: both localhost URLs
  throughout HTTP/HTTPS enable/disable, invalid certificates/settings, IP changes,
  failed LAN restart and exact rollback. Untrusted TLS and unauthenticated
  privileged requests are refused. Host network/services are not reconfigured.
- Non-root file access and zero child capabilities under the broker's full
  credential-drop/systemd restrictions, with temporary files only.
- QEMU with two disposable 1 GiB USB disks: preparation, UUID mount/remount,
  system/busy/namespace/loop/swap/device-mapper/layout refusals; two real ext4
  images; account/group/custom access; explicit repair of a restricted parent;
  unchanged existing files/lost+found/private backing files; ordered and partial
  recovery; selected-drive reformat with backups and real operation stages.
  The unrelated virtual disk's SHA256 remained unchanged.

The transfer bundle's TEST-VERIFICATION.txt records final test counts, installed
payload/DEV4 upgrade checks and privacy results for the exact packaged commit.

## Remaining physical acceptance

Ubuntu Studio 26.04.1 install/upgrade/reboot and Dolphin access; actual ADATA port
reconnect timing/readback, moved ports and hubs; phone/tablet LAN HTTP warning and
HTTPS trust; mechanical HDD and USB-SATA bridge standby/Bitfocus Companion. A
permanently blocked kernel writer remains a failure with a pending enable duty,
not a success or permission for another reset. Large/4K-sector drive preparation
still needs separately authorized hardware tests. QEMU uses an isolated minimal
Linux guest and stubbed systemctl, not a complete Ubuntu Studio desktop.

No claim of independently verified electrical power cycling or Zorin compatibility
is made. Live Docker testing stays deferred until these core physical tests pass.
