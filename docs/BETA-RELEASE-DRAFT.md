# Beta 3 release preparation

Package/runtime **2.0.1~beta3**, local release tag **v2.0.1-beta.3**.
Companion **0.2.6** is unchanged. The publication repository is a clean export;
private Git history, host settings, credentials, receipts and logs are excluded.
Preserve original private checkpoints separately; never push them with `--all` or
`--mirror`. The authorized public destination is `ninoleto/usb-storage-watch`. Publish only
the sanitized history descending from Beta 1; preserve Beta 1 and Beta 2 and use a prerelease,
never the latest/stable release. Verify remote refs and downloaded asset hashes.

Use [BETA-GITHUB-RELEASE.md](BETA-GITHUB-RELEASE.md) as the proposed GitHub body and
mark the release **pre-release**. [VALIDATION-CURRENT.md](VALIDATION-CURRENT.md)
separates physical, operator-reported and simulated evidence. Erugo authenticated
transfer acceptance is explicitly deferred; do not resume password recovery.

Release assets:

- `usb-storage-watch_2.0.1-beta3_all.deb`
- `usb-storage-watch-2.0.1-beta3.tar.gz` — portable application source/installer,
  including the bundled module; module development source is in the Git tree.
- `usb-storage-watch-companion-0.2.6.tgz`
- `SHA256SUMS`

The module SHA256 must remain
`0640988a2e741099c140b40db32281066d196f3e93eb0af4a4b32b983b250b58`.
Version ordering is `2.0.0~ui40 < 2.0.1~beta1 < 2.0.1~beta2 < 2.0.1~beta3 < 2.0.1`. Do not rename UI40 artifacts.

Build as an ordinary user with Python 3.10+ and `dpkg-deb`; installer smoke also
requires `fakeroot` and `systemd-analyze`. Runtime dependencies are declared in
`packaging/control`. The existing Companion bundle is copied, never rebuilt.

```sh
python3 -B -I tools/build.py
python3 -B -I tools/integration_test.py --smoke-only
python3 -B -I tools/privacy_scan.py
```

The builder creates GitHub-compatible filenames and the complete three-asset
manifest. From the artifact directory, verify it:

```sh
sha256sum -c SHA256SUMS
```

After reviewing existing storage ownership and making a private backup, install
only while no storage/recovery operation is active:

```sh
sudo apt install ./usb-storage-watch_2.0.1-beta3_all.deb
```

A fresh apt installation creates the non-login web account, enables the privileged
broker, localhost dashboard and boot timer. No drive monitor or app starts without
configuration; LAN access defaults off. Open `http://localhost:8765`. Retrieve the
unique management token locally from `/var/lib/usb-storage-watch/management.token`
with sudo; never include it in reports. Configure optional HTTPS through Network
Settings, then use Integrations for Companion setup and same-origin module download.
Do not import another machine's token, configuration or incident state.

Keep previous installers and private configuration/state backups. Downgrade only
while idle with a compatible preserved package; retain newer incident receipts.
Uninstalling USW does not restore Docker policies or an external watcher. Existing
images can be registered without recreation via [EXISTING-IMAGE.md](EXISTING-IMAGE.md).
Native services/backup jobs require their own reviewed coordination before unmount.

Before publication, review the exact tagged tree and generated source archive,
not just the Debian payload. Keep legal notices and pinned upstream sources intact.
Check version/module consistency, isolated installer behavior and artifact privacy.
Preserve a separate validation report/checksums. Do not claim live beta installation
or target-host acceptance from isolated package tests.

## Developer handoff

Beta 3 changes only recovery planning for verified registered child image mounts
and SMTP setup refusals, plus associated tests and packaging/documentation.
`web_protection.planning_backing` verifies registered topology before a planning-only
view is passed to the unchanged engine guard. Never remove the worker's descendant
mount refusal. `web_broker.require_notification_settings` catches only SMTP load
failures before service or settings changes; do not hide genuine service failures.
`web_lifecycle.py` is embedded in the built prerm for
normal and failed-upgrade preparation before unpack; preserve supervisor-first
shutdown, worker readback and existing maintenance guards. Shared manual app
storage verification remains in `web_docker.py`, using boot/recovery verifiers and
storage/app locks. Preserve pinned IDs, deliberate stops, timeout/late-return
receipts, safe-unmount review and separate startup/recovery settings.

Companion source is `integrations/companion-module-usb-storage-watch`; the archive
is unchanged. Preserve one-press guarded controls, independently fresh status,
editable layouts and no automatic command replay. Simulate disruptive operations.
The historical HTTP 503 remains unexplained; do not infer its cause or declare it fixed.
