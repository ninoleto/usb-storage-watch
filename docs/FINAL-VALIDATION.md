> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# Corrected 1.1.0 release validation

This report preserves the initial storage, failure, installer and security
validation. The [physical reconnect investigation](RECONNECT-INVESTIGATION.md)
records the subsequently discovered defects, corrections and two consecutive
successful operator-performed storage-plus-Docker reconnects. Read both reports
for the final acceptance scope; publication remains subject to owner approval.

Validation date: 2026-10-28. The version remains 1.1.0 because the GUI release
has never been published. Earlier 1.0.0 and 1.1.0 packages and their manifests
were preserved as read-only local baselines before rebuilding. Nothing was
published, uploaded or deployed to another machine.

## Environment and boundaries

Tests ran on a disposable Ubuntu 24.04 VMware guest, Python 3.12, systemd 255,
Linux 6.17, Docker Engine 29.1.3 and BusyBox 1.37.0. The real test medium was an
approximately 29.5 GiB ADATA ext4 USB flash drive. Before storage fault injection,
the harness independently checked the supplied live UUID, direct blkid result,
USB transport, model, capacity, serial and physical sysfs topology. The separate
50 GB VMware disk containing `/` was excluded. No disk was formatted,
repartitioned, erased or repaired. An existing 64 MiB image on the USB disk was
used for dependent-loop tests. No production server was accessed.

Live tests used five-second observations, two-sample confirmation and 15-second
recovery waits; the shipped defaults remain 15 seconds, two samples and 60
seconds. The real worker deadline test retained the normal 80-second limit.
Local SMTP tests used authenticated STARTTLS and implicit TLS, with certificate
verification against a temporary local test CA. No provider inbox delivery is
claimed. Private configuration, credentials, certificates, raw logs and device
identifiers remain outside the source and release packages.

## Recovery corrections

- Removed the nonempty-directory restriction from the engine and corresponding
  GUI setup validation. Normal mounts hide existing entries without deleting,
  moving or modifying them. Symlink and backing-filesystem checks remain.
- Allowed `needs_recovery` when an ext4 journal exists and no recorded error or
  invalid state is present. An unclean filesystem without a replayable journal,
  error/orphan state, recorded error count or read-only device still fails.
- Added explicit process mount-namespace inspection and Linux exclusive
  block-device opening before unmounted-device verification. This detects live
  or retained use of the returned device without inferring it from a journal
  flag. Inaccessible surviving namespace metadata fails closed.
- Preserved exact direct UUID/ext4 proof, fstab identity/options, occupied target
  and submount checks, post-mount device/rw/error checks, dependent-loop backing
  inode verification and durable Docker action budgets. Recovery uses ordinary
  `mount` only; no forced mount, fsck, formatting or destructive repair.
- Improved CLI choices: invalid disk numbers, ports and timing values reprompt
  with valid ranges; yes/no accepts y/n and rejects unknown responses; TLS mode
  errors explain the accepted choices. Dashboard design and recovery ownership
  remain unchanged.

