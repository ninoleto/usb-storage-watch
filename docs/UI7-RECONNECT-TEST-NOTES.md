> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI7 — TEST ONLY: reconnect results and safety-check timing

This build continues UI6. It fixes misleading manual-operation feedback and
separates process inspection from the actual USB-write timeout. It does not add
verified electrical power switching. Physical testing is still required on the
Ubuntu Studio test computer. Do not install on production Zorin.

## User-visible changes

- The action is named **Reconnect USB (software)**. Both the drive page and the
  confirmation explain that power removal is unverified and that USB control
  cannot switch off a separate disk power supply.
- A backend response containing `ok: false` produces a red error message. It is
  no longer displayed as a successful operation simply because HTTP returned 200.
- The last recorded operation stays visible on the selected drive page, including
  its outcome, details and timestamp. Successful USB return still requires the
  expected hardware and filesystem identity; enabled-port readback alone is
  insufficient.
- Drive status and history refresh after operations. A subsequent status-read
  failure is reported separately and cannot turn a successful operation into a
  failed one. No automatic retry is sent by the browser.
- Recent-events buttons wrap correctly on narrow screens.

## Reconnect worker changes

- Identity and isolation checks have a 15-second budget in the supervised disable
  worker. The old 3-second limit included these checks and could expire before
  any USB write.
- The USB-write/readback phase retains a separate 3-second limit, bounded by an
  18-second total worker budget. Progress updates cannot renew that limit.
- The enable guardian's lifetime covers the longer inspection budget. Existing
  enable-only cleanup, pending obligations, per-port locking and reset budgets
  remain enforced.
- Slow inspection records its stage and, periodically, the process ID and kind
  of inspection. No process command line or file contents are recorded.
- A timeout before a disconnect write reports that reconnect was not performed.
  An enabled port does not imply that a disconnect or power cycle occurred.
- Unreadable live processes, busy files, wrong hardware, occupied companion
  ports and unknown identities continue to refuse the operation. No permission
  checks were removed and no service privileges were broadened.

This timing correction is a candidate fix for the reported inspection timeout,
not proof that the physical machine now reconnects successfully. Real permission
errors will still require diagnosis rather than being silently bypassed.

## Electrical power is a separate capability

`uhubctl` reporting **No compatible devices detected** means it did not detect
a compatible power-switching hub in that run. A USB disconnect or a hub status
bit does not prove loss of VBUS. An independently powered SATA disk also needs
control of its own power supply to lose electrical power.

This release never invokes forced or recursive `uhubctl` operations and never
controls an entire USB controller. `power_cycle_available` and
`electrical_power_cut_verified` remain false. The existing hardware descriptor
and `power_off_reported` fields are diagnostic information, not electrical proof.

References:

- <https://github.com/mvp/uhubctl#compatible-usb-hubs>
- <https://docs.kernel.org/driver-api/usb/power-management.html>

## Physical acceptance

1. Upgrade on the Ubuntu Studio test machine only. Keep the UI6 archive.
2. Verify existing profiles, mount paths, image preferences and history. Inspect
   the new software-reconnect label and power notice without operating a drive.
3. For a deliberate test with expendable storage, close files and dependent
   applications first. Do not format, erase, or modify a data-bearing disk.
4. Check that the final on-screen result matches Recent events and that other
   drives are unaffected. A refusal must remain an error; monitoring may remain
   paused and the selected drive may remain unmounted after a failed attempt.
5. If inspection still times out, retain the exact new stage from the error and
   the selected drive's event record. Do not repeatedly retry to force a result.

Production migration, real USB power loss, real HDD standby, live Docker/SMTP,
and physical reconnect reliability have not been certified by cloud tests.
