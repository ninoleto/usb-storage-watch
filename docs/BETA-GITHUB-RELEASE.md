# USB Storage Watch 2.0.1 beta 1

Pre-release for systemd Linux hosts using removable ext4 storage and explicitly
selected Docker applications. Ordinary external folders work without virtual images.

- Independent computer-startup and drive-failure recovery settings.
- Required filesystem/image identity checked before manual Start/Restart; missing
  storage refuses the request without mounting implicitly or mutating Docker.
- Reviewed safe unmount stops selected dependent apps before storage removal;
  remounting retains deliberate app stops.
- Persistent drive-return timeout, one failure notification and guarded late-return
  recovery, with incident-scoped cleanup and exact container identities.
- Upgrade preparation stops the listener supervisor first and verifies old processes
  and workers exited, including dpkg's failed-upgrade fallback.
- Companion **0.2.6**, unchanged: one-press controls through existing safeguards,
  editable layouts, separate status freshness and no replay of uncertain commands.

## Installation

Download the Debian package and `SHA256SUMS`. If all three assets are downloaded,
verify the complete manifest and install while recovery/storage operations are idle:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_2.0.1~beta1_all.deb
```

Open `http://localhost:8765`. Fresh installation enables the broker, localhost
dashboard and boot timer; drive/app automation requires configuration and LAN starts
disabled. Back up existing settings and coordinate any previous watcher first.
Never operate two recovery owners for the same storage.

The portable application source includes its installer and bundled module. The
Companion development source is also included in the tagged Git repository. Import
the separate 0.2.6 archive only if needed; existing 0.2.6 buttons need no replacement.
Packages are unsigned; checksums are integrity checks, not signature verification.

## Validation and limits

Carried-forward Ubuntu physical tests cover a five-minute no-return timeout,
late recovery and a connected-storage reboot. UI40's real upgrade verified process
renewal and preserved runtime/configuration. The operator reports successful safe
unmount, clients blocking starts, remount retaining stops, explicit starts and
visible existing files; Immich briefly showed Starting before Running. Those client
refusals sent no command and are not a physical backend-refusal test. Backend
storage protection has separate simulated and authenticated-client coverage.

This beta uses that runtime with version/publication changes. Package validation
uses isolated roots and simulated services; no live installation of the beta or
Zorin production deployment is claimed. Erugo authenticated upload/download is
deliberately deferred to target-host acceptance. Running/visible files do not prove
transfer integrity or readiness with delayed databases/cache.

Existing loop images can be retained through the documented CLI/config route.
Native Plex/FTP/backup consumers are not stopped by Docker controls; a reviewed
native-service and storage-ownership plan is required. Software USB reconnect does
not prove electrical power cycling. There is no general crash-restart watchdog.
The historical Companion HTTP 503 cause remains unidentified.
