# USB Storage Watch 2.0.1 Beta 3

Testing prerelease for systemd Linux hosts with removable ext4 storage and
explicitly selected Docker apps. Ordinary external folders need no virtual image.

This release corrects two GUI setup blockers reproduced against Beta 2:

- **Recovery activation with registered mounted images:** planning freshly checks
  the physical filesystem, registered image UUID, backing file/device/inode,
  loop offset/size and mount topology. Verified child image mounts no longer
  block activation. Unknown, shared, stacked, conflicting or changed mounts still
  refuse setup. The recovery worker's strict remount guard is unchanged.
- **Email notification setup:** missing, unreadable or invalid SMTP settings
  produce sanitized instructions to open **Email & Notifications**. Refusal
  leaves the drive's settings and monitoring unchanged. Genuine later service
  failures remain distinct. Valid saved email settings allow notification enabling.

Beta 2's first-HTTPS and reviewed mounted-image adoption fixes remain. Companion
**0.2.6** is byte-identical; existing buttons need no replacement. Earlier release
tags/assets are retained. No recovery engine, app-start policy or token changes.

## Install or upgrade

Download the three package assets and `SHA256SUMS` into one folder, then verify:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-beta3_all.deb
```

The internal Debian version is **2.0.1~beta3**, newer than Beta 1 and Beta 2.
Public filenames use hyphens so GitHub retains the checksum manifest's names.
The source archive is `usb-storage-watch-2.0.1-beta3.tar.gz`; build from its root
with `python3 -B tools/build.py`. Apt resolves distribution dependencies.
Checksums verify bytes; packages are not publisher-signed.

Privately back up configuration/state and coordinate existing automation first.
Install only while storage/recovery is idle. Fresh installation enables the
broker, localhost dashboard and boot timer. LAN access, drive monitoring/recovery
and app startup need explicit configuration. Open `http://localhost:8765` and use
the management-token instructions. Upgrades preserve settings and credentials.

For a fresh setup, use the GUI in this order:

1. Register the physical drive and retain its verified existing mount.
2. If required, adopt its existing mounted image through **Virtual Disk Images**.
3. Start monitoring, then review and enable **Automatic recovery** in Manage Drive.
4. Configure SMTP in **Email & Notifications** and send an explicitly requested
   test there; then enable the drive's **Email notifications**.
5. Review exact app identities, independent startup/recovery drives and optional
   images in **Docker Apps**, including Docker/Compose restart-policy ownership.

Registration/adoption never disables another watcher or adds app dependencies.
See [image handover guidance](https://github.com/ninoleto/usb-storage-watch/blob/v2.0.1-beta.3/docs/EXISTING-IMAGE.md).

## Validation and limits

Both setup failures were reproduced on unchanged Beta 2. Beta 3 tests cover the
full authenticated setup sequence, preserved settings on refusal, changed/unknown
image identities and topology, stale reviews and competing operation locks.
An isolated mount namespace used two real disposable ext4 loop mounts and real
loop identity checks, preserving fstab, data and permissions. Email setup/testing
used certificate-verified SMTP TLS confined to localhost. USB discovery, PAM,
service control and Docker were simulated; no production storage or services
were operated. Focused Docker policy/Compose, optional-image, manual storage,
boot and repeated-recovery regressions passed.

Chromium tests at 320/768/1440 px used real localhost HTTP, sessions and broker
handlers, verifying recovery confirmation and missing-email toggle rollback and
successful retry. Fresh/upgrade checks used private package roots; Python 3.12
with Flask 3.0.2 was tested. Packaged TLS regressions preserve Beta 2's verified
HTTPS confirmation/rollback and certificate/hostname rejection. These are
isolated tests, not a booted target-distribution or production acceptance test.

Prior Ubuntu physical timeout/late-recovery/reboot and operator-reported manual
unmount/remount/app-start acceptance are carried forward, not repeated. Zorin
Beta 3 acceptance and Erugo authenticated transfer testing remain **pending**.
Running/visible files do not prove transfer integrity or arbitrary delayed
application dependencies; direct Docker starts do not execute Compose ordering.

The historical intermittent Companion **GET /api/docker-overview HTTP 503**
remains **unresolved**; no cause or fix is claimed. Native Plex, FTP and backup
users require their own reviewed shutdown/recovery ownership plan; Docker
controls do not manage native consumers. Software reconnect is not proof of
power cycling. This is not a general application-crash restart watchdog.

Rollback: retain the prior installer and private configuration/state backup.
While idle, use apt's explicit downgrade option with the verified prior package.
Restore configuration only if needed, preserving later receipts. No image data,
mountpoint or fstab migration is required. Beta 2 retains the two setup limitations
corrected here; Beta 1 also lacks Beta 2's HTTPS/adoption fixes.
