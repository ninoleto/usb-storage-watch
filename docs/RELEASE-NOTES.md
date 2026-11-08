# USB Storage Watch 2.0.2

**Regular release with documented hardware and testing limitations.**
Application version: `2.0.2`. Tag: `v2.0.2`.
Debian version: `2.0.2`.

This release preserves the proven Beta 6 recovery behavior. It changes version identification,
packaging metadata and documentation. No recovery features, configuration migration,
dependency upgrades or recovery-engine refactoring are included.

## Hardware Compatibility and Testing

USB Storage Watch is developed and tested primarily on hardware owned by the maintainer. Successful operation has been confirmed on the documented test systems, but compatibility with other Linux distributions, kernels, USB controllers, storage adapters and hardware configurations is not guaranteed.

Automatic recovery depends on hardware capabilities and the operating system's ability to reset USB devices, remount filesystems and restore dependent services.

The software is provided as-is. Users should test recovery procedures on their own equipment before relying on them to protect production services or important data.

Some USB controllers cannot electrically power-cycle individual ports. Software
reset/reconnect does not establish electrical power removal. Some filesystem
errors require manual intervention or reboot, and busy mounts can prevent safe
recovery. Recovery does not guarantee protection against data loss. Docker
services should restart only after their required storage is verified.
Different Linux environments may behave differently. Universal compatibility and
production-grade reliability are not claimed.

### Maintainer's ZORIN test — November 8, 2026

Zorin OS 18.1; Intel N97 mini PC; external Hitachi USB hard drive; ext4; Docker
containers and dependent virtual images. Following a host reboot, physical USB
cable disconnection and reconnection recovered automatically on **Attempt 1** in
approximately **1 minute 52 seconds**.

The maintainer confirmed main ext4 restoration; UUID, filesystem type and
read/write flags; dependent virtual-image restoration; restart of Erugo, Plex,
Immich and PhotoPrism; passing container verification; and manual application
functionality. This is reported **Beta 6** hardware testing. No new physical 2.0.2
test is claimed.

**Previous ZORIN tests experienced serious mount recovery difficulties.**
This successful result does not erase those failures or guarantee future recovery.

Earlier versions were also tested successfully on **Ubuntu Studio 26.04.1** with
different storage devices. That historical evidence does **not** verify the exact
2.0.2 build on Ubuntu Studio.

## What changed

- One authoritative version in `settings.py` supplies API/CLI identity, rendered
  dashboard title/footer and build metadata.
- Corrected the hard-coded “Beta 5 · TEST BUILD” footer present in Beta 6.
  Responses already use `Cache-Control: no-store`; reload after upgrading.
- Application, API and Debian version `2.0.2`; display **USB Storage Watch 2.0.2**.
- Rewritten README, upgrade/maintenance instructions, evidence and limitations.
  Historical tests and contributor instructions are preserved.
- Improved exclusions for local caches, reports and build artifacts.

Storage monitoring, recovery, filesystem/image verification, Docker dependencies
and stop/start order, email, LAN/authentication, configuration persistence and UI
controls retain the Beta 6 implementation. Companion 0.2.6 is unchanged.

## Downloads and installation

- `usb-storage-watch_2.0.2_all.deb` — Debian-family installer.
- `usb-storage-watch-2.0.2.tar.gz` — portable source/installer and tests.
- `usb-storage-watch-companion-0.2.6.tgz` — unchanged optional Companion module.
- `RELEASE-NOTES.md` — these notes.
- `SHA256SUMS` — SHA-256 checksums for all four files above.

Download all five into one directory, then:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.2_all.deb
```

Fresh installations leave drive monitoring/recovery and LAN access unconfigured.
See the [README](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.2/README.md)
for dependencies, initial setup and security.
For Beta 6, follow the
[upgrade procedure](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.2/docs/UPGRADING.md);
retain a local Beta 6 rollback package because historical release downloads may
be removed. Publication does not upgrade the production installation.

## Validation and remaining limits

See [2.0.2 validation](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.2/docs/VALIDATION-CURRENT.md)
for exact completed checks, environment blockers and tests not performed.
Earlier preparation passed 184 focused checks, package identity checks and 11
isolated installer checks. Its full suite was **not green**: 1,352 tests ran with
100 errors and 24 skips. Missing trusted Compose/browser dependencies, sandbox
socket restrictions and inherited fixtures are documented; representative failures
also reproduce on Beta 6. Those earlier results are not a fresh 2.0.2 full-suite
pass.

The rebuilt 2.0.2 packages passed **194 focused checks**, packaged UI/API/CLI
identity checks, **11 isolated installer checks**, and private-root Beta 6 upgrade
and rollback. The final systemd verifier remains blocked by sandbox socket
permissions. Source/package contents, privacy and SHA-256 checks were verified.
The full suite was not rerun for this version/documentation-only change.

The maintainer's read-only 117-file ZORIN fingerprint exactly matches the preserved
Beta 6 source. No new physical 2.0.2 acceptance, unrestricted browser/TLS/systemd
verification or extensive Linux distribution testing is claimed.
Simulated recovery and isolated installer tests do not establish hardware reliability.
No production USB reset, forced unmount, filesystem repair or automated ZORIN
upgrade is part of this release preparation. Packages are unsigned.

Mounted HDD standby/wake behavior, live I/O attribution on individual adapters,
external-hub electrical control, arbitrary native consumers and different
distribution/architecture combinations still require operator validation.
The historical Companion HTTP 503 cause remains unresolved.
