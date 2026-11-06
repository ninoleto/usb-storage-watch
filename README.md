# USB Storage Watch 2.0.1 beta 1 — beta candidate

Removable ext4 storage monitoring, guarded recovery and explicitly selected Docker
application startup. Ordinary folders and optional virtual images are supported.
The prepared source is based on verified UI40; no public beta is released yet.

See [current validation and limits](docs/VALIDATION-CURRENT.md),
[release draft](docs/BETA-RELEASE-DRAFT.md), [existing-image handover](docs/EXISTING-IMAGE.md)
and [Companion 0.2.6](docs/COMPANION.md). Older UI/DEV reports are historical evidence.

Manual Start/Restart verifies every configured required filesystem/image before
Docker mutation. Startup and drive recovery remain independent. Safe unmount stops
selected dependent apps; remounting does not restart deliberately stopped apps.
The UI40 installer verifies old supervisor/listener/worker shutdown, including the
pre-unpack failed-upgrade fallback. All backend protections remain in force.

The separate [Prepare drive screen](docs/PREPARE-DRIVE.md) can erase an explicitly
confirmed, unused USB drive and create a mounted Linux ext4 filesystem. Formatting
is never part of automatic recovery. Disposable virtual-disk tests have passed;
physical-drive acceptance remains pending.

USB Storage Watch independently monitors multiple removable **ext4** filesystems and sends an email
when a confirmed outage reaches its final outcome. Optional recovery can mount a
returned filesystem, including ordinary ext4 journal replay, restore configured dependent ext4 loop images, reconnect an automatically verified isolated
USB root port, and stop/start selected Docker containers around drive recovery.

This distribution is derived from the working v3.2 recovery implementation.
It has its own service, configuration and sender. No original machine settings,
SMTP credentials, hardware qualification, incident history or queue are shipped.
Version 1.1 adds an authenticated local web dashboard while retaining the CLI
and the shared recovery engine, with corrected journal and nonempty-mountpoint
handling. It does not replace differently named monitors.

**Automatic mounting, USB resetting and Docker actions default off.** Manage Drive offers separate controls for monitoring and automatic recovery.
Both require an explicit user choice. You supply your own email account. Installation starts the optional localhost dashboard, but does not enable
the storage monitor or automatic recovery. Never run two recovery monitors on
the same disk. Keep a working existing installation separate from this package.

## Requirements and supported scope

- A systemd-based Linux host, Python 3.10 or newer, systemd 249 or newer,
  util-linux (`mount`, `blkid`, `losetup`), udev and trusted CA certificates.
- Ubuntu 24.04, Ubuntu Studio 26.04 and Zorin OS 18.1 are the initial targets.
  The package is architecture `all` (Python; no compiled binaries). Other
  distributions can use the portable installer if these paths and tools exist.
  Ubuntu 24.04 has been validated in a VMware guest, including the real systemd
  service, USB ext4 mounts, local TLS SMTP and Docker Engine 29.1.3. Other targets
  are compatibility requirements, **not a boot-tested distribution matrix**.
- Each normal ext4 disk or partition uses its own stable absolute path, such as
  `/mnt/storage`. Encrypted, RAID, LVM, network, FUSE and non-ext4 storage recovery
  are outside the supported scope. Paths containing spaces are not supported.
- Persistent state must reside on the writable internal root filesystem.
  Separate `/var`, network root and a state directory on the watched disk are
  deliberately refused. Automatic main mounts require protected directories on the internal root
  filesystem, or a protected desktop location under `/run/media` on the host
  `/run` tmpfs. Existing valid connection settings are preferred; their path
  alone does not require a location change.
- Docker is optional. Recovery supports an accessible local Unix socket and
  Linux containers selected explicitly in the dashboard.
  API version is configurable (default `v1.47`); select one supported by your
  daemon. Restart does not require shell utilities inside the container.
- Software USB reconnect requires an automatically verified direct PCI xHCI root
  port, isolated companion interface and a working per-port disable attribute.
  Hubs allow monitoring and ordinary mounts, but never port reconnect. Electrical
  power loss is not assumed from a software reconnect or a hardware descriptor.

## Install and open the dashboard

On Ubuntu 24.04, install the downloaded package:

