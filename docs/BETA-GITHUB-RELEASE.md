# USB Storage Watch 2.0.1 Beta 5

Prepared testing prerelease; Companion **0.2.6** is unchanged.

- **Review access changes** can cover an eligible Compose project directory and
  configuration files together. Exact numeric modes and affected writers are shown.
- Explicit confirmation removes only necessary write bits. Ownership, read/traverse
  access, directory setgid and child-data permissions are preserved. No recursive
  chmod/chown, restart/recreation or automatic settings save occurs.
- Current Docker mounts, configured shared storage, pinned identities, memberships
  and operation locks are checked. Stale reviews refuse; private records and clear
  per-path outcomes cover partial failures. Drafts return to normal Save settings.
- Portainer server/agent product labels and external access-control labels no longer
  imply deployment ownership. Confirmed management markers remain guarded; unknown
  hints and manager-private source locations stay unverified/blocked.
- Green saved-state badges, automatic recovery and Companion behavior are preserved.

Remaining GUI stops include unsafe ancestors outside the project, direct shared-data
mounts, missing/non-directory child data sources, unknown inventory/membership,
ACLs, unsafe links/ownership and unsupported Compose sources. Native-service access
is not fully inventoried: removing directory write prevents affected accounts from
creating/deleting/renaming entries there. Do not assume Plex/FTP is unaffected.
See [Docker setup](DOCKER-SETUP.md) for the exact boundary and rollback notes.

## Install or upgrade

Obtain all four assets in one folder, back up configuration/state privately and
retain the previous installer. Upgrade only while storage/recovery is idle using
the existing lifecycle preparation. Do not clear receipts or bypass a refusal.

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-beta5_all.deb
```

Internal version: **2.0.1~beta5**, newer than Beta 4. Assets:
`usb-storage-watch_2.0.1-beta5_all.deb`,
`usb-storage-watch-2.0.1-beta5.tar.gz`,
`usb-storage-watch-companion-0.2.6.tgz`, `SHA256SUMS`.
Build source with `python3 -B tools/build.py`. Apt resolves declared dependencies.
Packages are unsigned; hashes verify bytes. No target-host acceptance is claimed.

## Validation and limitations

Focused fixtures cover a PhotoPrism-like shared-group project and Compose file,
with writable child application data, and an Immich-like project/environment layout.
They exercise confirmed changes, stale reviews, shared-data refusals, partial
failure/readback, app locks and explicit settings save. Real temporary filesystem
operations and Compose rendering are distinguished from simulated Docker, accounts
and services. Browser checks use localhost authenticated broker flows at mobile,
tablet and desktop widths. A separate kernel credential fixture verifies child-data
access under a distinct UID/group. Packaging uses private fresh/upgrade roots.

Earlier physical recovery/reboot and isolated TLS/mount evidence is carried forward,
not repeated. Target-host acceptance and Erugo authenticated transfers remain pending.
Direct Docker starts do not enforce Compose dependency ordering. Native consumers
require their own ownership/shutdown plan. The historical intermittent Companion
`/api/docker-overview` HTTP 503 remains unresolved. USW is not a crash watchdog.

Rollback while idle uses the retained Beta 4 installer with `--allow-downgrades`.
Preserve later incident state. A package downgrade does not undo separately confirmed
access changes; review private original-mode records for precise restoration.
