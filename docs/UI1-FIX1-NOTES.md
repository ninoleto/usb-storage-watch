> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 2.0 — UI1+fix1 test-only hotfix

## Reproduced failure

On the UI1 Virtual Disk Images page, entering **Add existing** or pressing **Scan USB drive** caused an HTTP 400 error: `Unknown or disallowed operation.` The Flask frontend allowed `image-discover`, but `web_broker.py` had omitted it from the privileged broker's read-only operation allowlist. The broker refused the request before reaching the existing bounded, read-only image discovery implementation.

## Changes

- Add `image-discover` to the privileged broker's **read-only** allowed actions. It still requires an authenticated dashboard session, does not permit a POST, and never itself imports, formats, mounts or alters an image.
- Keep image registration and creation guarded by the existing review/consent and filesystem verification procedures.
- Stop scanning automatically when changing tabs. Explicit **Scan USB drive** requests exactly one read-only scan.
- When the selected USB filesystem is not mounted or its status is stale, provide a clear **Open Manage Drive** link and disable create/scan/import until mount verification.
- Preserve previously configured images, settings, tokens, recovery state, SMTP, LAN listeners and the approved UI layout. No migration is required.

## Tests

- Red tests reproduced the exact 400 error for both legacy and second drive profiles; green tests validate authenticated read-only access and POST/unauthenticated refusals.
- Static contract test checks all literal UI API operations against frontend and broker allowlists.
- Browser mock checks confirm explicit scanning, no automatic duplicate scan, and proper unmounted-drive warnings at 320, 390, 768 and 1440px.
- Installed-package and upgrade checks use a private synthetic root, never a physical disk.

## Important existing limitations

- The known host `/proc/<pid>/fd` permission issue with manual USB reconnection is **not** fixed here.
- This cloud environment lacks the `flask` and `mkfs.ext4` executables, so real Flask HTTP and physical ext4 image creation are not certified by these tests.
- Virtual Disk Images require a verified mounted primary USB drive. Remote uploads and network-share transfers are not implemented.
- No physical disks, USB ports, Zorin host, SMTP server or real Docker containers were accessed or modified.