```sh
sudo apt install ./usb-storage-watch_2.0.1~beta1_all.deb
```

A fresh installation enables the privileged broker, localhost dashboard and boot
coordinator timer. The timer starts no apps until startup is configured. Drive
monitoring and recovery remain opt-in; LAN access starts disabled.

Open **USB Storage Watch** from the applications menu, or **http://localhost:8765**.
The installer creates a unique management token. On the application computer,
retrieve it with:

```sh
sudo cat /var/lib/usb-storage-watch/management.token
```

The command may request your local administrator's sudo password. Copy the token,
paste it into **Management token**, then select **Connect**. The same token works
locally and over the existing optional LAN HTTP/HTTPS listeners. The file is
root-owned, mode `0600`, in the private application state directory.

A DEV6 upgrade adds this retrievable token without replacing the existing DEV6
credential. Both work during the transition. **Advanced → Management access →
Replace management token** explicitly retires all old tokens and signs out every
session. Existing package service restarts require signing in again.

If the file is lost, use **Additional setup and token recovery → Create or recover
a token** at localhost and authenticate with a named local administrator. This
explicit action regenerates the file and revokes earlier tokens/sessions. Linux
password recovery is unavailable over LAN. There is no default or shared token.

1. Select your USB drive by its name and capacity.
2. Choose **Automatic recovery**. Configure optional notifications separately in **Email**.
3. Read the short explanation and click **Start monitoring**.

Existing usable connection settings are kept. The Overview shows current drive
availability and monitoring status. Change mount location is on Manage Drive. Virtual Disk Images, Docker & Applications, Integrations and Advanced Settings have separate pages. Docker restart settings belong to each detected container; drive and image choices are made by the user. Remote image upload is not offered. See [the web guide](docs/WEB-GUI.md).

Existing 1.0 configuration, SMTP credentials, state and queued notifications are
preserved on upgrade. A running monitor resumes after package maintenance;
installing on a new machine never starts the monitor automatically.

For a headless installation, explicitly suppress GUI activation even when its
optional dependencies are already installed:

```sh
sudo env USB_STORAGE_WATCH_HEADLESS=1 apt install --no-install-recommends ./usb-storage-watch_2.0.1~beta1_all.deb
sudo usb-storage-watch setup
sudo usb-storage-watch validate
sudo usb-storage-watch diagnose
```

Use `sudo usb-storage-watch web-disable` or `web-enable` to change GUI enablement.
The Debian package now requires `python3-flask`, `python3-pam`, `python3-yaml`, `openssl`, `hdparm`, `acl` and `xdg-utils`. The package
includes a pinned Gunicorn server; it never downloads Python code during install.
The web UI is validated on Ubuntu 24.04. Other distributions remain unverified;
headless installations retain the documented core requirements.

A checksum detects accidental corruption; these locally built packages are not
signed or distributed through an authenticated repository. Only install a copy
from a source you trust.

The CLI setup utility lists eligible ext4 data disks with size, model, current
mountpoint and UUID. Disks containing the system root, boot, `/usr` or `/var`
mount are excluded. Confirm the intended data disk. A UUID identifies a
filesystem even when names such as `/dev/sdb1` change. The mountpoint is the
folder where that disk normally appears. Use a stable mount configured by your
system administrator, not a temporary desktop automount under `/media`.

The CLI wizard asks about email, normal mounts, an optional loop filesystem and
individual Docker containers. Answer **no** to recovery questions to start with
monitoring only. It never formats, mounts, unmounts, repairs or tests USB resets.
It does not edit `/etc/fstab`. See [configuration](docs/CONFIGURATION.md) before
enabling any recovery option.

Automatic mounting permits ordinary ext4 journal replay and nonempty target
directories; underlying files are preserved. Recorded filesystem errors,
read-only devices, wrong identities and active mounts of the returned device in
other namespaces still prevent recovery. The monitor does not stop containers
to release storage or run filesystem repair. See the
[final recovery validation](docs/FINAL-VALIDATION.md) and
[recovery behavior](docs/RECOVERY.md).

## Install the portable archive

```sh
tar -xzf usb-storage-watch-2.0.0~ui5.tar.gz
cd usb-storage-watch-2.0.0~ui5
sudo python3 tools/install.py
```

