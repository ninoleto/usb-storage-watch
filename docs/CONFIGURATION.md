# Configuration reference

The interactive `sudo usb-storage-watch setup` utility is the recommended starting
point. It requires this package's service to be stopped and refuses to change an
incident in progress or an unresolved USB enable obligation. It never stops a
service for you. It preserves the previous JSON file as `*.previous`, including
SMTP credentials; protect backups like the live configuration.

Files on the target host:

| Path | Purpose |
| --- | --- |
| `/etc/usb-storage-watch/config.json` | Disk identity and explicit recovery choices |
| `/etc/usb-storage-watch/smtp.json` | SMTP credentials and recipient |
| `/var/lib/usb-storage-watch/` | Durable incidents, receipts, locks, application/USB ledgers and email queue |
| `/usr/lib/usb-storage-watch/` | Program modules |
| `/usr/sbin/usb-storage-watch` | Administration command |
| `/usr/lib/systemd/system/usb-storage-watch.service` | Service unit |

The configuration directory must be root-owned mode `0700`; JSON files must be
root-owned mode `0600`, regular single-link files. Symlinks are refused. The
internal state directory uses mode `0700`. Back up these directories securely.
Never put credentials in a shell command, Git repository or public issue.

Use `sudoedit /etc/usb-storage-watch/config.json` after stopping this service.
Validate before restarting. Unknown/missing settings, unsafe paths and options
are rejected. JSON uses `true`/`false`, not quoted strings. The example in
`examples/config.json` includes every field but deliberately has an empty disk
UUID and no recipient/credentials. It must be configured before use.

| Group / field | Meaning and default |
| --- | --- |
| `version` | Configuration schema version `1` |
| `disk.uuid` | Exact lowercase ext4 filesystem UUID; required |
| `disk.mountpoint` | Stable absolute path; example `/mnt/storage` |
| `disk.label` | Short email subject label, default `USB storage` |
| `disk.fstab_options` | Exact reviewed comma-separated fstab options; empty until mount recovery is enabled |
| `monitor.interval` | Seconds between observations, default `15`, allowed 5–3600 |
| `monitor.observations` | Consecutive unhealthy/healthy observations, default `2`, allowed 1–10 |
| `monitor.boot_grace` | Boot observation grace in seconds, default `90` |
| `notifications.enabled` | Enable outcome email; wizard recommends true; requires SMTP configuration |
| `recovery.mount` | Allow guarded normal mounts; default false |
| `recovery.wait` | Minimum wait before each attempt, default `15` seconds, allowed 15–86400 |
| `recovery.attempts` | Reserved normal recovery attempts per attachment, default `1`; absent waiting does not consume a mount attempt |
| `recovery.worker_timeout` | Total supervised storage worker deadline, default `120` seconds; must allow enumeration plus 50 seconds |
| `dependent.enabled` | Observe an existing dependent loop filesystem, default false |
| `dependent.uuid`, `mountpoint`, `image`, `fstab_options` | Exact ext4 identity, mountpoint and regular image on the main disk; loop option required |
| `usb.enabled` | Explicit opt-in; default false, requires qualified profile and mount recovery |
| `usb.profile` | Target-only qualification object, default null; see USB guide |
| `usb.disable_seconds` | Default 1 second; allowed 0.1–2 |
| `usb.enumeration_seconds` | Default 20 seconds; allowed 1–60; checks every 0.25 seconds |
| `docker.enabled` | Stop selected containers on detected disk failure and start after disk/image recovery; default false |
| `docker.socket` | Local socket, default `/var/run/docker.sock` |
| `docker.api` | Explicit supported Docker API version, default `v1.47` |
| `docker.health_timeout` | Per-container health verification deadline, default 120 seconds |
| `docker.worker_timeout` | Entire application stage deadline, default 720 seconds; adjust for many containers |
| `docker.containers` | Explicit list, empty by default, maximum 10 |

A container entry has `name`, `container_id`, `images`, `grace` (5–120 seconds),
and the legacy advisory fields `source` and `destination`. `images` is a list of
registered image UUIDs on this drive. An empty list means no additional image
selection. New selections use an explicit Docker container ID; upgrading keeps
existing selections and does not infer image choices from bind paths.

```json
{"name":"photo-app","container_id":"<64-character Docker ID>","images":[],"source":"","destination":"","grace":30}
```

Use the container cards in **Docker & Applications** to configure these choices.
The same container can be selected for more than one drive. Monitoring can stay
on while saving. No Compose/YAML or bind changes are made. Detection warnings
do not impose prerequisites. Explicitly selected images must be mounted before
starting the container; unrelated image failures are reported separately. A recorded Docker request is never blindly
replayed after a timeout. Increase the application deadline if several selected
containers need long graceful shutdown or health-check periods.

## Normal mount configuration

Mount recovery uses only an **existing, reviewed** `/etc/fstab` entry. The package
does not create or edit entries, create data directories, attach images, or run
mount/repair during setup. Have the normal mount working before enabling recovery.
A representative main entry is:

```text
UUID=YOUR-REAL-EXT4-UUID /mnt/storage ext4 defaults,nofail,x-systemd.device-timeout=10s 0 0
```

Replace the placeholder with your own UUID. This example disables automatic
boot-time fsck for that entry (last field `0`); filesystem maintenance is your
responsibility. Never copy a fabricated UUID into production. For an existing
loop image the source is its absolute path and options must include `loop`.

Allowed options are `defaults`, `rw`, `nofail`, `nodev`, `nosuid`, `noexec`,
`noatime`, `relatime`, `lazytime`, `errors=remount-ro`, and the documented
`x-systemd.device-timeout=Ns` / `x-systemd.requires-mounts-for=/path` forms.
`loop` is permitted only for the dependent image. Options such as `force`,
`remount`, `ro` and `noload` are rejected for automatic mount recovery.

The monitor independently checks actual UUID, ext4 superblock, error counters,
mount flags, occupied targets, process mount namespaces and exclusive access to
the returned block device. Normal ext4 journal replay is allowed when no error
state is recorded. Nonempty mountpoints are allowed without modifying underlying
files. An unclean filesystem without a journal to replay still requires review.
Successful remount is never promised; damaged or actively used storage is refused.

## SMTP

`sudo usb-storage-watch smtp-setup` changes SMTP settings while the service is
stopped. Fields are `version:1`, `security` (`starttls` or `tls`), `host`, integer
`port`, `username`, `password`, `sender`, `recipient`. Exactly one recipient is
supported. Authentication is mandatory; an unauthenticated relay is unsupported.
The example uses reserved example addresses and an empty password, so cannot
send mail unchanged. There is no credential import from another application.
TLS validates the server certificate and hostname using the host trust store.

After changing SMTP settings, run `sudo usb-storage-watch validate`, then
`sudo usb-storage-watch test-email`, check receipt, and start the service.
