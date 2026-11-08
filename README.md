# USB Storage Watch 2.0.1 RC1

USB Storage Watch monitors removable ext4 filesystems on Linux. It can recover a
returned USB disk, verify required storage, restore selected virtual disk images,
and restart explicitly selected Docker containers. A local web dashboard and CLI
provide configuration, monitoring, diagnostics and email notifications.

**Version `2.0.1-rc.1` is a release candidate undergoing further reliability testing.**
It preserves the Beta 6 recovery implementation. RC1 changes release identity,
packaging metadata and documentation; it adds no recovery features.

## Hardware Compatibility and Testing

USB Storage Watch is developed and tested primarily on hardware owned by the maintainer. Successful operation has been confirmed on the documented test systems, but compatibility with other Linux distributions, kernels, USB controllers, storage adapters and hardware configurations is not guaranteed.

Automatic recovery depends on hardware capabilities and the operating system's ability to reset USB devices, remount filesystems and restore dependent services.

The software is provided as-is. Users should test recovery procedures on their own equipment before relying on them to protect production services or important data.

- Some USB controllers cannot electrically power-cycle individual ports. Software
  reconnect or device reset does not prove electrical power removal.
- Some filesystem errors require manual intervention or reboot. Recovery does
  not run filesystem repairs or reboot the host.
- Busy mounts and uncertain device identity can prevent safe recovery.
- Recovery does not guarantee protection against data loss. Maintain independent backups.
- Docker services should restart only after their required storage is verified.
  Configure every required disk/image explicitly.
- Different Linux environments may behave differently. This is not a claim of
  universal compatibility or production-grade reliability.

### Documented hardware testing

On **November 8, 2026**, the maintainer reported a successful **Beta 6** recovery
on **Zorin OS 18.1**, an **Intel N97 mini PC**, and an external **Hitachi USB hard
drive with ext4**, supporting Docker containers and dependent virtual images.
After a host reboot, a physical USB cable disconnection and reconnection recovered
automatically on **Attempt 1**, in approximately **1 minute 52 seconds**.

The main ext4 filesystem was restored and verified, including UUID, filesystem
type and read/write flags. The dependent virtual image was restored; Erugo, Plex,
Immich and PhotoPrism restarted; container verification checks passed; and the
maintainer manually confirmed application functionality. This is maintainer-reported
hardware evidence, not a new physical test performed during RC1 packaging.

**Earlier ZORIN tests encountered serious mount recovery difficulties.** The
successful Beta 6 result does not mean every recovery attempt has succeeded or
that every future incident will recover.

Earlier versions were also tested successfully on **Ubuntu Studio 26.04.1** with
different storage devices. Those results are historical; they do **not** establish
that the exact RC1 build was tested there. See
[current validation and limits](docs/VALIDATION-CURRENT.md).

## Requirements and architectures

- A systemd Linux host with Python 3.10+, systemd 249+, util-linux 2.37+, udev,
  ext4 utilities and the dependencies in [package metadata](packaging/control).
- The Debian package uses architecture `all`: Python and web assets, with no
  bundled native executable. Documented physical tests concern x86-64 systems.
  Other architectures, including ARM64, require suitable distribution packages
  and hardware validation; they have not been qualified.
- Zorin OS 18.1 and Ubuntu Studio 26.04.1 are the documented physical test
  environments. Earlier Ubuntu 24.04 VM results are historical. There is no
  fully tested distribution/kernel/controller compatibility matrix.
- Ordinary removable ext4 disks/partitions and configured ext4 loop images.
  Encrypted, RAID, LVM, network, FUSE and non-ext4 recovery are outside this scope.
  Storage paths with spaces are unsupported.
- Configuration and persistent state must reside on the writable internal root
  filesystem. Separate `/var`, network root and state on the watched disk are refused.
- Docker is optional and uses a local Unix socket. Containers are selected by
  exact identity; a recreated container requires explicit reselection.

## Main features

- Independent drive monitoring, durable incident history and bounded recovery.
- Filesystem UUID/type/mount/read-write verification before dependent startup.
- Optional USB reconnect/reset with identity, topology and storage-use guards.
- Optional virtual image recovery and independent Docker boot/recovery selections.
- Container stop/start sequencing, verification and respect for deliberate stops.
- Certificate-verified SMTP notifications and persistent incident-mail retries.
- Authenticated dashboard, optional LAN HTTP/HTTPS and persistent configuration.
- Guarded mounted HDD standby and measured container I/O diagnostics inherited
  from Beta 6; see [capabilities and limits](docs/HDD-STANDBY.md).
- Optional [Bitfocus Companion 0.2.6 integration](docs/COMPANION.md), unchanged.

## Installation

