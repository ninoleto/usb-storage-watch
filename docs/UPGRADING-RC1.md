# Upgrade Beta 6 to USB Storage Watch 2.0.1 RC1

Run these commands **on the target host**, during an idle maintenance window.
For the maintainer's ZORIN host, use its terminal through ANTEC. Publishing RC1
does not execute this procedure or upgrade production.

Before starting, verify no recovery, storage action, app operation or network
confirmation is pending. Do not start another operation during maintenance.
Keep any older competing watcher disabled/masked. Do not change mounts, Docker
selections, native consumers or recovery receipts to make the upgrade pass.

## Files and prerequisites

Place all five RC1 release files in one directory, together with the retained
`usb-storage-watch_2.0.1-beta6_all.deb` installer. Retain it privately before
historical GitHub releases are removed; do not rely on an old release URL.
The Beta 6 SHA-256 is:

`6328a9de25074bda967a78910d25ffbc59202e9932580d7773e932b7fa42e6df`

If that rollback package is unavailable or does not match, obtain the maintainer's
verified archived copy before proceeding. The procedure requires GNU tar, APT,
dpkg, sudo and the existing Beta 6 maintenance helpers. Stop on any error.
A read-only APT simulation precedes service preparation. No forced unmount,
USB reset, filesystem repair or Docker restart is part of these commands.

## Verified package and private backup procedure

Run from the directory containing the files. The subshell stops at the first
failure. The maintenance helpers quiesce USW services; APT hooks restore their
intended state. LAN disabled before upgrade stays disabled.

```sh
(
  set -eu
  test "$(dpkg-query -W -f='${Status}' usb-storage-watch)" = 'install ok installed'
  test "$(dpkg-query -W -f='${Version}' usb-storage-watch)" = '2.0.1~beta6'
  sha256sum -c SHA256SUMS
  printf '%s  usb-storage-watch_2.0.1-beta6_all.deb\n' \
    '6328a9de25074bda967a78910d25ffbc59202e9932580d7773e932b7fa42e6df' | sha256sum -c -
  test "$(dpkg-deb -f usb-storage-watch_2.0.1-beta6_all.deb Version)" = '2.0.1~beta6'
  test "$(dpkg-deb -f usb-storage-watch_2.0.1-rc.1_all.deb Package)" = 'usb-storage-watch'
  test "$(dpkg-deb -f usb-storage-watch_2.0.1-rc.1_all.deb Version)" = '2.0.1~rc.1'
  test "$(dpkg-deb -f usb-storage-watch_2.0.1-rc.1_all.deb Architecture)" = 'all'
  sudo apt-get --simulate --no-remove install ./usb-storage-watch_2.0.1-rc.1_all.deb

  sudo sh -eu - "$PWD" <<'USW_BACKUP'
umask 077
usw_backup=$(mktemp -d /var/backups/usw-before-rc1.XXXXXX)
printf 'Private backup directory: %s\n' "$usw_backup"
systemctl --no-pager --full list-units --all 'usb-storage-watch*.service' 'usb-storage-watch*.timer' > "$usw_backup/services-before.txt"
systemctl --no-pager list-unit-files 'usb-storage-watch*.service' 'usb-storage-watch*.timer' > "$usw_backup/units-before.txt"
/usr/bin/python3 -I /usr/lib/usb-storage-watch/maintenance.py prepare-upgrade
/usr/bin/python3 -I /usr/lib/usb-storage-watch/web_install.py prepare-upgrade
tar --acls --xattrs --numeric-owner -C / -czpf "$usw_backup/config-state-code.tar.gz" \
  etc/usb-storage-watch etc/usb-storage-watch-web var/lib/usb-storage-watch \
  usr/lib/usb-storage-watch etc/fstab
tar --acls --xattrs --numeric-owner -C / -dzf "$usw_backup/config-state-code.tar.gz"
cp "$1/usb-storage-watch_2.0.1-beta6_all.deb" "$usw_backup/"
cd "$usw_backup"
printf '%s  usb-storage-watch_2.0.1-beta6_all.deb\n' \
  '6328a9de25074bda967a78910d25ffbc59202e9932580d7773e932b7fa42e6df' | sha256sum -c -
sha256sum config-state-code.tar.gz usb-storage-watch_2.0.1-beta6_all.deb > SHA256SUMS
sha256sum -c SHA256SUMS
printf 'Private backup and rollback package verified: %s\n' "$usw_backup"
USW_BACKUP

  sudo apt-get --no-remove install ./usb-storage-watch_2.0.1-rc.1_all.deb
  test "$(dpkg-query -W -f='${Status}' usb-storage-watch)" = 'install ok installed'
  test "$(dpkg-query -W -f='${Version}' usb-storage-watch)" = '2.0.1~rc.1'
  usb-storage-watch --version
  systemctl --no-pager --full list-units --all 'usb-storage-watch*.service' 'usb-storage-watch*.timer'
  systemctl --no-pager list-unit-files 'usb-storage-watch*.service' 'usb-storage-watch*.timer'
)
```

The CLI should show `USB Storage Watch 2.0.1-rc.1`; the dashboard should show
`USB Storage Watch 2.0.1 RC1`. Reload and sign in again. Check saved drive/image
selections, monitoring/service states, LAN/HTTPS, container state and existing
application functionality without initiating a new recovery test.

If preparation or backup fails, stop and inspect the error; do not bypass it or
clear state. Services may remain quiesced and need administrator attention.
The backup contains credentials and private keys: never upload it to GitHub.

## Rollback

While idle, repeat the same maintenance preparation and make a fresh private
backup before reinstalling the retained, hash-verified Beta 6 package:

```sh
sudo apt-get --no-remove --allow-downgrades install ./usb-storage-watch_2.0.1-beta6_all.deb
```

Package rollback preserves current state. Do not copy old incident receipts back
wholesale or undo separately confirmed access changes. A portable installation
must use its portable installer instead of these Debian commands; preserve its
previous source archive and private configuration/state first.

See [validation](VALIDATION-CURRENT.md) for what was actually tested. The operator
procedure has not been executed on production during RC1 preparation.
