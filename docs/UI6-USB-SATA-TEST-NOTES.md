> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI6 — TEST ONLY: USB-to-SATA mechanical HDD support

## Reported physical case

EXAMPLE SATA DISK (465.8 GiB), data through USB-to-SATA adapter, power through PC PSU.
`lsblk` identifies the transport as USB while udev reports `ID_BUS=ata`,
`ID_SERIAL_SHORT` and `ID_WWN`. A verified USB path and matching serial
must be used instead of interpreting ID_BUS as the physical connector.

## Scope

- Disk preparation recognizes **only real USB-attached** disk sysfs nodes,
  and still requires an unmounted, unclaimed disk with a unique serial and
  administrator-confirmed erase operation. ATA/WWN by-id paths are accepted
  only when the target is present in the USB-only inventory and its kernel
  ancestry and identity agree. No change to the destructive confirmation.
- USB reconnect discovery and passive HDD standby allow the same verified
  ATA-over-USB topology without treating the ATA property as a direct SATA
  connector. Hub and shared-port protections are unchanged.
- Passive HDD classification uses a positive ATA rotation rate or, when that
  field is absent, kernel rotational flag + native ATA identity and WWN;
  a rotational flag alone **never** certifies a flash drive as mechanical.
- NTFS is not supported for monitoring, virtual disk recovery or automatic
  standby. The example drive currently has NTFS and cannot be monitored without
  deliberate ext4 preparation. This build will not format it automatically.
- This does not guarantee that the bridge supports hdparm -y/-C; physical
  standby must be verified separately, and USB reset is never evidence of
  removing the externally supplied electrical power.

## Safety constraints

- No write or operation is performed by read-only inventory/status.
- All existing configuration, profiles, virtual disk images and service state
  remain unchanged during upgrade.
- Physical tests only on Ubuntu Studio; never touch Zorin.
