> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch UI9 — TEST ONLY

This build addresses the UI8 testing reports. Install on the Ubuntu Studio test machine; physical acceptance is still required before production use.

## Changes and expected behavior

1. **HDD standby controls stay visible.** The section remains in Advanced Settings for every selected drive. Its switch, minute value, minus/plus, Reset and Save controls are disabled when HDD standby does not apply. Selecting flash storage no longer removes the section.
2. **All dropdowns have large touch targets.** Open menu rows and closed controls are at least 48 pixels tall. Keyboard arrows, Home/End, type-to-find, Enter and Escape work. Long selected names do not change the control height.
3. **Timing settings use vertical rows.** Each setting has minus/value/plus/Reset controls and explanatory text beside it on wider screens, below it on narrow screens. Single dividers separate settings; a double divider separates Drive monitoring from USB recovery. HDD standby follows the timing Save button with matching controls.
4. **Refresh events works on Manage Drive and Event History.** Correct the invalid selector; retain the selected history filter.
5. **Image mount state and recovery preference are independent.** Mount image and Unmount image leave Mount on recovery unchanged. Changing the preference leaves the current mount unchanged. An intentionally unmounted image stays unmounted during normal healthy-drive monitoring; the next recovery mounts it if its preference is enabled. A disabled image is excluded from automatic image recovery even if mounted manually. Busy-process, nested-mount, identity and read/write checks still apply. Disabling a required recovery dependency is still refused.
6. **Overview shows passive HDD status.** In use, Idle, Spun down, Unknown or Status pending appear as appropriate. SSD/flash storage shows HDD sleep: Not supported. Idle does not mean spindle stop. Only a confirmed standby request with unchanged connection and no subsequent block I/O is presented as Spun down.
7. **Administration availability is hardened.** Event-history SQLite connections close explicitly rather than depending on garbage collection. Background observation runs separately from the accept loop, with at most one observer. Request workers and lock waits are bounded; socket resource exhaustion backs off and warnings are rate limited. Reads have shorter connection/response timeouts. Busy disk commands are refused rather than queued or retried. Monitor services retain their independent operation.
8. **Recovery badges use the requested colors.** Enabled is green; disabled is gray.
9. **Companion token state updates immediately.** Creating and copying a restricted token makes Revoke available without a page refresh or drive change. Other drives retain their own tokens.
10. **Manage Drive refreshes activity automatically.** Overview, Manage Drive and event history poll every 15 seconds while idle, without overlapping polls, replacing forms or retrying a disk operation. Closely spaced passive samples no longer erase an established activity state. Busy actions and open dialogs/menu selections defer polling.

Manual HDD sleep retains UI8 behavior: monitoring and its startup preference remain unchanged on success or refusal. Pending writes are flushed before a bounded quiet check; active users or continued I/O can still prevent sleep. Normal file access can wake a mounted disk.

## Evidence and limits

The UI8 hardware report already demonstrated successful recovery of the primary ext4 filesystem and its configured image, verified read/write, with an email delivered. It used no USB reset. The user's later sleep event also showed monitoring stayed ON. UI9 automated tests preserve these paths with synthetic hardware boundaries; they are not another physical recovery test.

The old freeze logs showed a running administration process with high CPU and repeated observation errors, while drive monitors remained running. A real connection-lifetime defect was reproduced in UI8: with garbage collection disabled, 1,000 history captures retained 1,000 database descriptors. UI9 closes them deterministically. The logs do not prove this was the sole cause of the original freeze. A long-running test on the Ubuntu host remains necessary.

See the accompanying TEST-RESULTS.txt for exact automated coverage, the pre-existing /proc child-process test limitation, and the Unix-socket test skipped by this execution environment. Hardware spindle behavior, real USB interruption, live service availability, Docker and SMTP were not exercised by this build.

## Ubuntu Studio acceptance

- Upgrade from UI8, then Ctrl+Shift+R and verify UI9 in the sidebar. Keep the UI8 ZIP for rollback.
- Switch between HDD and flash storage in Advanced Settings. The standby section should remain in place, with disabled controls for flash. Test dropdown rows and timing controls by touch.
- Write to the HDD with Manage Drive open. Allow one 15-second poll after any dialog closes; In use should update without a page refresh. Overview should show the same passive state. When writing stops, Idle is expected; it is not proof of sleep.
- Refresh recent events and the filtered history. No selector error should appear.
- With Mount on recovery ON, unmount an image. The switch must remain ON, and normal monitoring must leave the image unmounted. Mount it again and confirm the switch is unchanged. Repeat with the switch OFF. For a deliberate recovery test, stop application activity first and verify that only enabled image dependencies return.
- Create/copy a restricted Companion token. Revoke must become available immediately. Revoke the test token when finished.
- Request HDD sleep with monitoring ON. Confirm monitoring stays ON, including if sleep is refused. Verify spindle behavior on the actual bridge; subsequent file access may wake it.
- Leave monitoring and the dashboard running through normal use and recovery testing. If administration stops responding, capture service status and recent logs before restarting it. A test-build UI result alone does not establish that the old freeze is eliminated.
