> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 1.0.0 — VM validation report

Historical baseline report. See [FINAL-VALIDATION.md](FINAL-VALIDATION.md) for
the corrected initial GUI release and its new hardware validation.

Validation date: 2026-10-27. Release disposition: ready for release within the
supported scope below, with USB port resetting disabled on unqualified hardware.
No source or package was published.

## Environment and boundaries

The main target was an Ubuntu 24.04.4 VMware guest with Linux 6.17.0-29-generic,
Python 3.12.3, systemd/udev 255, util-linux/mount 2.39.3 and Docker Engine 29.1.3.
Docker tests used the configured API v1.47 and BusyBox 1.37.0 containers with
networking disabled. Mail tests used a loopback-only aiosmtpd 1.4.4 test server,
a temporary trusted test CA, authentication, STARTTLS and implicit TLS.

A separate booted Ubuntu 24.04 systemd-nspawn container exercised the portable
installer against its own filesystem, package database and service manager. Its
network was private. Host program/unit/configuration fingerprints were unchanged
by the portable tests.

The approximately 29.5 GB disposable USB drive was identified using the supplied
filesystem UUID, independent blkid/udev information, physical serial, USB
transport, capacity and mount relationships. Identity was rechecked before
storage operations. The Ubuntu system disk was never formatted, repartitioned
or erased. Only a new 64 MiB regular image on the verified USB filesystem was
formatted for the dependent-loop test. No production server, host shared folder
or Windows host was accessed.

## Defects found and corrected

1. **Environment-dependent USB tests.** Three controller test methods followed a
   symlink into the host's real xHCI driver directory. Hiding `/sys` inside a
   private test mount namespace reproduced eight errors, including subtests.
   The fixture now supplies its own driver tree and synthetic resolution. A
   different-driver rejection test was added. The complete suite passes both
   with normal sysfs and with sysfs hidden in that private namespace.
2. **Dependent-loop udev race.** A real recovery mounted the loop image but
   reported partial recovery because udev filesystem identity was not yet
   complete. Previously only a missing metadata file triggered the bounded
   retry. Incomplete UUID/type fields now trigger the same three-second
   read-only verification wait. Known wrong UUID/type values still fail
   immediately. Five focused regressions cover missing fields, known mismatches,
   retry without another mount, and timeout. Three subsequent complete real
   main-plus-loop recovery cycles passed.
3. **Debian packaging.** Added the separate `mount` dependency, versioned
   util-linux/coreutils dependencies, standard copyright and compressed
   changelog/manual files, and an installed-size estimate. Package directories
   now have deterministic 0755 permissions instead of inheriting a builder's
   group-writable umask.
4. **Installer separation and permissions.** Debian pre-installation now refuses
   an existing portable manifest. The portable installer already refuses dpkg
   ownership; both directions were exercised live. Portable installation now
   applies a safe umask, including when invoked by a permissive caller.
5. **Beginner-facing diagnostics.** Setup excludes entire disks containing the
   system root, boot, `/usr` or `/var`, and displays the parent model for
   partitions. Unsupported USB companion ports or missing firmware identities
   produce an explanatory error instead of a generic subprocess failure.
6. **Compressed documentation audit.** The final privacy gate initially treated
   the new Debian gzip documentation as unexpected binary content. It now
   decompresses only the two known documentation paths, with a 1 MiB output
   limit, and applies the same identity/secret checks to their text. Regression
   tests cover hidden private values, unexpected binaries and malformed or
   oversized compressed documents.

A repeat-test setup briefly encountered a busy parent mount while a loop detach
was still settling. The harness was corrected to wait for udev and loop release;
no forced unmount was used and no application guard was relaxed.

## Automated and build checks

| Check | Result |
| --- | --- |
| Final Python unit/simulation suite | 252 tests passed |
| Shuffled test order | Five runs of all 252 tests passed; 1,260 executions |
| Private namespace with `/sys` hidden | All 252 tests passed as root |
| Extracted portable source | All 252 tests passed |
| Isolated Debian/portable lifecycle suite | 13 checks passed |
| Permissive-umask installation and Debian payload modes | Passed; no group/world-writable program paths |
| systemd unit syntax/dependencies | Passed on the VM and in the isolated test root |
| Clean package rebuilds | Both artifacts byte-identical under umasks 002 and 077 and when rebuilt from the extracted portable source |
| Archive and Debian payload review | Expected project files only; normalized ownership and timestamps |
| SHA256 manifest | Both final release artifacts verified |
| Lintian 2.117 | Zero errors; three reviewed warnings for intentional absolute command paths in maintainer scripts |
| Privacy audit | Source and unpacked artifacts passed, including a private VM-identity denylist outside the distribution |

The absolute paths in maintainer scripts intentionally select the expected
system Python, timeout and systemctl programs. The three Lintian style warnings
are retained rather than changing that behavior.

