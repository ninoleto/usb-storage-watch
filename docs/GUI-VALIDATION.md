> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 1.1.0 — GUI validation

Historical baseline report from before the final recovery corrections. Its
journal-recovery restriction is superseded by [FINAL-VALIDATION.md](FINAL-VALIDATION.md).

Validation date: 2026-10-27. Environment: disposable Ubuntu 24.04.4 amd64 VMware
guest, Python 3.12, systemd, Docker Engine 29.1.3, and a dedicated approximately
29.5 GiB USB ext4 test filesystem. No production machine, Windows host or shared
folder was accessed. Nothing was published.

## Scope and architecture

The new dashboard runs as `usb-storage-watch-web`, a non-login account without
capabilities, engine-state access, SMTP-file access or Docker-socket access. A
separate root broker exposes a bounded Unix-socket allowlist. It checks peer UID,
PAM administrator login, session validity and mutation CSRF tokens independently
of the web process. The browser has no direct disk-operation endpoint.

The existing engine, application-recovery module, USB module and SMTP sender
were compared against the archived 1.0 source: unchanged except the engine's
version string. Persistent incidents, retry budgets, mail queue, systemd cleanup
and once-per-incident container actions remain owned by that implementation.

The tested 1.0 Debian and portable packages are retained as read-only copies in
`dist/baseline-v1.0.0/`, with their original checksums. The original core validation
report remains [VALIDATION.md](VALIDATION.md).

## Automated and live results

| Check | Result |
| --- | --- |
| Core regression suite | All original 252 tests pass |
| New GUI/security/lifecycle tests | 43 pass; total suite 295 tests |
| Extracted archive test suite | Pass; self-contained source, optional Flask HTTP tests available in validation environment |
| Isolated package lifecycle | 13 checks pass using private dpkg roots and staged portable installation |
| Booted portable installation | 6 checks pass in an isolated systemd/network container; host package installation unchanged |
| Actual Debian lifecycle | 6 checks pass on the VM: running reinstall, disabled GUI preservation, explicit headless, remove, purge, reinstall |
| Initial 1.0 → 1.1 upgrade | Monitor configuration and state preserved byte for byte; monitoring remained disabled |
| Browser | Chromium/Playwright: login, setup, settings, status, history, diagnostics and logout pass |
| Responsive layout | Desktop and 390-pixel mobile viewport pass, no horizontal overflow |
| Accessibility | axe: zero reported violations on login, Overview, Setup, Events and Advanced after fixes |
| Disk discovery | Real USB model/capacity/ext4/UUID/mountpoint shown; system disk absent; synthetic duplicate/system-clone UUID cases refused |
| First-run wizard | Empty configuration handled; real disk selected; email/recovery/containers saved; monitor enabled through browser |
| SMTP | Real local authenticated STARTTLS and implicit TLS tests accepted; password cleared from inputs, retained only privately, absent from config responses; real authentication failure sanitized |
| Missing permanent mount entry | Explicit fstab confirmation required; actual UUID entry created and validated, existing system entries preserved, original fstab restored afterward |
| Docker discovery | Running and intentionally stopped writable binds selectable; read-only bind refused; no manually entered source/destination paths |
| Real recovery through GUI settings | Normal unmount followed by first automatic remount exactly 60 seconds after confirmation |
| Docker recovery | Selected previously running container started once; intentionally stopped container preserved with zero actions |
| Integrity and mail queue | Test-data hashes unchanged; incident notification delivered locally; queue drained |
| Restart persistence | Monitor restart does not replay the Docker action; GUI history survives broker restart; old sessions expire |
| HTTPS LAN | Explicit private-address bind, matching certificate/key, verified CA/hostname, TLS 1.2+ and Secure cookie pass |
| Network rejection tests | Mismatched hostname/key, missing confirmation, public/wildcard addresses, wrong Origin and TLS 1.1 rejected |
| Return to local access | LAN listener removed, HTTP loopback restored, old sessions invalidated |
| HTTP parser | Conflicting transfer codings, unknown coding, duplicate lengths and malformed header whitespace refused |
| Privilege boundaries | Web UID cannot read root engine configuration/state or SMTP files; only authenticated allowlisted broker operations accepted |
| Static checks | Python syntax, changed-code Pyflakes, JavaScript syntax, shellcheck and systemd unit verification pass |
| Debian lint | Zero errors; four reviewed absolute-executable-path style warnings retained deliberately |
| Privacy/dependency/build review | Source and unpacked artifacts audited; pinned upstream hashes verified; clean-build checks recorded with final artifacts |

The browser's HTTPS UI/cookie test used an isolated Chromium context permitting
the disposable test certificate because Chromium has its own trust store. A
separate Python client verified the certificate chain and hostname against the
VM's temporary trusted CA, including a connection to the VM's actual LAN address.
No external email inbox or second physical LAN client was involved.

The recovery test independently verified USB identity, UUID, capacity and mount
relationships immediately before a normal unmount. The disposable running
container was stopped by the test harness after outage confirmation to release
its retained filesystem reference. This is necessary because the engine
correctly refuses a new mount while stale container namespaces still use that
filesystem. The engine does not stop containers to force recovery.

