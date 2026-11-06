> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 2.0 UI4 — TEST ONLY

This build is for the **Ubuntu Studio 26.04.1 test computer only**. **Do not install on Zorin** or any production server.

## Changes

- Confirmation dialogs lock all controls during an outstanding operation. The app displays a spinner and waits for a verified server result; it does not fabricate percentage progress.
- Important manual actions now join the per-drive Event History: manual reconnect, mount/unmount, monitoring toggles, recovery and email settings changes, image configuration changes and intentional image mount/unmount. Routine health polling is not logged.
- Monitoring OFF displays in red.
- HTTPS Advanced Settings show the authenticated public local CA download (if available), fingerprint and browser trust instructions. Private keys are never offered for download.
- Management token can be explicitly rotated from Advanced Settings. The previous token and sessions are revoked; the new token is retrieved **on the host** using `sudo cat /var/lib/usb-storage-watch/management.token`. Do not paste it into chat or logs.
- Mechanical HDDs gain a guarded **Sleep HDD now** action and automatic standby after a configured idle period. Only verified idle disks are permitted to sleep; unknown/busy drives are refused, and standby is never inferred from polling alone. Flash/SSD controls are hidden.
- Creating, importing, manually mounting and intentionally unmounting Virtual Disk Images no longer require manually disabling monitoring. The selected monitor is paused/resumed inside a guarded transaction, leaving other drives untouched. Intentional unmount disables that image's automatic recovery and sets `noauto` for boot-time fstab mounts until the user explicitly mounts the image again. Configured Docker dependencies must be detached before unmount. The backing file is retained.
- Backing .img size is displayed when the verified ordinary file can be stat-ed; otherwise it shows Unknown rather than a false 0 GiB.

## Tests / known limits

- Browser tests use a simulated authenticated API, not physical USB operations.
- Targeted Python tests use isolated stores and mocks. Standby safety is covered by historical regressions; hardware spin-down and USB controller power removal are NOT verified here.
- The cloud build environment does not have Flask or mkfs.ext4; complete live HTTP and image formatting tests are therefore deferred to Ubuntu Studio. Do not treat that as a passing full suite.
- A manual USB port reconnect is a software re-enumeration; it does not prove electrical 5V power removal.
- Actual status of a USB-SATA bridge may be Unknown when no passive proof is available.
- Docker integration with live containers remains deferred until the basic workflow passes physical testing.

## Safe first physical checks

1. Open localhost UI, verify both drives and historical settings.
2. Verify button lock and status during a guarded reconnect of an **approved disposable test USB**. Never touch a shared USB controller or an unsupported hub.
3. Test mount/unmount of a small disposable image with monitoring ON, verify that the other mounted image remains untouched and the image remains unmounted after a page reload. Re-enable it through Mount Image.
4. Test manual Event History, red Monitoring OFF, HTTPS trust download and token rotation (only after preserving a way to log back in).
5. Test HDD standby only with a known-supported **mechanical HDD** on Ubuntu Studio, and only after confirming it contains no required running applications. Do not test with an SSD or flash drive.

Zorin OS remains OFF LIMITS.
