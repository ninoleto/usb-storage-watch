> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# 2.0 DEV4 — test-only core fixes

Checkpoint: `checkpoint/pre-dev4-core-fixes-20261030`, before changing DEV3.
The recovery engine is unchanged apart from its version. Existing USB recovery,
SMTP, Docker recovery, multiple filesystems, standby and Bitfocus Companion
components are reused. No physical disk was formatted or reset, no live Docker
workload was tested, and no production or physical target computer was accessed.

## Corrections

- Local HTTP always binds 127.0.0.1:8765 and accepts localhost. Optional HTTPS
  runs in a separate LAN service. Enabling it verifies the certificate and live
  listener; failures restore previous files. Disabling it leaves local access
  and authenticated local sessions available. LAN addresses/status refresh;
  after an address change, choose the new address and save. Trust guidance and
  the public certificate fingerprint remain available.
- Overview keeps drive identity, current mount and live monitoring/recovery
  together. Previous manual results have timestamps. Stop monitoring is amber
  with a pause icon. Hub reconnect stays visibly disabled with a precise reason;
  ordinary mounting remains available. Unknown spindle state is not called idle.
- Optional Limited Storage Spaces need only a name and size in GB. Defaults use
  `usb-storage-watch-volumes`, with protected `.images` backing storage and an
  accessible mounted folder. Existing paths are retained. New roots belong to
  the authenticated local user and undergo a real non-root file-access check.
  Imported spaces offer explicit, backed-up, nonrecursive ACL correction of
  only required folders. Existing files and lost+found are not changed.
- Prepare Drive only formats. Its bounded worker stops monitoring after consent,
  retains the existing identity/busy/namespace guards and backups, and reports
  actual preparing, formatting, mounting and verifying stages. Conflicting
  controls remain unavailable until completion; monitoring setup is separate.
- Setup no longer rewrites independent Email settings. Password preservation,
  separate save/test actions and accurate SMTP acceptance reporting remain.
- A phone drawer replaces scrolling tabs. Light, dark and system appearance,
  large numeric controls, individual resets and group resets retain validated
  backend defaults. Advanced Docker and multiple-space recovery remain intact.

## Validation

492 automated tests, including 31 Chromium workflows with isolated OS boundaries.
Coverage includes USB port changes, hub refusal, successful/error reconnect,
multiple dependencies and partial recovery, stopped Docker containers, email and
configuration preservation, formatting consent/progress, access correction,
mobile appearance and numeric defaults. Docker tests are simulations only.

Real Gunicorn listeners in a private network namespace passed localhost and
127.0.0.1 HTTP throughout LAN enable/disable, invalid certificates, IP changes,
failed LAN restart and rollback. TLS verification stayed enabled; an untrusted
certificate was rejected. Only isolated listener processes were started.

An isolated QEMU guest used two disposable 1 GiB virtual USB disks. Real Linux
partitioning, ext4 creation and mounts passed, including selected-drive reformat,
all four asynchronous stages, two dependent spaces, recovery ordering and partial
recovery. A non-root account browsed, created, modified and deleted files in new
and explicitly corrected existing spaces. Backing-file access was denied and
lost+found/existing-file metadata stayed unchanged. Busy/system/namespace/swap/
loop/device-mapper/layout guards refused unsafe operations. The unrelated virtual
disk checksum stayed unchanged. The small guest stubs systemctl; it is not a full
Ubuntu Studio installation. Package and upgrade results accompany the transfer
bundle in TEST-VERIFICATION.txt.

## Physical acceptance still required

Install/upgrade and reboot on Ubuntu Studio 26.04.1; local/LAN access and trust
from another device; desktop automount and Dolphin access; real HDD bridge standby
reporting; moved direct USB ports and hubs. Reformat only an explicitly authorized
disposable drive. Large/4K-sector disks and physical power loss remain untested.
The previously observed QEMU loop-metadata timeout under rapid remounts remains a
bounded verification limitation; no retry budget was expanded. Live Docker
acceptance is deferred. Ubuntu Studio and Zorin support is not newly certified by
these development-VM checks. Nothing has been published.