The journal flags follow the [kernel superblock specification](https://docs.kernel.org/filesystems/ext4/super.html).
Exclusive block-device opening follows the [Linux open contract](https://man7.org/linux/man-pages/man2/open.2.html).
These checks do not certify all user data; checksum tests below provide separate
evidence for the validation files.

## Actual USB and installed-service results

| Scenario | Observed result |
| --- | --- |
| A: nonempty primary mountpoint | PASS: installed service performed a normal mount on attempt 1; exact expected ext4 UUID and rw status independently verified |
| Underlying primary sentinel | PASS: invisible while mounted; after a normal unmount its exact contents were unchanged; service then remounted automatically |
| B: interrupted ext4 journal | PASS: targeted USB storage-driver detach removed the actual block device; on rebind the supplied UUID returned with `needs_recovery` set and zero recorded errors |
| Kernel journal replay | PASS: service mounted on attempt 1 without manual mounting; kernel logged `recovery complete`, then an rw mount |
| Checksums | PASS: all three recorded 1 MiB files matched their pre-outage SHA256 values; inside-container checksum matched the recovered host file |
| C: Docker and stale old device | PASS: a selected running container retained its old bind through USB disappearance, then the service restarted it exactly once after the returned filesystem was verified |
| Intentionally stopped / unrelated Docker | PASS: stopped selected container had zero actions; unrelated running container retained its original start time and state |
| Interrupted recovery wait | PASS: restarting systemd service after outage confirmation preserved incident ID and original recovery deadline |
| Restart after Docker recovery | PASS: completed ledger was retained; no additional container start or restart |
| Same returned device retained in Docker namespace | PASS: normal host unmount left an active namespace bind; namespace guard refused remount and exclusive block opening independently returned busy |
| Failed incident budget | PASS: exactly two attempts, no mount commands or Docker changes, no renewed budget after monitor restart |
| Real stalled worker | PASS: SIGSTOP of the installed recovery child was terminated by the 80-second supervisor limit (80.22 seconds observed); uncertain work blocked further mounts, final failure was notified |
| Failure notification | PASS: one correctly titled RECOVERY FAILED message, including the guarded refusal, was accepted by the local TLS SMTP server |
| SMTP temporary failure | PASS: injected SMTP 451 retained the same event in the durable queue across restart; retry delivered one matching Message-ID and drained the queue |
| Dependent loop restoration | PASS: two complete automatic primary-plus-loop cycles; UUID, rw flags and backing inode verified; loop-file checksum preserved |
| Nonempty dependent target | PASS: normal loop mounting hid and preserved the underlying sentinel in both cycles |
| USB qualification | PASS: VMware companion-port topology refused qualification; automatic port resetting remained disabled throughout |

Successful storage and Docker recovery used the actual installed systemd service,
without a manual mount command, manual Docker restart or reboot. The harness
used normal unmounts to set up or inspect tests; during the disconnect test it
released the dead host mount while leaving the running Docker bind intact.
No container was manually stopped to make that successful recovery possible.
Disposable containers were stopped and removed only after the separate refusal
test concluded, as fixture cleanup.

The data-file SHA256 was
`fbbab289f7f94b25736c58be46a994c441fd02552cc6022352e3d86d2fab7c83`.

The disconnect was a targeted guest storage-driver detach/rebind on the real USB
medium, not a mocked block device. It does not demonstrate a physical cable
unplug, a power interruption or an electrically qualified USB port reset.

## Browser and security validation

Chromium/Playwright exercised named administrator PAM login, disk selection with
system-disk exclusion, STARTTLS and implicit-TLS test mail, password clearing and
API secrecy, automatic mount settings, discovered running/stopped container
selection, rejection of a read-only bind, monitoring enable/disable, live disk
and service status, readable success/failure history, separate advanced settings,
unsupported hardware explanation and logout. Desktop and 390-pixel layouts had
no horizontal overflow or JavaScript errors. Axe reported zero violations on
login, Overview, Setup, Events and Advanced.

Live HTTP tests rejected unauthenticated access, root login, missing CSRF and
wrong Origin. The unprivileged web UID could not read engine configuration,
SMTP credentials or engine state; unauthenticated direct broker mutation was
refused. A real SMTP authentication failure exposed no password in API responses
or journals. Four malformed HTTP framing cases were rejected by the bundled
server. LAN tests rejected wrong certificate hostname/key, wildcard bind
and missing explicit confirmation. Certificate-verified HTTPS to the VM's own
LAN address accepted TLS 1.2/1.3 and rejected TLS 1.1. Browser cookies were Secure,
HttpOnly and SameSite=Strict; old sessions expired. Returning to local mode
removed the LAN listener and restored loopback-only service. The HTTPS browser
context permitted the disposable certificate; a separate Python client verified
its chain and hostname against the VM trust store.

Only a visually reviewed screenshot of the empty login page is included in
public documentation. Its exact bytes are pinned by the privacy audit; raw
dashboard screenshots with runtime identifiers remain private.

## Installation, automated checks and build review

| Check | Result |
| --- | --- |
| Full unit/simulation/GUI/security suite | 301 passed at this checkpoint; the final corrected suite has 322 passing tests, with no skips |
| Staged Debian/portable integration | 13 checks pass, including tests from extracted source |
| Booted Ubuntu portable lifecycle | 6 checks pass: clean install, upgrade, disabled GUI preservation, headless selection, removal and reinstall |
| Booted Ubuntu Debian lifecycle | 6 checks pass: clean baseline install, real 1.0-to-corrected-1.1 upgrade, disabled GUI preservation, headless selection, remove/purge and reinstall |
| Actual VM Debian lifecycle | Running reinstall restarted the monitor; remove/purge preserved config/SMTP/state bytes; reinstall restored localhost GUI with monitoring disabled |
| Lifecycle preservation | Configuration, synthetic SMTP credentials and persistent marker bytes preserved; monitoring never implicitly enabled |
| Syntax and unit files | Python parsing, JavaScript syntax, shellcheck and systemd unit verification pass |
| Bandit review | No applicable high/medium finding; Python-2 `input()` warning is inapplicable to Python 3; low findings reviewed for argument-list subprocess use |
| Lintian | Zero errors; four intentional absolute-command-path style warnings in maintainer scripts |
| Bundled dependency | Unmodified Gunicorn 26.2.0 source and MIT license match the per-file lock and upstream wheel digest |
| Reproducibility | Three byte-identical builds: workspace, changed umask, and a clean extraction of the portable source |
| Privacy | Source and unpacked Debian/tar payloads passed normal scanning and comparison against a private VM/SMTP identity denylist |
| Checksums / baselines | Both release artifacts verify against SHA256SUMS; both read-only historical baseline manifests remain unchanged |

Test-harness corrections included explicit lsblk tree output, handling older
mail captures without Message-ID, waiting for the browser page to load, and
matching the engine's `timed out` wording. The deadline scenario was repeated
from the beginning after fixing its assertion. One VM installation attempt
overlapped a package rebuild; repeating the complete lifecycle against an
immutable package copy passed. These fixture issues did not require weakening
recovery guards or changing the dashboard.

The local Git repository includes source, tests, installation/GUI documentation,
MIT license, dependency notices and draft release notes. Build artifacts, private
configuration, databases, logs, certificates and VM files are excluded from Git.
The portable archive contains the complete source tree. No remote is configured
and no public repository, tag or release was created. Final assets are
`dist/usb-storage-watch_1.1.0_all.deb`,
`dist/usb-storage-watch-1.1.0.tar.gz` and `dist/SHA256SUMS`.

The dependency check used [upstream PyPI metadata](https://pypi.org/project/gunicorn/26.2.0/)
and the [upstream advisory page](https://github.com/benoitc/gunicorn/security/advisories).
The metadata listed no vulnerabilities at review time; this is not a guarantee
against undiscovered or future vulnerabilities. Distribution packages provide
Flask, PAM and OpenSSL. No dependency download occurs during installation.

## Limits

Only Ubuntu 24.04 and Chromium were validated live. Booted installation tests
used a separate Ubuntu systemd/network namespace; they are distinct from physical
hardware tests. Reboot-specific engine branches remain covered by simulation;
the VM was not rebooted during these acceptance tests. Physical unplug/reconnect
was subsequently verified in the linked investigation. Separate power-fault
injection, qualified electrical port resetting, other distributions, Firefox/Safari
and external email inbox receipt are not claimed tested. Active returned-device
mounts, recorded filesystem damage and read-only storage still need operator
intervention. Artifacts are unsigned and publication remains subject to approval.