## Installed service, filesystem and timing tests

| Scenario | Observed result |
| --- | --- |
| Actual Debian installation | Version 1.0.0 installed; no automatic service enable/start |
| Start without configuration | Clean exit with setup guidance; no observation loop |
| Interactive setup and SMTP setup | Dedicated USB selected; protected configuration saved; no mounting or recovery action performed by the wizard |
| Corrected setup discovery | System disk excluded; USB model shown; active-service reconfiguration refused without changing configuration |
| Healthy startup/restart | No new failure event or application action |
| Default 15-second observations | Two bad observations confirmed an outage; one transient bad observation did not |
| Unmount and automatic normal mount | Real ext4 remounted on attempt 1; test-data SHA256 unchanged |
| Restart during first recovery wait | Incident identity and original deadline retained |
| First recovery delay | Measured 60 seconds after confirmation |
| Failed first attempt and second wait | Measured 60 seconds from completion of attempt 1 to attempt 2 |
| Maximum recovery attempts | Exactly two; no further mount attempt while the completed outage remained down |
| Natural restoration during wait | Read-only verification and natural-restoration outcome; no mount/reset action claimed |
| Guest USB storage-driver detach/rebind | UUID disappeared; absent first attempt did not reset USB; return was detected and attempt 2 remounted the filesystem |
| USB detection window, real clock with synthetic readiness | Timeout 20.0004 seconds with 80 probes; early-ready exit 1.0017 seconds |
| USB disable/enable and one-reset budget | Simulation coverage passed for one-second disable, failed enable, guardian cleanup, interrupted reset and no repeated reset |
| Dependent loop recovery after fix | Three real complete recovery cycles passed, including UUID, rw flags and backing-image inode verification |
| Wrong dependent UUID | Main mount recovered; image was not mounted; partial-recovery notification delivered |
| Read-only main filesystem | `check` returned 2; two recovery attempts left it read-only; failure notification delivered; manual rw restoration re-armed monitoring |
| Retained Docker bind mounts | Active-journal clean-state guard refused automatic remount; no forced mount, repair or container stop |
| Data integrity | Original 1 MiB sentinel and dummy container data retained |

Default timing was used for the 60-second timing and default-monitor tests.
Later Docker, loop and guard tests explicitly used five-second observations and
15-second recovery waits to shorten scenario execution. These settings were
local test configuration, not changed distribution defaults.

## Docker and interruption tests

Four disposable containers represented two selected running applications, one
selected intentionally stopped application, and one unselected application.
Writable `rprivate` binds, actual namespace device/inode identity, healthchecks
and inside-container read-only directory access were verified.

| Scenario | Result |
| --- | --- |
| Read-only `verify-apps` preflight | Passed for running containers; stopped container preserved |
| Main mount recovery followed by application start | Both previously running containers started exactly once after the harness released their old mount references |
| Natural main restoration followed by application restart | Both selected running containers restarted exactly once |
| Intentionally stopped application | Never started by recovery |
| Unselected application | Never started/restarted/stopped by the monitor |
| Container exits with status 42 on restart | Failed application recorded after bounded verification; another selected application recovered; attention notification delivered |
| Restart of monitor after final application failure | Failed action was not repeated |
| Monitor killed after Docker accepted a restart | systemd restarted the service after approximately 10.6 seconds; durable intent resumed verification only; one action per selected container |
| Persistent application results | IDs, action budgets, verification results and failure reasons survived restart |

The test harness, not the application, stopped dummy containers where necessary
to release their namespace mounts. The monitor itself never restarted the Docker
daemon or acted on an unselected container.

## Notifications and persistence

Authenticated STARTTLS and implicit TLS both delivered to the local test server.
Wrong authentication, an untrusted certificate and a server without STARTTLS
were rejected. A temporary SMTP 451 rejection retained the event for retry;
service restart preserved its ID and the later retry was accepted.

The retained complete captures contain 18 valid messages: 14 incident outcomes,
three explicitly labelled email tests and one explicitly labelled package
lifecycle test. Each of the 14 captured incidents has one final outcome and all
18 Message-IDs are distinct. Outcomes include automatic attempt-1/attempt-2
recovery, natural restoration, partial storage recovery, application failure and
manual-intervention failure. Credentials were absent from the captured bodies.

A session interruption coincided with a VM reboot. `/tmp` logs were lost and two
old test-server capture files were incomplete; those files were retained as
private evidence, not counted as valid captures. The journal confirmed acceptance
of the earlier queued failure message, and persistent state had an empty queue.
Subsequent logs were kept under `/var/tmp`, and the disposable SMTP capture server
was changed to fsync its files. The final checks and additional failure/recovery
notification scenarios were completed after resuming.

This verifies local SMTP behavior, not an external provider's inbox or spam
handling. Ordinary SMTP still cannot promise exactly-once inbox delivery after
an ambiguous acknowledgement.