Install the dependencies through your Linux distribution first, including the
optional GUI dependencies if wanted. Open http://localhost:8765 after installation,
or use `--headless` and the existing CLI setup. Choose either
the Debian package or the portable installer, and keep that choice for upgrades.
Do not overlay a portable installation on a dpkg-managed installation.
The archive includes the complete source, tests, package builder and maintenance
utilities; it is suitable as the starting point for a public source repository.

## Configure and test email

The sender is independent of any web application or existing notification tool.
It supports SMTP authentication with certificate-verified STARTTLS (usually
port 587) or implicit TLS (usually port 465). Plaintext SMTP and disabled
certificate verification are unsupported. Ask your email provider for the host,
port, username and password/app password; these are not always your usual login
settings. Passwords are entered without echo and saved only on the target host.

```sh
sudo usb-storage-watch test-email
```

This sends one clearly labelled test, never a simulated failure. Check both the
inbox and spam folder. “SMTP accepted” means the server accepted it, not that
inbox delivery is proven. A manually requested test has no persistent retry;
incident notifications do have a durable retry queue.

## Start, inspect and stop

After configuration, diagnostics and email testing succeed:

```sh
sudo systemctl enable --now usb-storage-watch.service
systemctl is-enabled usb-storage-watch.service
systemctl is-active usb-storage-watch.service
sudo usb-storage-watch --version
sudo usb-storage-watch check
sudo usb-storage-watch status
sudo journalctl -u usb-storage-watch.service -n 100 --no-pager
```

`status` includes persistent incident history and hardware identity. Treat it as
private before sharing. `check` reports current mount metadata; it does not prove
file integrity. `diagnose` checks configuration, state, dependencies and current
mount health without causing recovery. `verify-apps` checks configured Docker identities and runtime state; it never
restarts them. Docker storage detection is advisory.

```sh
sudo systemctl stop usb-storage-watch.service
sudo systemctl restart usb-storage-watch.service
sudo systemctl disable --now usb-storage-watch.service
```

Stopping/restarting preserves incidents and the email queue. A recorded pending
USB enable obligation is attempted during service start and stop. Monitoring
service startup alone does not start containers. The separate, default-off boot
startup option below can start explicitly selected containers after computer startup.

## Guided Docker setup

Docker & Applications shows current restart policy, identifiable deployment
manager, selected storage and conflicts. **Review Storage Watch management**
previews a policy-only change for the selected container; **Confirm policy setup**
sets Docker restart policy to `no` without recreating or restarting it. The
original policy is retained for restoration. A policy already set to `no` needs
no update. Your boot/recovery disk and image selections remain explicit.

For verified local Compose sources, review the selected-service change before
applying it. Source backups stay private, and effective configuration including
ordered overrides is validated. Ambiguous or externally managed deployments get
instructions rather than automatic edits. Live/source conflicts remain visible.
See [guided setup details and limitations](docs/UI26.md).

Ordinary external data folders are supported while application/Docker files stay
on SSD. Images are optional. Startup waits for the correct mounted filesystem,
not merely an existing directory. This manages computer startup and storage
recovery, not general application-crash restarts.

Manual app Start/Restart verifies every saved startup/recovery drive and selected
virtual image, including choices retained while automatic startup/recovery is off.
Monitoring may be off. Missing or unverifiable required storage refuses the command
before Docker is changed; no storage is mounted automatically. Stop does not require
ready storage. Apps without configured dependencies remain independently usable.

## Optional container boot startup

On Docker & Applications, enable **Start automatically when the computer starts** for a container
and explicitly choose its boot disks and optional images. These selections are
independent of recovery triggers and work with monitoring off. Disk-only upload
folders are supported. No recovery selection is copied or removed. A container
must use Docker restart policy `no` so only one component owns startup.

The boot coordinator waits for Docker, verifies disk identity, mounts and verifies
all selected prerequisites, then starts and verifies the container. A missing
selected disk delays startup even when its monitoring is off. Unselected recovery
disks/images do not become boot prerequisites. Already-running containers are
verified without remounting underneath them. Existing configured healthchecks
must pass; containers without one receive runtime-state verification only.

