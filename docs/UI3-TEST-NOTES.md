> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI3 — TEST ONLY

## Virtual Disk Image creation/import and monitoring

- **Monitoring OFF:** Reviewed image creation/import uses the existing guarded filesystem and fstab update path; monitoring remains off.
- **Monitoring ON:** The user does not need to turn monitoring off. Before the image changes, the broker verifies the primary mount and the absence of unfinished recovery incidents/USB reset obligations. It briefly **stops only that drive's monitor**, acquires the existing exclusive per-drive monitor lock and shared configuration/preparation locks, performs the reviewed image operation, and starts the same monitor automatically afterward. systemd enablement is not changed. The service reloads its dependency configuration at startup. Other drive services are not stopped.
- **Busy / recovery running:** Refuse without changing the drive or stopping monitoring.
- **Failure:** Preserve the image file and existing data; attempt to restore the original running state. If service start fails, report explicitly and require a check in Manage Drive. No success claim for physical formatting until tested.
- **Safety:** Keep ext4 UUID and mount verification, reserved/empty mount location checks, free-space checks, file creation with O_EXCL, explicit consent and permissions validation. Do not format entire disks here.

## Validation on Ubuntu Studio (test machine only)

1. Verify other monitored drives are healthy and keep their settings.
2. On a **mounted test USB drive** with monitoring ON, create a small disposable virtual image (example 0.125 GB), confirm explicitly, verify the image appears in Already configured, mounts and is writable by the selected local user.
3. Verify that the drive's monitoring status returns to ON and other monitors stayed ON. Then test unplug/replug only after image creation and mount status pass.
4. With monitoring OFF on a selected mounted test drive, create a second small image. Verify the service remains OFF and both images are registered without changing another drive.
5. Do not use real backup data or production USB media for these first physical acceptance tests.

This container cannot run a physical systemd monitor or mkfs.ext4; the mocked backend and browser tests cover ON/OFF orchestration, refusal paths and frontend forms. Real target verification is pending. Zorin remains strictly off limits.
