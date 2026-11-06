> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI10 — TEST ONLY

UI10 addresses the eight findings from UI9 testing. Existing configurations and
image files are retained. This update does not implement new Docker monitoring.

## Changes to test

1. **Drive type and standby:** Overview and Manage Drive show **HDD sleep: Not
   supported** for flash/SSD and other storage without a positively identified
   supported mechanical HDD. A known HDD retains its activity/standby status.
   No new disk-waking query is used for status.
2. **Add USB drive:** the button is blue, distinct from purple management/save
   buttons. Its dialog's Add drive action uses the same blue.
3. **Spacing:** Docker & Applications has a gap between the information banner
   and drive selector. Event History has a gap below its drive filter.
4. **Mount on recovery:** rapid taps update the switch immediately. Saves run
   one at a time and coalesce queued choices; the last choice wins after successful
   completion. The row shows Saving, Saved, or a save error. A failed/interrupted
   write is not automatically retried. The app reads back the current preference
   if possible. Manual mounting/unmounting stays independent.
5. **Prepare Drive:** ongoing work has a black background, yellow text/border,
   and an activity indicator. Formatting remains destructive and requires the
   existing explicit disk-erasure confirmation.
6. **LAN access:** enable/disable waits for the host's verified result from the
   localhost dashboard. The confirmation locks against duplicate submissions.
   Temporary status-read failures do not produce a toast storm. Advanced Settings
   shows the last network result. If a remote browser disables its own listener or
   changes its protocol, the page explains that completion must be checked from
   **http://localhost:8765 on the host** (or the new LAN URL). A queued/lost
   response is never presented as verified success. No write is automatically
   retried. LAN shutdown verification checks both service state and its main PID.
7. **Reconnect refusals:** known topology refusals are recorded before stopping
   monitoring or unmounting. If topology changes between the broker and the worker,
   an explicitly verified pre-unmount refusal restores the prior monitoring state.
   Post-unmount and uncertain failures retain the existing guarded behavior.
   The message now names the selected port, paired port and attached peer device.
8. **Messages:** notifications no longer stack over buttons or switches. A stable
   bar above the page shows one message; **Messages** opens the full recent history
   (up to 100 entries, repeated identical messages coalesced). Ordinary successes
   clear after a few seconds; errors remain available in history. Rapid recovery
   preference changes use the inline status instead of a toast per tap. Page
   controls do not move when a notification appears or disappears.

## USB reconnect limitation

This build does not bypass an occupied or unverified USB2/USB3 peer. It cannot
establish from a screenshot whether that peer is correctly associated with a
physical connector, a second attached device, or changing USB enumeration.
Front-panel versus rear motherboard placement alone does not establish isolation.
If the refusal remains, retain the new full port/device message for the next test
report. Ordinary remount recovery remains available. The build does not claim
electrical power removal, and cannot switch off a separate enclosure power supply.

The relevant kernel interfaces distinguish the peer relationship and the child
device attached to a port:
- https://docs.kernel.org/driver-api/usb/power-management.html
- https://code.googlesource.com/linux/torvalds/linux/+/7bcf809b1e7889ab7e75fe1fcf8f1a98332f36d2/drivers/usb/core/port.c

## Host acceptance sequence

- Install the UI10 package, reload with Ctrl+Shift+R, and verify the sidebar says
  UI10. Existing monitoring, image and recovery preferences should remain.
- Visit both flash drives and the HDD in Overview and Manage Drive. Check labels,
  live activity, and that HDD sleep retains the original monitoring state.
- On an image, tap Mount on recovery rapidly, end on the intended state, wait for
  Saved, then refresh. Repeat ending on the opposite state. Mount and unmount the
  image and verify the preference stays unchanged.
- Review messages while using switches, buttons and dropdowns on different pages.
  Confirm the information stays readable through Messages without blocking work.
- From localhost, enable and disable LAN and verify the final setting from another
  device. Then try disabling LAN from a remote page: its connection closing is
  expected, and the host's localhost dashboard must remain available. Check the
  last network change there. Also test HTTP/HTTPS if you use both.
- Test manual reconnect only with the usual disposable test storage and no active
  file users. On a preflight refusal, check that mount and monitoring state remain
  as before. Record the selected/paired ports and device name if still refused.
- Check spacing and the blue add button. If already doing a deliberate formatting
  test on disposable storage, verify the black/yellow ongoing status row.
- Repeat the known working remount/image recovery and notification test, then
  leave the dashboard running to check stability. Begin Docker monitoring work
  only after this build is accepted.

See the release TEST-RESULTS.txt for automated coverage and environment limits.
No physical user drive, live Ubuntu service, SMTP account, or production Zorin
installation was operated during this development run.
