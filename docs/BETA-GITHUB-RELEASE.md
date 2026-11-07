# USB Storage Watch 2.0.1 Beta 2

Testing prerelease for systemd Linux hosts with removable ext4 storage and
explicitly selected Docker apps. Ordinary external folders need no virtual image.

This release fixes two Beta 1 setup blockers:

- **First-time HTTPS:** a missing saved certificate no longer prevents probing the
  proposed HTTPS listener. Certificate-chain/hostname verification, exact listener
  and certificate checks, authenticated confirmation and rollback remain enforced.
  The GUI distinguishes preparing, ready for confirmation and failed states.
- **Existing mounted images:** GUI review can adopt a verified ext4 fstab loop image
  using its current backing file, filesystem UUID and mountpoint. Confirmation
  rechecks physical/loop identity and operation locks, saves only configuration,
  and preserves mount, fstab/options, data, ownership and permissions. No unmount,
  formatting, data copying or FTP stop is needed. Conflicts are refused; repeated
  adoption preserves saved choices. See [existing-image guidance](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.1-beta.2/docs/EXISTING-IMAGE.md).

Companion **0.2.6** is unchanged. Existing controls and buttons need no replacement.
Boot/recovery behavior, authentication and manual app storage protections remain.
Beta 1's tag and assets are retained.

## Install or upgrade

Download all three package assets and `SHA256SUMS` into one folder, then verify:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-beta2_all.deb
```

The package's Debian version is **2.0.1~beta2**, which upgrades **2.0.1~beta1**.
Public filenames use a hyphen so GitHub preserves the checksum manifest's names.
The source archive is `usb-storage-watch-2.0.1-beta2.tar.gz`; build with
`python3 -B tools/build.py` from its extracted root. Install the built Debian package
with apt to resolve distribution dependencies. See README for portable installation.
Packages are unsigned; checksums verify bytes, not publisher signatures.

Privately back up settings/state and coordinate previous storage automation first.
Install while storage/recovery is idle; the installer refuses unsafe upgrades.
Fresh installs enable the broker, localhost dashboard and boot coordinator timer.
LAN listening starts disabled; monitoring, recovery and app startup require GUI
configuration. Open `http://localhost:8765`, retrieve the management token using
the dashboard instructions, and configure network/image settings there. An upgrade
preserves existing configuration, credentials and intended service enablement.
Do not run competing recovery owners. Image adoption does not disable another
watcher or add app dependencies automatically.

## Validation and limits

Beta 1's fresh HTTPS failure was reproduced. Beta 2 tests include real verified
loopback TLS, HTTP-to-HTTPS confirmation/rollback and certificate/hostname refusal;
disposable ext4 files with real probes/configuration locks and simulated kernel
mount/loop/service observations; focused Chromium checks at desktop/tablet/mobile
sizes; and fresh/upgrade installation in private package roots. Python 3.12 with
Flask 3.0.2 is covered. These are isolated tests, not target-host acceptance.

Prior Ubuntu physical timeout/late-recovery/reboot and operator-reported manual
unmount/remount/app-start acceptance are carried forward; those hardware tests were
not repeated for this focused release. Zorin Beta 2 HTTPS/adoption acceptance is
**pending**. Erugo authenticated transfer testing remains pending. Running or
visible files do not prove file-transfer integrity or arbitrary delayed database/
cache readiness; direct Docker starts do not execute Compose dependency ordering.

The historical intermittent Companion **GET /api/docker-overview HTTP 503** remains
**unresolved**; its cause is not established. No transport/backend behavior was
changed for it here. Native Plex, FTP and backup users still require a reviewed
shutdown/recovery ownership plan; Docker controls do not manage native consumers.
Software reconnect does not prove electrical power cycling. Storage Watch is not
a general application-crash restart watchdog.

Rollback: keep the previous installer and private configuration/state backup.
While idle, use apt's explicit downgrade option with that verified package; restore
configuration only if required, preserving later incident receipts and mount/data
state. Beta 2 adoption never changes the existing image or fstab, so rollback needs
no data copy or remount. Beta 1 retains its documented setup limitations.