## Package lifecycle

The real VM exercised a running/enabled Debian service through a private
control-metadata-only test upgrade to 1.0.1, return to 1.0.0, and same-version
reinstallation. The service restarted only when previously active, remained
enabled during upgrades, and preserved configuration, synthetic SMTP credentials,
incident identity, attempt counts and a queued notification. The temporary 1.0.1
package is private test material, not a release artifact.

Real `dpkg --remove`, `--purge` and reinstall preserved private configuration,
credentials, history, the queue and a preservation fixture. Removal disabled the
service. Reinstallation left it inactive; starting it explicitly delivered the
retained test event. Live portable install/uninstall attempts against dpkg
ownership were refused without stopping the Debian service.

The extracted portable tar archive independently passed live installation,
active upgrade with program backups, enabled service startup after container
reboot, removal, reinstall and preservation checks. Attempted Debian installation
on top of that portable installation was refused before unpacking. Separate
staged tests also verified symlink escape rejection and refusal to remove an
unresolved USB enable obligation.

## Security, privacy and dependencies

The runtime uses Python's standard library and distribution tools; no vendored
Python libraries, credentials, certificates, test images or runtime state are
included in either release artifact. Required Debian tools are explicitly
depended upon; Docker remains optional. Runtime code and systemd units are
root-owned and not writable by ordinary users. Configuration/state directories
are 0700 and protected configuration files are 0600.

Review covered command arguments, path/UUID checks, configuration fingerprints,
locks, persisted action intent, USB enable obligations, subprocess deadlines,
verified SMTP TLS, sanitized errors, selected-container boundaries and package
lifecycle hooks. There is no telemetry or publishing code, no user-controlled
shell execution in the host service, and no controller-wide reset or automatic
filesystem repair. Docker's inside-container shell probe is fixed code with the
path passed as a quoted positional argument.

Bandit 1.6.2 scanned runtime and tools with no parsing errors. Its 52 findings
were reviewed: 51 low-severity reports concern explicit subprocess/exec usage,
imports, tool PATH lookup and validation-test assertions. The one reported high
finding is B322's Python-2 `input()` warning; this application requires Python 3,
where `input()` does not evaluate code. No unresolved application security defect
was identified by this review. This is not a whole-OS vulnerability certification
or a substitute for distribution security updates.

Private disk UUIDs, hardware serials, host identity, local paths, generated keys,
mail and test configurations remain outside the distribution. Both the standard
privacy scanner and an additional private identity denylist were used. Package
SHA256 values provide integrity checking; the release is unsigned.

## Limits and release scope

- VMware exposes a companion port and lacks the required usable stable firmware
  identity. Automatic port reset was correctly refused and remains disabled.
  No electrical power cycle, cable removal, controller reset or physical-port
  qualification is claimed. The operator's optional Workstation passthrough
  step is documented in [USB-QUALIFICATION.md](USB-QUALIFICATION.md).
- Guest driver detach/rebind validates block-device disappearance and return,
  not universal physical USB compatibility.
- Abrupt unplug/power loss can leave ext4 needing journal recovery. Retained
  container mounts can also leave its journal active. Automatic mounting must
  refuse those conditions; manual intervention can be necessary. The observed
  behavior is consistent with [Docker bind propagation](https://docs.docker.com/engine/storage/bind-mounts/)
  and the kernel's [ext4 recovery-required feature](https://cdn.kernel.org/doc/html/latest/filesystems/ext4/super.html).
- No destructive filesystem corruption, real failed hardware, uninterruptible
  kernel I/O or external SMTP provider was tested. Unsafe/corrupt-state and USB
  interruption paths have simulation coverage.
- Other distributions, rootless Docker, Docker Desktop, stacked/encrypted storage
  and a separate state filesystem were not qualified. Existing support limits
  remain in force. Enabled boot startup was exercised in the separate systemd
  container; the main VM's monitor was disabled across its incidental reboot.

No release-blocking defect remains in the verified scope. Publish only with
these limitations and the documented monitoring-first defaults; do not advertise
general physical USB reset compatibility.

## Final artifacts and VM state

- `dist/usb-storage-watch_1.0.0_all.deb`
- `dist/usb-storage-watch-1.0.0.tar.gz`
- `dist/SHA256SUMS`

Run `sha256sum -c SHA256SUMS` from `dist/`. Checksums are kept outside this report
to avoid a self-referential archive hash.

The final Debian package remains installed. The service is disabled/stopped with
a monitoring-only configuration, all optional actions and notifications off,
and an empty delivery queue. The verified USB drive remains normally mounted
with its disposable test data; no loop image remains attached. Dummy containers,
the temporary SMTP listener and its temporary system trust anchor were removed
or stopped. The portable test machine is powered off. Private evidence and
backups are retained in `/var/tmp/usw-validation` and
`/var/tmp/usw-validation-logs`; these directories are not release payloads.
