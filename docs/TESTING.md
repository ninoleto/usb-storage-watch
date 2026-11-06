# Testing and validation scope

The automated unit and isolated package tests use synthetic identities and mocked devices, USB, Docker and
SMTP. No real disk is disconnected, mounted, unmounted or repaired. No real USB
reset, container restart, SMTP delivery or host service operation is part of the
suite. Current disposable-VM validation is recorded in
[FINAL-VALIDATION.md](FINAL-VALIDATION.md); [VALIDATION.md](VALIDATION.md) is the
historical 1.0 baseline.
The [reconnect investigation](RECONNECT-INVESTIGATION.md) records the final 322
test suite, discovered defects and repeated operator-performed physical USB and
Docker acceptance tests.
Do not use a production installation as a failure test environment.

```sh
python3 -B -I -m unittest discover -s tests
python3 -I tools/build.py
python3 -I tools/integration_test.py
python3 -I tools/privacy_scan.py
```

Build dependencies: `dpkg-deb` (dpkg), Python 3.10+, and for integration tests
`fakeroot`, `dpkg` and `systemd-analyze`. Tests run as an ordinary user. Fakeroot
uses `FAKEROOTDONTTRYCHOWN=1` to simulate ownership without attempting real chown. They use
temporary paths, a separate dpkg root/database/log and explicit `DPKG_ROOT`
maintainer-script guards. Dependencies are intentionally not installed inside the
synthetic dpkg root; dpkg's dependency checks are bypassed **only in that test**.
Do not copy the private-root dpkg flags into normal installation commands.

Coverage includes confirmed failure and timing, persistent restart state,
natural return, successful/failed guarded mounts, wrong UUID/type, read-only or
unclean nonjournaled/ext4-error state, normal journal replay, nonempty targets,
active namespace/exclusive-device refusal, dependent image failure, USB qualification/topology,
one-reset budget, one-second disable, early enumeration and 20-second timeout,
second-wait return, failed re-enable, interrupted reset cleanup, configuration
changes, Docker running/stopped/unknown snapshots, API failure/timeouts,
per-container durable intent, interrupted verification, no repeated restart,
storage loss during application work, SMTP TLS and durable queue behavior.

Packaging tests cover portable install/upgrade/uninstall, .deb install/version
upgrade/remove/purge, preservation of synthetic credentials/history, safe paths,
no automatic activation, unresolved USB cleanup refusal, staged CLI diagnostics,
static systemd validation and running simulations from the extracted archive.

The source/privacy audit checks source and unpacked package members for secret
patterns, real user-home paths, unexpected addresses/UUIDs, binary payloads,
private runtime files and unqualified shipped defaults. Builder uses an explicit
allowlist, excludes caches/logs/runtime files, normalizes owners/timestamps, and
creates SHA256SUMS. Only reserved example addresses and synthetic test identities
are expected. Additional comparison against the origin machine's private values
must stay outside the distribution; never add a private denylist to public code.

## Validation limits

The isolated integration test remains a private **installation filesystem and
dpkg database**, not a running guest Linux system. The additional Ubuntu 24.04
VM tests exercise the installed systemd service and real ext4 storage, local
authenticated TLS SMTP and rootful Docker. Portable installation is also tested
inside a separate booted Ubuntu systemd container. These are distinct results;
neither simulation nor container boot establishes physical USB compatibility.

USB controller fixtures are entirely synthetic, including driver resolution.
The regression suite was also run with `/sys` hidden inside a private mount
namespace to verify that it no longer requires the host's xHCI driver directory.
Do not hide or replace the host's real `/sys` to run a test.

Physical cable/power faults, qualified electrical port reset, real provider inbox
delivery and other distribution boots remain outside the verified matrix.
VMware storage-driver detach/rebind emulates block-device disappearance; it is
not a physical USB reset qualification.

Before relying on optional recovery on a new host, use monitoring-only mode,
review diagnostics, verify a real test email yourself, inspect normal mounts and
container binds, and perform independent USB qualification only during a safely
planned offline maintenance procedure. Keep resets off when isolation is unclear.
The release is unsigned and has not been published online.

## GUI validation

