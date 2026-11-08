# USB Storage Watch 2.0.1 Beta 6 candidate

Prepared candidate, not published. Companion 0.2.6 is unchanged.

Mounted HDD standby permits idle running applications and idle open files. Both
manual and automatic requests flush dependent image filesystems before the backing
filesystem, then require a bounded quiet interval. They preserve identity, swap,
OS-disk, mechanical-media and storage-operation safeguards. Only normal hdparm -y
standby is used. Adapter verification and activity after the command are reported
honestly. No app is stopped, filesystem unmounted or monitoring preference changed.

Manage Drive → What is using this drive? measures whole-drive and cgroup v2 I/O.
It reports every observed active container, configured access without observed I/O,
and unavailable metrics separately. Buffered/shared writes and kernel/filesystem
work may remain unattributed. Idle accounting is never proof of physical standby.
See [HDD standby](HDD-STANDBY.md) for capabilities, limitations and hardware tests.

Upgrade only while idle, using the established lifecycle preparation and a private
configuration/state backup. Verify SHA256SUMS, then install:

```sh
sudo apt install ./usb-storage-watch_2.0.1-beta6_all.deb
```

Build: `python3 -B tools/build.py`. Internal Debian version: `2.0.1~beta6`.
Retain Beta 5 for rollback with `--allow-downgrades`; preserve later incident state.
No Zorin or physical HDD standby/wake acceptance is claimed. The historical
intermittent Companion /api/docker-overview HTTP 503 remains unresolved.
