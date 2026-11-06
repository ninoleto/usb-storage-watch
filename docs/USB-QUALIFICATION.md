# Optional USB port qualification

Leave USB recovery disabled unless a knowledgeable operator has independently
qualified the exact target disk, bridge, controller and physical port. Discovery
of a sysfs file is not qualification. A test on another computer does not qualify
this one. There is no shipped hardware allowlist and no automatic reset test.

Supported topology is a directly attached PCI xHCI root port with a stable
firmware node, no `peer` link in the current single-port executor, and a functioning per-port `disable`
attribute. Shared hubs, multi-level paths, controller resets, hub resets,
`uhubctl -f/-R`, whole-device authorization and alternate reset fallbacks are
unsupported. If the topology does not qualify, retain normal mount recovery.

A USB2/USB3 peer can be the other interface of the same physical connector.
Its presence does **not** prove isolation impossible. RC2 distinguishes peer
relationships read-only but retains the single-port execution restriction:
paired control and independent restoration of both interfaces are not yet
implemented or physically qualified. See [peer investigation and offline test
plan](USB-PEER-QUALIFICATION.md). Do not use the single-port attestation below
to bypass a peer refusal.

The Ubuntu 24.04 VMware validation guest exposed a peer link and no usable
stable port firmware identity. Candidate collection therefore refuses it with
an explanatory message; no qualification or automatic port reset was enabled.
Guest storage-driver detach/rebind was tested separately and does not qualify
the virtual controller or the physical host controller.

For an additional VMware passthrough test, first stop this monitor and every
consumer and cleanly unmount the test filesystem inside the guest. On the host,
use VMware Workstation's **VM → Removable Devices → the dedicated USB drive →
Disconnect (Connect to host)**, then **Connect (Disconnect from host)** to return
it. Verify the UUID and mount relationships again in the guest before use.
This host-side step must be performed by the operator; it is not a port power
test and does not override a rejected qualification.

## Collect a candidate without changing USB

With the disk normally mounted read/write, configured, healthy and this package's
service stopped, create a private directory and collect the candidate:

```sh
sudo install -d -m 0700 /root/storage-watch-qualification
sudo usb-storage-watch usb-candidate --output /root/storage-watch-qualification/candidate.json
```

This only reads identity and verifies the disk. It does not write sysfs or enable
resetting. It can fail conservatively on unsupported topology. Candidate JSON
contains the target hardware serial and physical paths: keep it private; never
add it to the distributable source repository.

## Independent qualification

Qualification is an administrator-controlled maintenance procedure outside this
package. Do not test on a mounted/active disk. Schedule downtime, ensure backups,
account for every dependent process/container/mount namespace, cleanly stop use,
and detach all relevant mounts/loop devices before any hardware test. This
package provides no command that performs that test or unmounts/stops consumers.
Have a qualified administrator perform it if you cannot prove those conditions.

Retain evidence that:

- The healthy filesystem UUID, bridge VID/PID and unique disk serial correspond
  to the intended physical connector and recorded PCI controller/firmware node.
- Only that individual port disconnected; kernel messages show no other USB
  device disconnections and no effects on other physical connectors.
- The port successfully re-enabled and its `disable` value read back as `0`.
- The correct disk/UUID returned within the intended bounded detection window,
  and normal mounts could be verified healthy afterward.

An offline success demonstrates port-specific logical control, not guaranteed
recovery from cable/power/enclosure/disk faults. Inspect the candidate again after
restoring normal operation; moved/replaced hardware requires new qualification.

## Record attestation and enable policy

Only after that independent test, with the original healthy disk back on its
qualified port, mount recovery configured and the service stopped:

```sh
sudo usb-storage-watch qualify-usb \
  --profile /root/storage-watch-qualification/candidate.json \
  --date YYYY-MM-DD \
  --evidence 'Describe the independent isolated-port test, enable readback, correct UUID return, and private evidence location.'
sudo usb-storage-watch validate
sudo usb-storage-watch diagnose
sudo systemctl start usb-storage-watch.service
```

Replace the date and evidence text. The tool requires the exact word `QUALIFIED`,
recollects the current healthy identity, refuses a mismatch, and saves the profile
and explicit enable choice. It performs **no physical test or reset**. Attestation
is an operator responsibility; the program cannot establish the truth of external
evidence. Recovery additionally needs a healthy same-boot binding captured by the
monitor, then a later confirmed outage satisfying all absence/activity guards.

No reset occurs if the device is still detected, another device occupies the
port, a matching bridge appears elsewhere, storage remains active, identities
change, or any guard cannot confidently inspect the system. Up to one reset is
reserved per incident, including interrupted/failed resets. Enable-only cleanup
is allowed to retry and never grants another disable.

To disable USB recovery while keeping monitoring, set `usb.enabled` to `false`
while this service is stopped, validate and start it. Do not remove a pending
USB ledger: it represents an obligation to re-enable a previously disabled port.
See recovery documentation for cleanup after interruption and hardware limits.
