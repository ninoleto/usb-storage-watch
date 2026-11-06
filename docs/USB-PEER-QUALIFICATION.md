# USB2/USB3 peer-port investigation and offline qualification plan

This candidate performs **read-only assessment only**. Paired USB resetting is
not enabled or supported by its executor. No physical USB isolation or power
control result is claimed for the Ubuntu Studio computer. Normal filesystem
remounting remains available with USB resetting off.

## Kernel findings

Linux describes USB2 high-speed and USB3 SuperSpeed peers as logical interfaces
of one connector, distinct from older companion-controller switchovers. Firmware
location data may identify the pairing; the kernel can also use fallback pairing.
A peer link therefore does not prove that isolation is impossible. Runtime port
power management sequences USB2 off before USB3, and USB3 on before USB2, to
prevent fallback to the other interface. Logical power-off does not guarantee
VBUS removal: shared power circuits or charging behavior can maintain it.
[Kernel USB power-management documentation](https://docs.kernel.org/driver-api/usb/power-management.html).

The Linux 7.0 port implementation creates reciprocal peer links. Its individual
`disable` writer disconnects the selected port's child and changes that port's
power state; it does not perform a paired transaction. The runtime-PM ordering
cannot be assumed to make two userspace `disable` writes atomic or crash-safe.
[Linux 7.0 port implementation](https://github.com/torvalds/linux/blob/v7.0/drivers/usb/core/port.c).
The ABI says VBUS control depends on hub power-switch support. A visible control
file alone does not establish independent electrical switching.
[Linux 7.0 USB sysfs ABI](https://github.com/torvalds/linux/blob/v7.0/Documentation/ABI/testing/sysfs-bus-usb).

## What RC2 changes

The read-only assessment checks reciprocal direct-root-port links, a common PCI
controller, USB2/USB3 root-hub speeds, both individual control attributes and an
unoccupied peer. It distinguishes a recognized but unqualified pair from an
unreadable/dangling mapping, different controller, downstream hub, missing
control, wrong speed pairing or attached peer device. A recognized pair is
reported as a possible shared connector, not as proof of either electrical
isolation or impossibility. Firmware and physical wiring still need verification.

The existing profile, action budget and cleanup ledger represent **one logical
port**. They cannot account safely for two disable operations, fallback
enumeration, an interruption between writes, or two independent re-enable
obligations. Consequently RC2 still refuses paired resets and cannot save a
paired qualification. This is a software support limit plus missing physical
proof, not a finding that the Ryzen hardware is incapable of isolation. The
single-port runtime refusal remains; no hub/controller reset fallback was added.

## Decision for a future paired implementation

A connector-scoped operation appears technically possible when both exact root
ports can be pinned, have independent controls, and are proven to affect only
that physical connector. This is an engineering inference, **not a qualification
of the reported machine**. The pair must be treated as one incident action with
two durable re-enable obligations, not as two independent retries. Both sides
must be absent before either disable, and both must be restored after any
interruption. Identity checks must handle the same disk returning at either
speed while rejecting any different device. Replacing a profile must not erase
a pending re-enable obligation. No operation may fall back to a controller,
root-hub, external-hub, authorization or driver-unbind reset.

Shared/ganged switching that requires affecting other connectors, missing
independent controls, uncertain physical mapping, an unrelated attached peer,
or inability to restore both interfaces independently means **do not qualify**.
Electrical isolation cannot be established remotely from the reported message.

## Later user-supervised offline procedure

The following is a test protocol for a knowledgeable operator, not instructions
to run a live reset now. RC2 provides no paired reset tool. Do not begin the
active phase until a separate paired test harness with independent restoration
of both interfaces has been reviewed. Do not alter sysfs manually to bypass the
RC2 refusal or attest QUALIFIED for a paired port in this version.

1. Arrange downtime and a dedicated expendable test disk, with a separately
   verified backup. Inventory storage mounts, container namespaces, loop devices,
   swap, open handles and mapped files. Stop all consumers and monitoring, finish
   outstanding incidents/re-enable obligations, and cleanly release all uses.
   Never force an unmount or test against production data.
2. Collect read-only evidence: kernel/systemd versions, controller PCI IDs and
   driver, both root-hub IDs, reciprocal canonical peer paths, speed classes,
   firmware/connector/location data, both disable/state values and bridge serial,
   VID/PID and filesystem UUID. Keep the resulting identities private.
3. Map the physical connector with supervised plug/unplug observations of the
   expendable device in USB2 and USB3 modes. Confirm both paths belong to that
   connector and no downstream hub or unrelated device sits on either side.
   A kernel default peer pairing is insufficient evidence by itself.
4. Inspect both hub descriptors for power-switch characteristics and obtain
   board/controller documentation where possible. Use appropriate electrical
   measurement if electrical power interruption is claimed. A state/disable
   readback proves logical state, not VBUS loss or disk power loss. Externally
   powered enclosures may retain power independently.
5. Establish harmless canary observations on other connectors with all storage
   unmounted and no production consumers. The reviewed harness must pin only
   the selected pair, check absence immediately before writes, record intent
   durably, and start a separate enable-only guardian before any disable.
6. In the active test, evaluate USB2-off then USB3-off, followed by USB3-on then
   USB2-on, while verifying every result. This is a proposed sequence informed
   by kernel runtime-PM behavior; its direct-disable implementation and the
   hardware must be tested, not assumed equivalent. Confirm that no unrelated
   connector loses connectivity or power. Stop if any cannot be proven.
7. Test interruption after each durable stage and each individual write; verify
   both interfaces return enabled even when the main test process exits. A
   failed re-enable must remain recorded and block further recovery. Never
   repeat a disable to compensate for an uncertain first result.
8. Verify the exact same disk returns at the expected connector, including
   fallback-speed cases. Only after restoration and identity verification,
   mount normally and verify test-data hashes. Retain failed and successful
   outcomes, timings, readbacks, unaffected canary evidence and restoration logs.
9. Submit that evidence for review of a future pair-aware profile, executor and
   cleanup implementation. Do not turn on paired recovery in RC2. A pass on one
   board/port/bridge/cable combination does not qualify another.

No commands or hardware tests in this plan have been run on either external
computer by this development work.
