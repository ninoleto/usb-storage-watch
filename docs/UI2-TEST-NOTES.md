> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI2 — TEST ONLY

## Confirmed corrections

- Approved interface preserved. Refresh works without blocking itself. Existing image selection immediately activates Add selected image. Image scan remains explicit and read-only.
- Reviewed mount migration submits the server-issued token, current config revision and explicit consent. The backend still refuses operations involving active incidents, dependent image paths or Docker dependencies when a safe migration cannot be verified.
- A previously configured drive with a new ext4 UUID can be re-associated **inside the GUI** (Overview or Manage Drive → Find reformatted drive). This is **not** automatic: user must review the matching physical hardware and explicitly confirm. The operation backs up old on-host config/fstab/state/pin/reset/migration data, resets old active recovery state, updates only that profile and leaves its monitoring OFF. External formatting destroys old data and images; re-association does not restore them. On failure it attempts rollback and tells user when administrator review is required.
- USB port reconnect rejects unverified ports. Kernel-only file descriptors are recognized without unnecessary stat calls, but ordinary unreadable descriptors still refuse the reset. The actual physical USB EACCES case remains **unverified**.

## First physical acceptance sequence on disposable Ubuntu Studio ONLY

1. Keep an extra copy of the current `2.0.0~ui1+fix1` DEB and your existing root configuration backup.
2. Verify zip/checksums, install UI2 and reload the browser. Confirm both ADATA and SanDisk configurations display.
3. On ADATA's disconnected profile select **Find reformatted drive**; verify the new filesystem UUID `the newly detected ext4 UUID displayed by the application`, and the original hardware identity and mount path shown in the dialog. Confirm only if they match. No drive is formatted, mounted or USB reset by this action.
4. Verify ADATA now has the new UUID and old history, but its monitor is stopped. Do **not** format ADATA again.
5. Confirm SanDisk remains mounted at `/mnt/sandisk`, and its `virtual1` and `virtual2` remain mounted/accessible. Do not modify either image.
6. Test read-only scan and selecting a discovered image. Test mount location changes only when the selected drive has no active dependent images or incidents. Do not force a busy drive.
7. Do not use Reconnect USB port until the previous permission failure is independently diagnosed and a safe direct port is qualified. Failure must refuse without touching another drive.

## Validation limits

Synthetic browser checks cover 320, 390, 768 and 1440px; tests include rollback after failed systemd reload, verified already-mounted reformatted disks, physical identity rejection, scoped rebind confirmation, two-step migration payload and immediate image selection. Additional isolated multi-drive and USB handle tests pass. This cloud environment lacks `python3-flask` and physical USB devices, so authenticated live HTTP and real hardware/operational acceptance remain pending. The package is not production-ready. Zorin OS is off limits.

## Remaining feature gaps

- Automatic dependency-aware mount path migration for configured loop-image/Docker apps is not supported; refusal is intentional, not a completed workflow.
- Remote `.img` upload/network file copying and Docker dependency editing in the new interface remain unavailable.
- Physical USB software reconnect and electrical power loss are unverified on Ubuntu Studio.
- Global UX polish must not compromise the host storage safety checks.
