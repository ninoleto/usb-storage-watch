> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI10 FIX1 — TEST ONLY

This patch fixes the Prepare Drive row that kept spinning after successful formatting.
The formatter reports `ready`; UI10's renderer only recognized `complete` and
`failed` as terminal phases. The progress polling already recognized `ready`.

The corrected row shows:

- Active preparation stages: black background, yellow text and an animated spinner.
- Ready: green completed result with a checkmark and no spinner.
- Failed: red failure result with a warning icon and no spinner.
- Unknown or idle phase: neutral result without claiming activity.

The last result remains readable. Completion is shown both when polling finishes
and when returning to Prepare Drive. There is no formatting-backend change.

## Check after upgrading

Reload the dashboard with Ctrl+Shift+R and confirm UI10 FIX1 in the sidebar.
Open Prepare Drive: the existing Ready result should have a green checkmark and
no spinner. The previous result can be checked without formatting again.

Browser regression checks use synthetic APIs at 320, 390, 768 and 1440 pixels.
See the release TEST-RESULTS.txt for the actual validation performed. Physical
formatting and USB reconnection are not exercised by these browser checks.

All UI10 changes remain in this patch. Keep the UI10 ZIP for rollback. Docker
monitoring development remains deferred until the UI passes host acceptance.