`tests/test_web.py` covers PAM/session boundaries, CSRF and origin enforcement,
request size and host restrictions, disk eligibility, write-only SMTP settings,
stale edits, explicit recovery confirmations, Docker bind selection, TLS
validation, history retention and GUI lifecycle. HTTP tests require the optional
Flask package; they are explicitly skipped on a minimal headless test host.

The pinned upstream server is verified against `tools/vendor-lock.json` during
every build. Privacy audit permits upstream contact/license text only when the
complete file matches the reviewed bytes; private-origin checks still apply.
Do not edit vendored code. Review a new upstream release and regenerate the
manifest as a deliberate dependency update. No installer downloads Python code.

The separate [GUI VM report](GUI-VALIDATION.md) records actual browser, HTTPS,
PAM, SMTP, Docker, USB recovery, lifecycle and accessibility checks. Playwright
and axe are development-only tools and are not required on an installed system.

## Basic setup and Advanced regression tests

RC3 replaces the basic wizard with a single setup screen. `tests/test_gui.py`
exercises drive selection, automatic recovery, optional email and one activation,
with both new drives and existing desktop-path permanent entries. It asserts
that ordinary setup and overview omit technical storage terminology, focuses
the specific invalid email field, tests a useful monitoring-only fallback,
checks mobile layout and verifies the live service banner.

`tests/test_protection.py` covers identity/readiness checks, explicit consent,
stale plans, private backups, rollback, concurrent edits, startup failures and
authenticated endpoints. `tests/test_mount_directory.py` exercises real directory
descriptor walks in private trees plus root/tmpfs mount metadata. Recovery-worker
tests cover guarded ordinary mounts at desktop paths and unsafe-parent refusal.

`tests/test_setup.py` tests consent-bound mount proposals, read-only validation,
existing-entry preservation, changed proposals, desktop conflicts, nonempty and
symlink targets, virtualization results and rollback. `tests/test_gui_advanced.py` drives
real Chromium through login, clean setup, error correction, consent, desktop
transition, Review, Save, Enable and accurate status. It also covers disabled
Docker, physical/virtual/unknown explanations, topology refusals and banners.

Development-only browser checks (Flask, Playwright and its Chromium required):

```sh
.venv/bin/python -B -I -m unittest discover -s tests
python3 -I tools/build.py
.venv/bin/python -I tools/gui_test.py
```

`tools/gui_test.py` installs the actual candidate deb into a clean private dpkg
root and runs the browser tests against its installed code/assets. It fails if
browser dependencies are absent. The ordinary headless suite explicitly skips
browser tests when Playwright is unavailable. `tests/gui_fixture.py` redirects
PAM authentication, systemd operations, discovery and mount observations to
isolated fixtures; actual HTTP, session/CSRF checks, validation, config writes
and mount-table writes run. No fixture configuration is shipped as a default.
This establishes browser and broker workflow behavior, not a booted OS, real
UDisks transition or physical hardware compatibility. The actual Ubuntu Studio
fresh-install test remains pending; see SIMPLE-SETUP-RC3-VALIDATION.md.

To repeat an exact reported upgrade identity without publishing user-specific
values, pass `--fixture /path/to/private-fixture.json` to `tools/gui_test.py`.
The private file contains `uuid` and `mountpoint` strings and stays outside the
distribution. Both basic and Advanced browser suites run with those values.
The real report's filesystem type, options and final `0 0` fields are in the
regression fixture. This tests the actual configuration text, with synthetic
OS observations; it is not a remote or physical-machine test.

## RC2 existing-entry migration and USB peers

The RC1 report is historical: the real Ubuntu Studio workflow exposed an
existing UUID entry under a desktop path that the clean fixture did not cover.
`tests/test_migration.py` now covers that exact entry shape using a synthetic
identity, including keep-existing, migration, live-mount refusal, saved config
and state, private backup, interruption, rollback, concurrent/unrelated edits,
retained notifications/budgets, active monitoring, Docker paths and formatting.
`tests/test_usb_peers.py` reads synthetic sysfs trees for normal USB2/USB3 peers,
dangling/nonreciprocal mappings, distinct controllers, hubs, wrong speeds,
missing controls and occupied peers. No real USB write is performed or enabled.
The Chromium suite additionally covers the legacy-entry keep/migrate flows,
missing migration consent, browser restart/resume and absent-disk rollback.
See MIGRATION-RC2-VALIDATION.md for exact evidence and physical-test limits.
