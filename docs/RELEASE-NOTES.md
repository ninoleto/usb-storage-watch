# USB Storage Watch 2.0.1 RC1

**Release candidate undergoing further reliability testing.**
Application version: `2.0.1-rc.1`. Tag: `v2.0.1-rc.1`.
Debian version: `2.0.1~rc.1`.

This promotion preserves the Beta 6 implementation at commit
`b06286f72f25744cd91331b3bd28918d69b5d0fd`. It changes version identification,
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
functionality. This is reported **Beta 6** hardware testing. No new physical RC1
test is claimed.

**Previous ZORIN tests experienced serious mount recovery difficulties.**
This successful result does not erase those failures or guarantee future recovery.

Earlier versions were also tested successfully on **Ubuntu Studio 26.04.1** with
different storage devices. That historical evidence does **not** verify the exact
RC1 build on Ubuntu Studio.

## What changed

- One authoritative version in `settings.py` supplies API/CLI identity, rendered
  dashboard title/footer and build metadata.
- Corrected the hard-coded “Beta 5 · TEST BUILD” footer present in Beta 6.
  Responses already use `Cache-Control: no-store`; reload after upgrading.
- Public version `2.0.1-rc.1`; Debian ordering uses `2.0.1~rc.1`.
- Rewritten README, upgrade/maintenance instructions, evidence and limitations.
  Historical tests and contributor instructions are preserved.
- Improved exclusions for local caches, reports and build artifacts.

Storage monitoring, recovery, filesystem/image verification, Docker dependencies
and stop/start order, email, LAN/authentication, configuration persistence and UI
controls retain the Beta 6 implementation. Companion 0.2.6 is unchanged.

## Downloads and installation

- `usb-storage-watch_2.0.1-rc.1_all.deb` — Debian-family installer.
- `usb-storage-watch-2.0.1-rc.1.tar.gz` — portable source/installer and tests.
- `usb-storage-watch-companion-0.2.6.tgz` — unchanged optional Companion module.
- `RELEASE-NOTES.md` — these notes.
- `SHA256SUMS` — SHA-256 checksums for all four files above.

Download all five into one directory, then:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-rc.1_all.deb
```

Fresh installations leave drive monitoring/recovery and LAN access unconfigured.
See the [README](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.1-rc.1/README.md)
for dependencies, initial setup and security.
For Beta 6, follow the
[upgrade procedure](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.1-rc.1/docs/UPGRADING-RC1.md);
retain a local Beta 6 rollback package because historical release downloads may
be removed. Publication does not upgrade the production installation.

## Validation and remaining limits

See [RC1 validation](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.1-rc.1/docs/VALIDATION-CURRENT.md)
for exact completed checks, environment blockers and tests not performed.
The 184 focused core/standby/storage/distribution checks, packaged identity/API
checks, 11 isolated installer checks and private-root Beta 6 upgrade/rollback
passed. The full suite did not pass: 1,352 tests ran with 100 errors and 24 skips.
Missing Compose/browser dependencies, sandbox socket restrictions and inherited
fixtures are documented; representative failures also reproduce on Beta 6.
Systemd/browser/TLS validation and deployed-source verification remain incomplete.
Simulated recovery and isolated installer tests do not establish hardware reliability.
No production USB reset, forced unmount, filesystem repair or automated ZORIN
upgrade is part of this release preparation. Packages are unsigned.

Mounted HDD standby/wake behavior, live I/O attribution on individual adapters,
external-hub electrical control, arbitrary native consumers and different
distribution/architecture combinations still require operator validation.
The historical Companion HTTP 503 cause remains unresolved.
