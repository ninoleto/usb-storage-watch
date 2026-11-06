# Maintenance and troubleshooting

## Turn off automatic actions, keep email

Wait for any active incident to finish. Stop **this package's** service, edit the
configuration, then validate and start it:

```sh
sudo systemctl stop usb-storage-watch.service
sudoedit /etc/usb-storage-watch/config.json
sudo usb-storage-watch validate
sudo systemctl start usb-storage-watch.service
```

Set `recovery.mount`, `usb.enabled` and `docker.enabled` to `false`. Keep
`notifications.enabled` true and keep SMTP settings. Keep disk identity,
incident history and USB ledger intact. The wizard also defaults every action
off, but cannot run while an incident/USB cleanup is unfinished. Never delete
incident state to get another reset or restart budget.

## Upgrade

Securely back up `/etc/usb-storage-watch/` and `/var/lib/usb-storage-watch/` before
maintenance. They contain credentials, hardware identities and the queue. Avoid
upgrades during an outage. Use the same installation method:

```sh
sudo apt install ./usb-storage-watch_NEW_VERSION_all.deb
# Or, from the newly extracted portable source:
sudo python3 tools/install.py
```

The monitor and this package’s two GUI services are stopped for replacement. Its stop hook attempts any pending
port re-enable. Unresolved cleanup blocks replacement/removal so helpers are
retained. If the service was active before upgrade, it is started again afterward;
an inactive service remains inactive. Configuration, SMTP credentials, queue and
history are not overwritten. Portable upgrades save prior program files under
`/var/lib/usb-storage-watch/backups/`. A failed copy leaves the service stopped;
fix the installation before starting it. dpkg manages package rollback/error
recovery. Read the changelog and preserve the old package for rollback; do not
downgrade across an incompatible state schema without reviewing its migration.

After upgrade:

```sh
sudo usb-storage-watch --version
sudo usb-storage-watch validate
sudo usb-storage-watch diagnose
systemctl is-active usb-storage-watch.service
sudo usb-storage-watch status
```

The source version, schema version and runtime incident version have different
purposes. Current package version is 1.1.0; config schema is 1; state schema is 2.

## Remove

For a Debian installation:

```sh
sudo apt remove usb-storage-watch
```

For a portable installation, retain/extract its archive and run:

```sh
sudo python3 tools/install.py --uninstall
```

Removal stops/disables this package’s monitor and GUI services and removes their code/units. It never
unmounts data, touches Docker, edits fstab or removes your data. Configuration,
SMTP credentials, history and queued mail remain. This package deliberately
retains generated configuration/state even with `apt purge`, so a mistaken purge
cannot erase a pending safety record. Reinstalling resumes that retained state;
it does not automatically start a previously removed monitor. A previously enabled
GUI returns on reinstall; an explicitly disabled GUI remains disabled.

For complete erasure, first verify the service is removed, no USB enable is
pending, and no queued email/history needs preserving. Archive the two private
directories and `/etc/usb-storage-watch-web/` if needed, then remove those directories manually. No automatic
purge utility deletes safety records. Do not remove the watched filesystem or
application data. A pending USB re-enable must be resolved while the installed
helpers are still available.

## Change the watched disk

One installation monitors one filesystem. Stop this service cleanly, resolve any
pending port enable, finish the incident, and securely archive the old config,
state and queue together. Only then initialize a new configuration/state for the
new disk. A saved UUID/mountpoint mismatch is intentionally rejected. Do not run
two copies against the same disk and do not point this package at an existing
monitor's state directory.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Service skipped / inactive after install | Installation does not activate it. Complete setup, validation and email test; then explicitly enable/start. |
| Invalid/unreadable config | Use `sudo usb-storage-watch validate`. JSON fields are strict; directory root:0700 and files root:0600. Do not paste secrets into logs. |
| State must be on internal root | `/var/lib/usb-storage-watch` must be on the writable root filesystem. Separate `/var` is currently unsupported. |
| Mount present but reported unhealthy | Correct UUID and ext4? Whole filesystem root? Both rw flags? `errors_count=0`? No stacked mounts? Run `diagnose` and review the journal. |
| Normal mount skipped | Explicit opt-in, exact fstab UUID/options, empty safe mountpoint, clean superblock/journal and no active use are all required. Read the recorded reason. |
| Unclean/aborted journal or filesystem errors | Stop automatic attempts and involve an administrator. Repairs are never automatic; do not override the guard with a force mount. |
| USB skipped | Read qualification/binding/isolation reason. Present device, stale Docker namespace, open handles, peer/hub or changed hardware intentionally prevents reset. |
| USB re-enable failed | Keep helpers/ledger installed. Further recovery is blocked. Review hardware/port identity and kernel logs; seek manual assistance. Software cannot fix missing power or a hung controller. |
| Application untouched | Was it running before the outage? Exact saved ID/bind? Is storage currently proven healthy? Unknown/stopped/paused containers are preserved. |
| Application verification failed | Check healthcheck, bind destination, rprivate/rw, source inode, access permissions and required shell/timeout/find tools. No automatic repeated restart. |
| SMTP failure | Check provider host/port/TLS mode, app password, account restrictions, network and CA certificates. Errors are sanitized. Test inbox delivery explicitly. |
| Queue retry after uncertain SMTP response | Normal ambiguity: event IDs are stable, but accepted messages can be delivered twice. |
| No second email after failed incident later returns | One final event per incident; later healthy verification re-arms the next independent outage. Review the journal for late restoration. |
| Pending incident after restart | Intent was persisted deliberately. Do not delete it; allow bounded verification/finalization. |

Useful commands:

```sh
sudo journalctl -u usb-storage-watch.service --since today --no-pager
sudo usb-storage-watch diagnose
sudo usb-storage-watch status
sudo usb-storage-watch verify-apps
```

Runtime state and diagnostics contain private filesystem/hardware/container
information. Redact those before reporting a bug. Never include `smtp.json`, its
backup, provider credentials, complete container environment, or private USB
qualification evidence in a public report.

## Web service maintenance

See [WEB-GUI.md](WEB-GUI.md) for authentication, session revocation, headless
installation and TLS recovery. Back up `/etc/usb-storage-watch-web/` privately
when LAN TLS is configured: it contains a private key. The presentation history
is `/var/lib/usb-storage-watch/web-history.sqlite3`; it never controls recovery.
