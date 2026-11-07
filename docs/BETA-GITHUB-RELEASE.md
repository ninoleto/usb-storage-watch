# USB Storage Watch 2.0.1 Beta 4

Prepared testing prerelease. This update improves GUI Docker setup and saved
startup/recovery indicators. Companion **0.2.6** is unchanged.

- Permission diagnostics name the exact Compose/environment file or parent
  directory, with owner, Unix mode and relevant group membership. Configuration
  contents and secrets are never included.
- Eligible files offer **Review file permission change → Confirm**. The review
  shows the exact mode change and affected writers. Only group/other write bits
  are removed from that single pinned file; no recursive chmod/chown or parent/
  media changes. File/container identity, memberships and recovery locks are
  rechecked. Normal Compose validation and app review then run again.
- Permission adjustment never restarts/recreates an app or saves its startup/
  recovery settings. Unsaved settings remain **Not configured**. Existing saved
  choices are retained, including during partial failure.
- Saved **Startup enabled** and **Recovery enabled** badges now have a visible
  success-green border in both expanded and collapsed cards. Off, unknown and
  unsaved settings do not gain enabled styling.

Directory changes, unsafe ownership, symlinks/hard links, access ACLs, special
mode bits and known app bind-mounted configuration are not offered for automatic
repair. The specific affected path and limitation are shown instead. Shared media
access must be reviewed by its owner. Unsupported Compose sources and external
managers remain subject to existing safeguards; technical instructions are
expandable. See [Docker setup](DOCKER-SETUP.md) in the source documentation.

## Install or upgrade

After receiving the three package assets and `SHA256SUMS` in one directory:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1-beta4_all.deb
```

Internal Debian version: **2.0.1~beta4**, newer than Beta 3. Public asset names use
hyphens and match the checksum manifest. Source:
`usb-storage-watch-2.0.1-beta4.tar.gz`; build with `python3 -B tools/build.py`.
Apt resolves declared dependencies. Packages are unsigned; hashes verify bytes.

Privately back up current settings/state and keep the previous installer. Upgrade
only while storage/recovery is idle. Existing settings, tokens, mounts and app
selections are preserved. No live install is required to build/test this release.
Fresh installation enables the broker, localhost dashboard and boot timer;
monitoring, recovery, LAN listening and app startup remain explicit choices.

Open Docker Apps, edit the intended startup/recovery selections and **Review
changes**. Inspect any permission diagnostic; confirm a supported file adjustment
only if the named accounts should lose write access to that configuration. Then
review the refreshed setup and **Save settings**. A directory diagnosis requires
owner review; do not recursively change application/media permissions to bypass it.

## Evidence and limits

Isolated tests use actual temporary file permissions/descriptor operations and
Compose configuration rendering, with simulated Docker, service control and
accounts/groups. They cover Erugo-like, PhotoPrism-like and Immich-like layouts;
shared-group files and exact writable ancestors; refusal/stale reviews; preserved
media; failure/rollback; competing locks; source consistency and successful or
partial settings saves. Python 3.12 compatibility and affected app/recovery/storage
regressions are checked. No production Docker or host permission changes occurred.

Real Chromium at 320/768/1440 px uses localhost HTTP, authenticated sessions and
the broker to exercise the complete permission UI and saved green badges. Package
validation uses private fresh/upgrade roots and byte/hash/privacy checks. These
are not Zorin acceptance tests. The exact blocking Immich directory on that host
has not been established by the supplied evidence; the GUI must identify it.

Earlier physical Ubuntu timeout/recovery/reboot and manual-unmount acceptance,
and earlier isolated TLS/mount tests, are carried forward rather than repeated.
Automatic recovery, identity/storage safeguards and Companion are unchanged.
Zorin acceptance and Erugo authenticated transfers remain pending. Native Plex,
FTP and backup users need their own ownership/shutdown plan; Docker controls do
not manage them. Direct Docker starts do not enforce Compose dependency ordering.
The historical intermittent Companion `/api/docker-overview` HTTP 503 remains
unresolved. Storage Watch is not a general application-crash watchdog.

Rollback while idle uses the retained verified Beta 3 installer with apt's explicit
`--allow-downgrades` option. Preserve later incident state. A downgrade does not
undo a separately confirmed permission change; original modes and identities are
recorded privately for precise owner review. Do not restore permissions recursively.
Earlier released source/tags/assets and the unchanged Companion archive are retained.
