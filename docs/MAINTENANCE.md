# Maintenance and troubleshooting

Use the [current README](../README.md) and
[Beta 6 → RC1 upgrade procedure](UPGRADING-RC1.md) for exact package names,
private backups and service preparation.

## Configuration and monitoring

Each drive has independent settings and a systemd monitoring instance. The
original profile uses `usb-storage-watch.service`; additional profiles use
`usb-storage-watch@PROFILE_ID.service`. Prefer the dashboard's drive controls
and reviewed settings. Monitoring, automatic recovery, notifications, boot
startup and app recovery are separate options.

Wait for active operations to finish before maintenance. Do not delete incident
receipts, reset budgets, pending port-enable evidence or email queues.
Stopping a monitor preserves its incident state. Existing cleanup obligations
must be reconciled by the installed helpers.

The application version is `2.0.1-rc.1`; Debian metadata uses `2.0.1~rc.1`.
Configuration and incident schema versions are independent of release identity.
RC1 changes no schema, configuration default or recovery policy.

## Upgrade and recovery from installation errors

The existing maintenance helpers and package hooks stop and verify USW workers,
web listeners/supervisors and broker before replacement. Active monitoring and
intended web/LAN enablement are restored afterward. Disabled LAN stays disabled.
Unresolved USB enable cleanup or surviving workers can block replacement/removal.

Keep a verified old installer plus private configuration, state, certificates
and code backups. Do not overwrite current state with old receipts after a package
rollback. A failed installation may leave services stopped; inspect the error
and repair the package installation before resuming normal operation.

## Remove

Use one command matching your installation method:

```sh
sudo apt remove usb-storage-watch
# Or, from the matching portable archive:
sudo python3 tools/install.py --uninstall
```

Removal stops/disables USW services and removes its program files. It does not
unmount data, operate Docker, edit fstab or delete images/application data.
Generated configuration, SMTP credentials, history and queued mail remain, even
after Debian purge. Unresolved port-enable obligations can prevent removal.

Before manually deleting private state, verify removal completed, no USB enable
obligation remains, and required history/queued mail have been archived.
Private paths include `/etc/usb-storage-watch`, `/etc/usb-storage-watch-web`
and `/var/lib/usb-storage-watch`. Do not delete the watched filesystem.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| Unconfigured/inactive monitor | Complete setup and explicitly start monitoring for that drive. |
| Invalid configuration | Run `sudo usb-storage-watch validate`; do not publish credential files. |
| State directory refused | Persistent state must be on the writable internal root filesystem. Separate `/var` is unsupported. |
| Unhealthy mount | Review UUID, ext4 type, rw flags, stacked mounts, filesystem errors and the recorded reason. |
| Recovery refused | Busy mounts, unknown users, changed identities and uncertain receipts remain blockers. Normal journal replay differs from filesystem repair. |
| Container not restarted | Review selected prerequisites, pinned identity, deliberate stops and healthchecks. Direct starts do not perform Compose dependency ordering. |
| USB re-enable failed | Keep helpers and ledger installed; inspect port identity and kernel logs. Manual intervention or reboot may be needed. |
| SMTP failure | Review host/port/TLS, CA trust, provider restrictions and spam. Acceptance is not inbox delivery. |
| Timeout followed by late return | The incident's timeout and later recovery may have separate notifications; retained evidence prevents renewed reset budgets. |
| Old dashboard label | Beta 6 hard-coded Beta 5. Verify RC1 package/CLI, running web service and browser reload; responses use no-store. |

```sh
usb-storage-watch --version
sudo usb-storage-watch diagnose
sudo usb-storage-watch status
sudo usb-storage-watch verify-apps
systemctl --no-pager --full list-units --all 'usb-storage-watch*.service'
```

Diagnostics may contain private disk/container identities. Redact before sharing.
Never publish SMTP settings, tokens, private keys or full Docker environment values.
See [web maintenance](WEB-GUI.md) for authentication and certificate handling.