## Defects found and resolved

- First-run status tried to validate an empty disk UUID; it now presents the setup
  entry point without invoking configured-engine validation.
- Docker discovery validated a half-built recovery draft before mount options and
  selected binds were resolved. Discovery now probes with actions disabled, then
  validates the complete configuration before writing it.
- OpenSSL `x509 -checkhost` returns exit status zero on mismatch. The broker now
  checks the actual match result, validity start/end and key pairing.
- An HTTP-to-HTTPS change could retain an older non-Secure browser cookie. Network
  changes now delete that cookie and invalidate every broker session.
- Advanced settings could inherit unsaved container selections from a previous
  setup view. Views now reset draft selections and reject stale navigation results.
- Large Unicode event histories are bounded by encoded response size, avoiding
  failures when many long incidents fill the archive.
- Logout now clears private page contents and pending view state as well as the
  cookie/session, including unsaved SMTP input.
- GUI disable/headless choices and previously enabled GUI reinstall behavior are
  retained explicitly across package/portable lifecycle operations.
- Accessibility fixes added a login main landmark, stronger footer contrast and a
  keyboard-focusable journal pane.
- The Debian changelog date and PAM conffile metadata were corrected; shell lint
  and unused imports were cleaned up.

Two validation fixtures also needed correction: one selected the implicit-TLS
mode while testing a STARTTLS port, and one queried the web listener immediately
after systemd returned from restart. Tests now select the intended mode and wait
for listener readiness. These did not require recovery-engine changes.

## Dependency and security review

The VM runtime was updated to Ubuntu security candidates: Python 3.12 package
`3.12.3-1ubuntu0.17`, OpenSSL `3.0.13-0ubuntu3.16`, PAM
`1.5.3-5ubuntu5.7` and CA certificates `20260816ubuntu0.24.04.1`. The full
regression suite, PAM/browser login and SMTP/HTTPS tests were repeated afterward.

Flask is distribution supplied; the VM uses the patched Ubuntu package
`3.0.2-1ubuntu1.1`, matching [USN-8104-1](https://ubuntu.com/security/notices/USN-8104-1).
Ubuntu's packaged Gunicorn was rejected because its old parser version still has
unresolved advisories, including [CVE-2024-1135](https://ubuntu.com/security/CVE-2024-1135)
and the issue documented in the [Debian CVE-2024-6827 tracker](https://security-tracker.debian.org/tracker/CVE-2024-6827).

The application instead bundles unmodified Gunicorn **26.2.0** Python sources
from the [upstream PyPI release](https://pypi.org/project/gunicorn/26.2.0/), MIT
license included. The wheel SHA256 is
`bd249d0b3f7972f7432f0a6b6ff3b3ee2d129f70cd1ff6c09a9dd9e29a2b88e3`.
`tools/vendor-lock.json` records the upstream URL and every included file hash.
The build refuses mismatches. Only the standard-library HTTP/1.1 gthread path is
used; optional parsers, HTTP/2, ASGI and the control socket are disabled.
No install-time network downloads, vendored binaries, analytics or CDN resources
are required. OS security updates maintain Flask/PAM/OpenSSL; the bundled server
needs deliberate package updates.

Bandit findings in first-party code were reviewed: subprocess calls use argument
lists, never a shell; remaining low-severity findings concern imports, fixed
commands and validation assertions in tools. The inherited high-severity `input`
finding assumes Python 2 and is inapplicable to this Python 3-only application.
This is a development security review, not an independent penetration test or a
claim that all future dependency vulnerabilities are excluded.

## Limits and release assessment

- GUI and live package behavior were tested on Ubuntu 24.04 only. The portable
  lifecycle ran in another isolated Ubuntu root, not a second distribution.
- VMware's USB port has a companion peer; qualification is refused and USB resets
  remain off. No physical electrical reset is claimed. The existing synthetic
  engine tests retain coverage of the 20-second window and retry limits.
- The GUI requires ext4 and the existing engine's storage safety constraints.
  Filesystems needing journal recovery, damaged/read-only filesystems and retained
  container mount references can correctly require manual intervention.
- Switching an established disk requires safe state archival by an administrator.
  Dependent loop-image configuration remains in the CLI and is preserved by GUI
  saves. These are documented advanced tasks, not silently unsupported controls.
- LAN setup requires a trusted certificate supplied by the administrator; automatic
  issuance/renewal and public Internet exposure are outside scope.
- History is a bounded presentation archive; incidents overwritten while the broker
  is stopped may not be captured. The engine state and journal remain authoritative.
- Browser checks used Chromium and automated accessibility tools; Firefox, Safari,
  physical mobile devices and user studies were not tested.

The implementation is suitable for **release review within the verified Ubuntu
24.04 scope**, with no known failing functional test remaining. Broader platform
and physical-USB compatibility must not be advertised as verified. Nothing has
been signed, uploaded or published. Final packages are
`dist/usb-storage-watch_1.1.0_all.deb` and
`dist/usb-storage-watch-1.1.0.tar.gz`; consult `dist/SHA256SUMS` for their final hashes.