Startup is attempted once per host boot, including when the container was stopped
before reboot. Later manual stops are respected; Stop in this dashboard also
cancels a pending boot start for the current boot. Enabling the option schedules
it during the current boot as well. Durable receipts reconcile interrupted work
without blindly repeating mounts or starts. Storage and container locks coordinate
startup with recovery. Configured email is sent after verification; acceptance
does not prove inbox delivery. See [UI25 validation and limits](docs/UI25.md).

## Recovery and safety

Default timing is a sample every 15 seconds, two consecutive observations, and
a configurable 15-second recovery wait. Upgrades retain configured timings.
Selected containers begin stopping at the first bad observation, before the
recovery wait. An absent disk is awaited; waiting alone does not consume a normal
mount attempt. A verified returned disk may use a different USB port/device name.
Only proven owned stale mounts may be normally unmounted, with managed image
mounts handled before their parent. Unknown/busy mounts remain refused.
After the disk and explicitly selected images are mounted, the containers start.

Each drive's Manage Drive page includes Mount, Unmount safely, Reset USB
and supported HDD standby controls. Safe unmount stops only that drive's monitoring. Standby uses
`hdparm -y`, kernel I/O counters, active-user and Docker checks, and write flushing.
Routine status checks do not open filesystem contents or issue disk power probes.
Docker restart choices are on the container-first Docker & Applications page.
Image mounts, timings and USB diagnostics have their own controls. Global Advanced contains management and network access.
Manual USB reset requires all relevant storage to be unmounted and leaves it
unmounted. Mounted storage disables the button and is also rejected by the server
before side effects. Refusal does not pause monitoring. Current topology, bus/device
address, VID:PID and available serial are shown; cached information is labelled.
Where supported, reset uses the guarded individual port reconnect. Otherwise a
verified, storage-only leaf device may support Linux USB device reset, including
behind an external hub without resetting that hub. Unsupported capabilities are
reported separately from failed operations. Neither method proves electrical
power removal; no second method is attempted after an operation fails.
The dedicated Bitfocus Companion module provides live state and guarded actions
using dashboard sessions and the existing management token; see [brief setup instructions](docs/COMPANION.md). The menu launcher follows the saved localhost port (8765 by default).

Every action needs explicit configuration and runtime proof. USB reset has an
absolute one-attempt budget per outage, saved before I/O. No controller-wide
reset, shared-hub operation, forced mount, repair, read/write remount of an
unsafe filesystem, reboot, Docker daemon restart or unrelated container action
is performed. See [the full recovery sequence](docs/RECOVERY.md).

One final outcome event per incident reports natural return, successful automatic
recovery and attempt number, partial recovery or manual intervention. Selected
Docker results and USB reset details are included. Delivery retries reuse the
same event ID. SMTP cannot guarantee exactly-once inbox delivery if the server
accepted a message just before the connection/process failed.

## Maintenance, troubleshooting and development

- [Web dashboard and beginner setup](docs/WEB-GUI.md)
- [GUI VM validation report](docs/GUI-VALIDATION.md)
- [Physical reconnect investigation and final results](docs/RECONNECT-INVESTIGATION.md)
- [Storage, failure, installer and security validation](docs/FINAL-VALIDATION.md)
- [All settings, SMTP permissions, fstab and Docker setup](docs/CONFIGURATION.md)
- [USB diagnostics and limitations](docs/USB-QUALIFICATION.md)
- [Recovery behavior and crash handling](docs/RECOVERY.md)
- [Upgrade, removal, troubleshooting and disabling recovery](docs/MAINTENANCE.md)
- [Isolated test instructions and validation scope](docs/TESTING.md)
- [Dependencies and notices](THIRD-PARTY-NOTICES.md)

```sh
make test
make build
make integration
```

Tests simulate disks, USB I/O, Docker and SMTP. Integration tests install into a
private temporary filesystem/dpkg database and never start a host service.
The [current validation report](docs/VALIDATION-CURRENT.md) separately records tests of the
installed service, real storage, notifications, containers and installers.
Build outputs go into `dist/`. No command in this project publishes source or
creates an online release. License: [MIT](LICENSE).


USB-to-SATA ATA-pass-through support in UI6: see [test notes](docs/UI6-USB-SATA-TEST-NOTES.md).

UI7 reconnect feedback and bounded inspection: see [test notes](docs/UI7-RECONNECT-TEST-NOTES.md).