Download the Debian package, portable archive, Companion archive, release notes
and `SHA256SUMS` from the
[RC1 release](https://github.com/ninoleto/usb-storage-watch/releases/tag/v2.0.1-rc.1).
Verify the downloaded files in one directory:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-rc.1_all.deb
```

The Debian version is `2.0.1~rc.1`, which sorts above Beta 6 and below the eventual
`2.0.1`. The application/API version is `2.0.1-rc.1`.
Checksums detect changed bytes; these packages are unsigned.

A fresh installation enables the broker, localhost dashboard and boot coordinator
timer. **Drive monitoring, automatic recovery, automatic USB reset, Docker
startup/recovery and LAN access require explicit configuration.** The boot timer
starts no applications without saved startup selections. Do not run another
recovery monitor against the same disk.

Open **USB Storage Watch** from the application menu or
**http://localhost:8765**. On the application host, retrieve the unique management
token and paste it into the dashboard's **Management token** field:

```sh
sudo cat /var/lib/usb-storage-watch/management.token
```

Treat this token as a password. There is no shared default token.

### Portable installation and headless use

Install dependencies through your distribution first. Use one installation method
consistently; do not overlay the portable installer on a dpkg installation.

```sh
tar -xzf usb-storage-watch-2.0.1-rc.1.tar.gz
cd usb-storage-watch-2.0.1-rc.1
sudo python3 tools/install.py
```

For portable headless use, add `--headless`. For Debian headless use:

```sh
sudo env USB_STORAGE_WATCH_HEADLESS=1 apt install ./usb-storage-watch_2.0.1-rc.1_all.deb
sudo usb-storage-watch setup
sudo usb-storage-watch validate
sudo usb-storage-watch diagnose
```

The package contains a pinned Gunicorn server and downloads no Python code during
installation. The CLI setup wizard does not format, mount, unmount or repair disks.

## Upgrade from Beta 6

Use the [Beta 6 → RC1 upgrade procedure](docs/UPGRADING-RC1.md). It verifies the
package, retains the Beta 6 installer, prepares existing services for maintenance,
privately backs up configuration/state/code, and installs through APT.
Run it only when no recovery, storage/app operation or network confirmation is
pending. Publication does not upgrade any installed host.

Existing configuration, credentials, images, Docker selections, incident receipts
and queued mail are preserved. No configuration migration or recovery-policy
change is part of RC1. Sign in again after services restart and reload the page
to obtain **USB Storage Watch 2.0.1 RC1**.

## Initial configuration

1. Register the intended disk by verified identity and keep its usable mount
   location. Review filesystem UUID and mount status.
2. Register only needed virtual images. Ordinary bind-mounted data folders
   require no virtual image. See [existing-image handover](docs/EXISTING-IMAGE.md).
3. Start monitoring, then explicitly enable desired recovery options in
   **Manage Drive**. Monitoring and automatic recovery are separate choices.
4. Configure SMTP in **Email & Notifications**, send a test, and separately
   enable each drive's email notifications.
5. In **Docker Apps**, select exact containers and their required disks/images.
   Review startup, recovery and restart-policy settings independently.

The separate **Prepare drive** workflow can erase an explicitly confirmed unused
USB disk to create ext4. Formatting is never automatic recovery. It has disposable
virtual-disk coverage, not broad physical-drive acceptance.
See [web setup](docs/WEB-GUI.md) and [configuration](docs/CONFIGURATION.md).

## Monitoring and recovery

Defaults are 15-second samples, two bad observations, a 15-second recovery wait,
one mount attempt and a five-minute drive-return timeout. Upgrades preserve saved
timings. Selected dependent containers begin stopping at the first bad observation.
Recovery verifies their stopped state before storage cleanup.

Only proven owned stale mounts are ordinarily unmounted, with images handled
before their backing filesystem. A returned disk is identified by UUID and live
device identity, including changed device names. Normal ext4 mounting can include
journal replay; filesystem repair is never automatic. Wrong identities, unsafe
filesystems, busy/unknown mounts and uncertain actions remain blockers.

Selected images are mounted and verified after their backing filesystem.
Containers start only after required storage is verified, followed by container
verification and the configured notification. A drive-return timeout retains
incident evidence for later guarded recovery; it does not erase retry/reset budgets.

Manual USB reset requires all relevant storage to be unmounted and leaves it
unmounted. Guards apply in the backend as well as the UI. Depending on verified
capabilities, a guarded port reconnect or storage-only leaf-device reset may be
available. Neither resets an entire controller nor proves electrical power cycling.
See [recovery details](docs/RECOVERY.md).

## Docker integration and virtual images

Boot startup and outage recovery have separate disk/image selections. USW requires
Docker restart policy `no` when it owns startup; reviewed policy/Compose changes
target only the selected container/service. Unsupported or ambiguous deployment
management requires manual coordination. See [Docker setup](docs/DOCKER-SETUP.md).

Manual Start/Restart verifies saved required storage, including choices retained
while automatic startup/recovery is off. It does not mount missing storage.
Safe unmount stops and verifies selected dependent apps. Mounting storage again
does not automatically restart deliberately stopped apps.

Configured healthchecks must pass; containers without healthchecks get runtime
verification. Direct Docker starts do not execute Compose dependency ordering.
USW is not an application-crash watchdog. Native services and external managers
need separate coordination; optional post-recovery systemd restarts do not provide
pre-unmount shutdown or boot storage gating.

Virtual images are optional ext4 filesystems backed by registered files. Recovery
checks their backing filesystem, identity and mount before dependent apps start.
Selections and monitoring settings are retained across upgrades.

## Email notifications

SMTP supports authenticated STARTTLS or implicit TLS with certificate verification.
Plaintext SMTP and disabled TLS verification are unsupported. Credentials stay on
the target host. Use the dashboard test or:

```sh
sudo usb-storage-watch test-email
```

SMTP acceptance is not proof of inbox delivery. Check the inbox/spam folder.
Incident notifications use a durable retry queue; a manual test is sent once.
An uncertain SMTP response can result in duplicate delivery.

## LAN access and security

Localhost is independent of optional LAN access, which starts disabled. Automatic
network selection chooses an eligible physical interface; VPN/virtual interfaces
require explicit Manual selection. Configure access in **Advanced Settings** and
complete the displayed exact-address confirmation.

Use HTTPS for LAN access and verify/trust the displayed host CA. HTTP sends the
management token without encryption. Do not expose the interface through public
port forwarding. Keep tokens, SMTP credentials and TLS private keys out of reports.
Backend authorization, CSRF protection, operation locks and identity checks also
apply to integrations.

Local token recovery requires a named local administrator; Linux-password recovery
is unavailable over LAN. Replacing the token revokes old sessions/tokens.
See [the web guide](docs/WEB-GUI.md) for certificate handling.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Monitoring off after fresh install | Register/configure the disk and explicitly start monitoring. |
| Filesystem cannot recover | Check UUID, ext4 type, read/write flags, live users and the refusal reason. Some failures need administrator repair or reboot. |
| Container stays stopped | Verify selected storage, healthchecks, deliberate-stop holds and exact identity. |
| USB reset unavailable | Mounted/busy storage, unsupported port control or unverified identity can prevent reset. |
| HDD standby refused/unverified | Inspect measured activity and adapter capabilities; unavailable metrics are not zero activity. |
| Beta 5 label after upgrade | Beta 6 embedded that stale label. Verify CLI/package versions, reload and check that the new web service is running. Responses use `Cache-Control: no-store`. |
| LAN access fails | Check saved address/interface, confirmation and CA trust; do not disable certificate verification. |
| Email missing | Check SMTP/TLS, provider restrictions and spam; server acceptance differs from delivery. |

```sh
usb-storage-watch --version
sudo usb-storage-watch diagnose
sudo usb-storage-watch status
systemctl --no-pager --full list-units --all 'usb-storage-watch*.service'
sudo journalctl -u usb-storage-watch-broker.service -n 100 --no-pager
```

Per-drive monitoring uses `usb-storage-watch@PROFILE_ID.service`; the original
profile uses `usb-storage-watch.service`. Select the applicable unit for its
journal. Diagnostics can contain private identities: redact before sharing.
Never delete incident receipts or bypass refusal guards to force recovery.

## Uninstallation

```sh
sudo apt remove usb-storage-watch
# Portable installations: from the corresponding extracted archive
sudo python3 tools/install.py --uninstall
```

Use only the command for your installation method. Removal stops this application's
services and removes its program files. It does not remove watched data, virtual
images, Docker containers or fstab entries. Generated configuration, credentials,
history and safety records remain, including after Debian purge. Unresolved USB
re-enable obligations can block removal; keep helpers and state intact.
See [maintenance](docs/MAINTENANCE.md) before manually deleting private state.

## Source, tests and license

[Contributor instructions](AGENTS.md), [documentation index](docs/README.md) and
[validation](docs/VALIDATION-CURRENT.md) describe changes and evidence.
Historical DEV/UI/Beta reports are not current installation instructions.

```sh
make test
make build
python3 -B -I tools/integration_test.py --smoke-only
make audit
```

Tests use isolated fixtures; browser/TLS checks require their documented dependencies
and permission to bind localhost sockets. Do not run hardware tests on production.
Build outputs and private evidence are excluded from Git.

License: [MIT](LICENSE). Bundled components retain their
[third-party notices](THIRD-PARTY-NOTICES.md).
