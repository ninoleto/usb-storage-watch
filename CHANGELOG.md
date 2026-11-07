## 2.0.1 beta 4

- Identify exact Compose/environment files and ancestor directories rejected by
  permission checks, with ownership, mode and relevant group membership.
- Offer authenticated one-use reviews to remove group/other write bits from an
  eligible configuration file. Pin file/container identities, preserve other
  permissions and media, and rerun normal setup validation before any app save.
- Explain directory/shared-access and other unsupported cases without guessed
  permission changes or generic command walls.
- Keep unsaved startup/recovery visibly Not configured; show saved enabled header
  badges with a success-green border, including collapsed cards.
- Companion 0.2.6, recovery engine and existing storage safeguards are unchanged.

## 2.0.1 beta 3

- Verify registered descendant image mounts during recovery planning instead of
  rejecting them solely for being mounted. Keep the actual remount guard strict.
- Return actionable, sanitized email-setup refusals before changing monitoring
  or notification settings; keep service failures distinct.
- Exercise fresh registration, adoption, monitoring, recovery and email setup with
  disposable actual mounts and localhost SMTP TLS, plus simulated refusal cases.
- Companion 0.2.6 is unchanged; previous release tags/assets are retained.

## 2.0.1 beta 2

- Fix first-time HTTPS preparation when no saved certificate exists, retaining
  certificate/hostname verification, exact-origin confirmation and rollback.
- Report network preparation, pending confirmation and failures accurately.
- Adopt verified, already-mounted fstab ext4 images through GUI review without
  changing their mounts, fstab, contents or permissions.
- Publish GitHub-compatible asset names and a matching three-asset checksum manifest.
- Companion 0.2.6 and recovery behavior unchanged.

## UI40 — verified upgrade lifecycle

- Stop the broker supervisor before its listeners; verify stopped state and
  worker counts before allowing unpack. Refuse failures and incompatible broker
  restart overrides instead of reporting success.
- Normal and failed-upgrade hooks use the same embedded preparation helper,
  available before the new payload is installed. Repeated preparation retains
  the original active-service receipt; upgrading does not enable a disabled LAN.
- Document configuration-only registration of an existing fstab loop image.
  No image-import feature, recovery-engine or Companion changes.

## UI39 — manual app storage readiness

- Verify the union of saved startup/recovery drives and images before manual
  Start/Restart, including retained choices with automation disabled.
- Use existing filesystem verification and storage-before-app locks. Reject
  unavailable storage or changed settings without Docker commands or cleared holds.
- Keep Stop, unrelated apps, authentication and automatic recovery unchanged.
- Update installation examples; bundle the unchanged Companion 0.2.6 archive.

## UI38 — focused Integrations cleanup

- Link directly to existing token and network settings; token replacement stays
  in Advanced Settings and certificate download stays in Network Settings.
- Copy the complete public certificate while keeping its text collapsed by default.
- Keep the unchanged Companion 0.2.6 download on the dashboard's own origin.

## UI37 — current Companion setup

- Active server URL, existing management-token controls, full public CA PEM and
  verified module download. No drive selector or extra credentials.
- Remove obsolete Companion v1/standby bearer routes and token issuers/verifiers.
- Keep current session/CSRF authentication, one-press guarded controls and the
  unchanged Companion 0.2.6 package. No recovery or startup engine changes.

## 2.0.0~ui36 — TEST ONLY (outcome history and saved app indicators)

- Display and sort completed history by the actual outcome timestamp, with the
  original outage time shown separately. Preserve timeout and later recovery.
- Keep original event timestamps and incident evidence; derive presentation
  metadata without rewriting the underlying outage records.
- Show saved startup/recovery settings in collapsed app headers, independently
  of runtime state and drafts. Unavailable settings are explicitly unknown.

## 2.0.0~ui35 — TEST ONLY (drive return deadline)

- Add a per-drive five-minute default return timeout from confirmed outage,
  persisted across monitor restart/reboot without renewing the budget.
- Record one timeout failure through the existing notification/retry queue;
  preserve cleanup, stop receipts and remaining recovery/reset budgets for return.
- Show the backend countdown and timeout state, keep affected apps protected,
  and retain separately timestamped timeout history after later recovery.

## 2.0.0~ui34 — TEST ONLY (explain deliberate app stops)

- Show a Docker Apps link when current storage and pinned stopped app identities
  verify a same-boot safe-unmount hold. Clear the notice when its evidence expires.
- Verify selected physical filesystems and optional images, including shared-drive
  and boot choices. Unavailable Docker/storage/status never becomes a ready claim.
- Keep monitoring status independent; no automatic starts, preference changes,
  hold release, or recovery/startup behavior changes.

## 2.0.0~ui33 — TEST ONLY (repeated safe unmount correction)

- Recognize the owning broker's unmount lock during admission; a retained earlier
  receipt must not make a new reviewed operation block itself.
- Preserve real competing-operation locks, recovery restrictions, same-boot
  deliberate stops and pending-start suppression. Do not delete or migrate receipts.
- Keep progress visible and duplicate confirmation disabled while running; require
  a fresh review after a refused or uncertain one-use confirmation.
- Exercise the authenticated frontend/broker and real worker subprocess/lock/JSON
  path with isolated storage and Docker fixtures, including remount/manual starts
  and a later ordinary-folder app addition.

## 2.0.0~ui32 — TEST ONLY (reviewed safe unmount and selector contrast)

- White 2 px borders and white arrows on enabled blue dropdown fields; retain
  dimensions, disabled feedback and keyboard/touch focus.
- Review pinned dependent app identities and selected images before safe unmount.
  Stop and verify selected apps before the existing busy-storage/image/disk guards.
- Serialize app actions/settings and retain same-boot deliberate stops across
  shared recovery and pending boot startup. Manual Mount never starts apps.
- Keep selections, intentional-unmount monitoring semantics and repeated recovery.

## 2.0.0~ui31 — TEST ONLY (complete app locks and blue selectors)

- Disable every affected app-card control during recovery, including secondary
  draft/identity actions; keep status updating and show an undimmed amber notice.
- Give disabled switches a neutral appearance; retain drafts, selections and
  expansion. Keep open confirmations current and refuse stale mutations.
- Cover new identity selections in legacy editors with cross-drive incident guards.
- Use the existing Docker-header blue for dropdown fields throughout the app.
- Document an optional default-off reboot-after-failure proposal; no reboot behavior added.

## 2.0.0~ui30 — TEST ONLY (recovery controls and boot-email diagnostics)

- Refuse manual app actions and conflicting settings throughout active incidents,
  using exact identities, current state and existing container locks. No queued commands.
- Keep read-only status and unrelated apps usable; terminal incidents release the
  restriction only when no other active incident affects the same app.
- Nest independently saved HDD standby controls inside Timing & recovery.
- Retain allowlisted notification errors, exit status and attempt identity/time;
  keep startup receipts terminal and do not add email retries.

## 2.0.0~ui29 — TEST ONLY (image hierarchy and unavailable apps)

- Darker nested image selectors retain independent expansion across edits,
  refreshes and browser reloads, showing selected image counts and names.
- Rename the panel to Drive failure & recovery and clarify optional images.
- Group missing saved IDs compactly, with reviewed explicit-ID reconnection and
  removal of Storage Watch settings only. Existing destinations cannot be merged
  or overwritten. Backups and recovery history are retained.
- Docker failure means unknown status, never a missing identity or cleanup signal.

## 2.0.0~ui28 — TEST ONLY (app startup and recovery interface)

- Separate touch-friendly Computer startup and Drive recovery panels; independent
  switches retain their selected drives and optional images while off.
- Compact manual app controls, collapsed Advanced details and one Review changes
  → Save settings flow. Reuse authenticated exact-ID policy/Compose confirmation,
  backups and readback; show partial saves and external-manager instructions.
- Keep ordinary-folder support, recovery engine, boot-once receipts and network
  behavior. Warn beside selected drives with unavailable recovery prerequisites.

## 2.0.0~ui27 — TEST ONLY (automatic network address)

- Add explicit Automatic/Manual network address modes, physical-interface selection and verified URLs.
- Follow address changes through the existing network transaction/rollback machinery; keep localhost independent and wait without failed-start loops when no address is eligible.
- Preserve HTTPS issuer trust for renewed addresses; require explicit acknowledgement for otherwise necessary trust replacement. Never downgrade HTTPS.
- Keep virtual/VPN interfaces available for Manual selection; do not change host networking or storage/container settings.

## 2.0.0~ui26 — TEST ONLY (guided container setup)

- Display live restart policy, deployment manager, explicit boot/recovery prerequisites and policy conflicts.
- Confirm a restart-policy-only Docker update without container recreation or restart; retain the original policy.
- Validate Compose source identity, ordered overrides and effective configuration; preview and back up only the selected service restart field. Refuse ambiguous sources and preserve uncertain outcomes for review.
- Use “Start automatically when the computer starts”; keep ordinary external folders fully supported with optional images.
- Preserve UI25 USB, reboot and disk-recovery behavior; no completed physical tests are repeated for this release.

## 2.0.0~ui25

- Manual USB reset requires unmounted storage and leaves it unmounted; monitoring is unchanged.
- Verify the same returned disk on a previously captured USB2/USB3 companion without resetting the companion. Add guarded leaf-device reset where port reconnect is unavailable.
- Display live USB topology/address/identity, mounted-state controls and reset capability.
- Add opt-in container startup once per boot with separate explicit disk/image prerequisites and durable action receipts. Existing recovery selections and UI24 cleanup remain unchanged.

## 2.0.0~ui24 — TEST ONLY (successive recovery incidents)

- Scope completed cleanup command history, retry counters and pending-loop continuation to the incident that created them.
- Archive validated settled older cleanup records instead of applying their mount identities to a later outage.
- Preserve blocking of malformed/uncertain receipts and duplicate commands within the same incident.
- Resume the reported completed UI23 no-action failure after upgrade and fresh verification.
- Add repeated recovery cycles with deliberate mount/device identifier reuse.

## 2.0.0~ui23 — TEST ONLY (failed-mount namespace correction)

- Remove the cross-namespace availability requirement before an ordinary unmount of the freshly verified configured failed mount tree.
- Preserve stopped-container checks, exact current mount identity, normal unmount results, returned-device checks and loop-detach guards.
- Resume the reported completed UI22 namespace refusal with no storage commands after fresh verification.
- Include device, process and mount location in remaining namespace refusals.

## 2.0.0~ui22 — TEST ONLY (automatic failed-mount release)

- Stop selected containers, verify they are stopped, then normally unmount the configured failed image/disk mounts before storage recovery.
- A freshly verified disconnected shutdown mount no longer requires a healthy mount identity recorded by an older release.
- Preserve exact mount, configured image, container and returned-device checks. No force/lazy unmount or filesystem repair.
- Resume eligible settled older incidents, including the UI21 wait, through the automatic sequence.
- Mount the disk and selected images, start selected containers and verify the result before the final notification.

## 2.0.0~ui21 — TEST ONLY (legacy incident recovery)

- Resume a completed failed incident from before UI20 after a fresh failure observation, preserving its history.
- Stop selected containers before recovery and wait without spending a mount attempt while an unproven old mount remains.
- After a one-time normal release of that old mount, continue disk mount, selected virtual images, container start and final email.
- Show the reason for waiting beneath drive controls. Existing UI20 behavior and visual changes are retained.
- A missing historical mount identity is not invented. Automatic cleanup still requires a recorded healthy identity.

## 2.0.0~ui20 — TEST ONLY (disk and container recovery sequence)

- Stop selected containers at the first detected disk failure, before recovery.
- Wait for disk return; handle owned stale mount trees after USB-port changes.
- Mount selected images before starting the selected containers; queue the final outcome afterward.
- Distinguish Docker daemon refusals from uncertain transport results.
- Show one current action result, dark green Start monitoring, dark blue container headers, and 24-hour timestamps.
- Preserve manual container controls, editable Docker choices, image controls and network settings.

## 2.0.0~ui19 — TEST ONLY (detached mount recovery)

- Record a healthy mount identity and USB attachment for narrowly scoped
  cleanup of its detached, shutdown mount after a drive returns.
- Use one normal unmount after revalidation, then existing filesystem, image
  and selected-container recovery. Preserve failed/uncertain-operation limits.
- Distinguish an occupied/conflicting mount location from an unmounted drive,
  and report actual/expected devices and the original recovery blocker.
- Put long action errors across the action row or dialog width, with labels
  identifying the relevant control.
- Keep UI18 Docker Start/Stop/Restart and previous image/network fixes.

## 2.0.0~ui18 — TEST ONLY (manual container controls)

- Add the previously agreed manual Start, Stop and Restart controls to each
  detected container card. Monitoring and automatic restart choices do not
  control their availability.
- Show pending and final results at the controls. Verify the selected container
  identity and runtime state without changing its configured storage.
- Serialize manual and recovery operations for the same container, and do not
  repeat a command after a lost response.
- Retain UI17 image creation/mounting fixes, local action feedback, separated
  image removal, and clearer disk/image/container dependency explanations.

## 2.0.0~ui17 — TEST ONLY (image operations and local action feedback)

- Correct shared configuration-lock ownership in manual virtual-image operations.
- Honor explicit manual image mounting independently of automatic recovery.
- Put progress, completion and errors beneath the relevant action controls.
- Report partial creation clearly and prevent a consumed confirmation from
  submitting the same creation again.
- Separate virtual-image removal from normal actions and explain detected
  Docker image dependencies without imposing them on restart choices.

## 2.0.0~ui16 — TEST ONLY (container-first restart settings)

- Replace drive-first Docker page with detected container cards, per-drive
  switches, optional image choices and independent saves.
- Add remembered collapsible headers; preserve drafts during polling/collapse.
- Permit Docker settings changes with monitoring either on or off.
- Treat detected bind storage as advisory; attempt selected image mounts and
  continue selected restarts after image failures.
- Restart explicitly selected containers after successful drive recovery,
  including previously stopped containers, with bounded durable action records.
- Preserve earlier network, drive-removal and touch interface improvements.

## 2.0.0~ui15 — TEST ONLY (Docker restart controls and audit)

- Describe Docker actions as restart after drive recovery, with explicit results
  for restarted, started after exiting, and intentionally kept-stopped containers.
- Explain automatically detected required storage and move existing folder
  mappings into details; remove misleading single-choice storage selection.
- Distinguish saved configuration from drafts, validate empty selections locally,
  and protect settings/status displays against stale asynchronous responses.
- Separate Remove from Storage Watch from everyday controls on desktop and mobile.
- Retain required-storage verification, bounded Docker actions, UI13 network
  settings and UI14 drive retirement behavior.

## 2.0.0~ui14 — TEST ONLY (remove managed drives)

- Add Remove from Storage Watch to overview cards and Manage Drive, with an
  identity-bound confirmation that explains files, mounts and app dependencies.
- Stop and disable only the selected monitor, verify worker/USB cleanup state,
  and atomically retire its configuration while retaining private history.
- Support disconnected drives, the legacy profile, the last remaining drive,
  and later explicit re-addition with fresh settings and a new profile identity.
- Reject retired-profile and integration-token requests; keep shared dashboard
  login, network/SMTP settings and other drive profiles unchanged.
- Reconcile overview cards and selection caches with complete server lists;
  ignore older in-flight lists after a removal and verify lost responses without
  automatically repeating a removal request.
- Retain UI13 network layout, certificate guides and modal touch pickers.

## 2.0.0~ui13 — TEST ONLY (RF network interface and touch picker correction)

- Fix Apply remaining disabled when a new HTTPS endpoint needs a trust certificate.
  Apply prepares missing certificate material; input errors are stated beside it.
- Use the RF433 Button Manager test.5 network card, spacing, URL cards, protocol
  choices, full-width port resets, and six expandable certificate import guides.
- Replace every dropdown with a scrollable modal picker with large option cards,
  keyboard navigation, focus containment, and an explicit close button.
- Remove native number-input spinner arrows throughout the interface.
- Download the public trust certificate as an importable .crt file; add server
  certificate renewal with the existing issuer and durable rollback on failure.
- Keep UI12 per-container storage dependencies and prior drive/UI fixes.

## 2.0.0~ui12 — TEST ONLY (RF-style network settings and storage-specific Docker recovery)

- Stage network changes while retaining saved listeners. Require authenticated confirmation from the exact proposed URL within three minutes; cancel/timeout/restart retains the previous configuration.
- Match RF Button Manager network URL cards, HTTP/HTTPS choices, grouped server address and touch port controls, certificate guidance, and pending-connection panel. Keep USB Watch defaults 8765/8766.
- Retain a private local certificate issuer across address changes. Publish only its public trust certificate; update the desktop launcher after confirmed localhost port changes.
- Infer required images from each container's bind folders, including additional binds and nested image prerequisites. A missing unrelated backup image does not block a direct-folder container.
- Restart a previously running container even when it is still running. Retain stopped-container preservation, identity checks, read-only access checks and one-action-per-incident limits.
- Preserve accurate partial-storage outcomes, block missing/disabled image fallback directories, and show Required storage beside container settings and current state.
- Add isolated backend transaction/dependency tests and Chromium handoff coverage; actual Ubuntu network and Docker outage acceptance remains required.

## 2.0.0~ui11 — TEST ONLY (Docker recovery controls and remaining UI fixes)

- Expose per-drive Docker selection, explicit enable/disable, fresh save validation, live metadata status, historical recovery results, and a bounded read-only access check.
- Require stopping the selected monitor before configuration edits and make restarting it explicit. Preserve selections while Docker is unavailable; allow disabling without rediscovery.
- Refuse folders underneath absent or disabled image mounts and retain the single-drive owner rule for selected containers.
- Track independent timing/standby drafts and confirmed saves; keep edits made during an in-flight save.
- Add Clear messages, inline event-refresh feedback, a mounted-drive change-location guard, and a stronger Start monitoring border.
- Add synthetic backend tests and Chromium workflows at 320, 390, 768, and 1440 px. Live Ubuntu Docker outage acceptance remains required.
- Retain existing storage recovery and Docker lifecycle safeguards; no general container watchdog or destructive container controls are added.

## 2.0.0~ui10+fix1 — TEST ONLY (Finished preparation status)

- Recognize the formatter's `ready` phase as successful completion: remove the spinner and replace the black/yellow working row with a green checkmark result.
- Show a red result without a spinner on failure. Show activity only for known preparation stages; idle or unknown phases do not imply background work.
- Cover completion from progress polling and revisiting Prepare Drive, plus failed completion, at four browser widths with synthetic APIs.
- Preserve the UI10 behavior and preparation backend. Docker monitoring remains deferred.

## 2.0.0~ui10 — TEST ONLY (Responsive controls and verified network changes)

- Put one notification in a reserved bar, retain up to 100 recent messages, coalesce repeated messages, and keep controls free of moving overlays.
- Accept rapid Mount on recovery taps, serialize absolute preference saves, coalesce queued choices, and show inline saving/error feedback without remounting images.
- Show unsupported HDD sleep consistently for storage without an identified supported HDD; preserve known media metadata on incomplete status replies.
- Give Add USB drive a distinct blue button, space application/history selectors, and highlight active formatting with a black/yellow progress row.
- Wait for LAN enable/disable completion, tolerate transient read failures without retrying writes, show rollback results, and explain verification when a remote connection is intentionally closed.
- Verify a stopped LAN service has no main process; persist network-operation outcomes for review from localhost.
- Persist reconnect preflight refusals before any service stop or unmount. Restore prior monitoring if a later worker preflight proves storage unchanged. Keep uncertain/post-unmount failures guarded.
- Include selected/paired port names and attached-device identity in occupied-peer diagnostics. Retain the guard against disconnecting an unproven device; hardware acceptance remains required.
- Remove animated route scrolling that could close a newly opened touch dropdown. Docker monitoring remains deferred.

## 2.0.0~ui9 — TEST ONLY (Touch controls, live status and administration availability)

- Close event-history databases deterministically; keep background observation off the administration accept loop, bound request concurrency and lock waits, and back off on resource exhaustion.
- Keep manual image mounting independent of Mount on recovery, including disabled-image manual mounts, while retaining busy-storage and dependency guards.
- Add live passive HDD state to Overview and Manage Drive, with gray unsupported state for flash/SSD and green enabled recovery badges.
- Correct event refresh selectors and immediately refresh Companion token controls.
- Keep HDD standby controls visible, use touch switches/steppers, stack timing rows with explanations, and give every dropdown large touch and keyboard controls.
- Preserve UI8 manual sleep monitoring behavior and existing recovery bounds. See docs/UI9-TEST-NOTES.md and the release TEST-RESULTS.txt for physical acceptance and test limitations.

## 2.0.0~ui8 — TEST ONLY (Sleep without stopping monitoring)

- Manual HDD sleep leaves the monitoring service and its startup preference untouched on success, refusal, timeout and worker failure. An already stopped monitor stays stopped.
- Serialize sleep with storage operations using the recovery lock while allowing the existing monitor to keep observing the drive.
- Flush pending writes before the manual quiet check. Allow up to 15 seconds to establish three quiet seconds, without waiting for the configured automatic idle timer.
- Keep active-user, USB identity, mount, busy-I/O and bridge-verification checks. Automatic idle standby retains its existing policy.
- Keep the actual operation result visible even if later status reads or saving the last-operation receipt fail. Never retry a standby command automatically.
- See docs/UI8-SLEEP-TEST-NOTES.md. Physical spindle behavior still needs acceptance on the Ubuntu Studio test machine.

## 2.0.0~ui7 — TEST ONLY (Truthful reconnect results and bounded inspection)

- Label software USB reconnect explicitly and show that electrical power removal is unverified.
- Display failed backend outcomes as errors, retain the last recorded operation on the selected drive, and refresh status/history without retrying disk commands.
- Separate the disable worker's 15-second identity/isolation budget from the 3-second USB-write/readback budget; keep all safety checks and enable cleanup.
- Distinguish a refusal before any disconnect write from a completed write, uncertain write, verified disk return, and filesystem verification.
- Fix narrow-screen wrapping for Recent events buttons. Preserve UI6 USB-to-SATA detection, profiles, images and safeguards.
- See docs/UI7-RECONNECT-TEST-NOTES.md for scope and physical acceptance. No verified electrical power switching is added.

## 2.0.0~ui5 — TEST ONLY (Network apply, event refresh and image recovery preference)

- Change HTTP/HTTPS using an explicit Apply network settings action. The existing listener validates the change, local HTTP stays available, and failed LAN changes are reported. No manual LAN switch-off/on is required.
- Refresh Event History or a drive's Recent Events immediately and automatically while the relevant page is open. Preserve selected filter, scroll and other active UI input.
- Give each Virtual Disk Image an independent **Mount on recovery** checkbox, persisted in its recovery configuration without changing the current mount. Disabling is refused when another enabled image or Docker recovery depends on it.
- Retain UI4 token rotation, local certificate trust help, manual-operation records, confirm/cancel busy locks and guarded HDD standby. Hardware standby and intermittent USB reconnect timeout still require physical validation.
- No production deployment or drive operations performed while building.

## 2.0.0~ui4 — TEST ONLY (Operation status, manual history and HDD standby UI)

- Prevent repeated confirmation or cancellation during an in-flight drive operation; provide a visible waiting state.
- Record meaningful manual disk/monitoring/image operations into the selected drive's bounded event history.
- Make Monitoring OFF visibly red across Overview and Manage Drive.
- Restore authenticated download of the public HTTPS local trust certificate and plain-language browser setup notes.
- Explain recovery timing controls and expose safeguarded management-token rotation.
- Expose safe manual HDD sleep, automatic idle timeout and passive HDD state for mechanical HDDs.
- Permit registered Virtual Disk Images to be mounted or intentionally unmounted with monitoring on or off by coordinating only the selected drive's monitor; persist a no-auto-mount intent.
- Report the actual .img backing file capacity instead of a false 0 GiB when possible.
- No physical drive commands, production changes, public release or Docker testing in this package build.

## 2.0.0~ui3 — TEST ONLY (Virtual Disk Images with monitoring ON or OFF)

- Allow reviewed Virtual Disk Image creation and import without the user stopping monitoring.
- Keep monitoring disabled if it was disabled; if it was running, temporarily stop only the selected drive service under exclusive storage locks and automatically start it again so its recovery engine adopts the new image configuration.
- Reject pending recovery incidents, unresolved USB port enable obligations, ambiguous service states and unverified primary mounts. Preserve other drives' monitors and all existing file contents.
- Provide explicit confirmation and explain the short internal monitor pause. No change to the approved interface or recovery algorithm.
- Physical image formatting and service lifecycle acceptance on Ubuntu Studio remains pending.

## 2.0.0~ui2 — TEST ONLY (drive re-identification and UI contract corrections)

- Built-in, administrator-confirmed recovery for a previously configured USB drive after an external reformat changed its ext4 UUID; strongly verify hardware identity, review consent, save on-host backup, update existing UUID/mount registration, archive prior incident and keep monitor OFF until explicitly resumed. Preserve other drives and history.
- Correct Refresh drives self-blocking and update selected existing .img state without requiring a page reload.
- Correct reviewed mount-location UI API token/revision/confirmation payload, retaining backend dependency restrictions and rollback protections.
- Refuse USB port reconnection unless direct-port qualification is verified; safely recognize only kernel-only file descriptors while still failing closed on unreadable ordinary descriptors.
- Keep the approved graphical interface; no production deployments or automatic hardware mutations in this build.

## 2.0.0~ui1+fix1 — TEST ONLY (Virtual Disk Images hotfix)

- Correct the mismatch between the web frontend and privileged broker operation allowlists: authenticated read-only `image-discover` is now accepted for each configured drive.
- Prevent automatic scan on tab selection. Scan only after the user explicitly clicks Scan USB drive.
- Explain when the selected USB filesystem is not mounted, and disable image create/scan/import until mounting has been verified. Existing registrations remain visible.
- Add isolated two-drive broker authorization tests and frontend/broker API contract coverage, plus phone/tablet/desktop browser regression checks.
- Preserve the approved interface, backend recovery operations, tokens and all drive configurations; no physical operations performed in build.

## 2.0.0~dev9 — TEST ONLY

- Explicit drive routes and global settings; Overview always lists all drives.
- Genuine Add workflow and reviewed, independent monitoring/recovery controls in Manage Drive; remove Setup.
- Resolve preparation from physical disk identity with target-bound consent, ownership guards and progress.
- Combined, filterable event history; explicit per-drive email notification preferences.
- Distinguish actual and expected mounts; passive evidence-based media icons.
- Preserve legacy configurations, services, recovery budgets, data, tokens and listeners.
- Recheck transient process-exit mountinfo errors during concurrent recovery; surviving unreadable namespaces still fail closed.

## 2.0.0~dev8 — TEST ONLY

- Independent drive profiles, systemd monitors, recovery state, locks and history.
- Multi-drive Overview with Add USB drive and scoped Manage drive controls.
- Preserve existing settings/state in place; share management access and SMTP.
- Reject duplicate identities, conflicting mount paths and duplicate application owners.
- Coordinate targeted port operations and shared mount-table writes; keep existing recovery bounds.
- Isolate preparation identities, confirmations, dependent images and Companion tokens per drive.

## 2.0.0~dev7 — TEST ONLY

Separate interactive editor ownership from live status rendering so nested
permissions and drafts survive polling. Automatically provision a retrievable,
root-only management token; preserve DEV6 credentials during an explicit transition.
Separate Email account settings from Email notifications with distinct save/test
buttons. Recovery, listeners, virtual images and Companion integration are retained.
See [DEV7 testing notes](docs/DEV7-TEST-NOTES.md).

## 2.0.0~dev6 — TEST ONLY

Stable expanded technical details, consistent action colors, grouped timings,
Virtual Disk Image tabs, passive flash/HDD classification, token-only dashboard
login with local recovery, certificate help, and scoped Companion v1 status and
control API. Recovery algorithm and DEV5 LAN listeners are retained. See
[DEV6 testing notes](docs/DEV6-TEST-NOTES.md).

# 2.0.0~dev5 — test-only core corrections

Verified USB reconnect outcomes despite ambiguous power readback or lost write
receipts; independent image mount/access status and explicit account/group access;
management-token login, one optional LAN switch with acknowledged HTTP or verified
HTTPS; one dark theme and compact touch controls. Localhost HTTP remains separate.
See [DEV5 test notes](docs/DEV5-TEST-NOTES.md).

# 2.0.0~dev4 — test-only core fixes

Independent localhost HTTP and optional verified LAN HTTPS; accurate live status;
Limited Storage Spaces with guarded local-user access; responsive formatting-only
screen; mobile navigation, appearance choices and numeric defaults. Existing
recovery, Docker, SMTP, multiple filesystems and Bitfocus Companion are retained.
See [DEV4 test notes](docs/DEV4-TEST-NOTES.md).

# 2.0.0~dev3 — test-only GUI and application storage

Unified Overview controls; dedicated Setup, Email and Advanced screens; precise
software reconnect verification; multiple dependent ext4 images and Docker
selections; explicit selected-drive reformat; simplified authenticated local HTTPS.
Existing recovery, standby, Bitfocus Companion and SMTP components remain.
See [DEV3 test notes](docs/DEV3-TEST-NOTES.md).

# 2.0 development prototype (unreleased)

One recovery sequence, safe manual disk controls, guarded mechanical HDD standby,
service recovery and a simpler main dashboard. Existing filesystem, USB, SMTP,
Docker and authentication components are retained. See
[prototype validation and remaining work](docs/PROTOTYPE-2.0.md).

# 1.1.1~rc3 — simple protection setup candidate

- One basic screen: select a friendly drive name, choose automatic recovery and
  optional email, then explicitly activate protection. Expert controls stay in Advanced.
- Validate readiness before activation; bind consent to the reviewed drive and
  system settings. Reuse existing valid entries without relocating active mounts.
- Register a new drive at its current safe location or choose a location for an
  unmounted drive; retain private backups and roll back failed configuration writes.
- Support protected desktop directories on host /run tmpfs, with descriptor-based
  no-symlink traversal and safe directory recreation after desktop cleanup.
- Preserve filesystem guards, namespace exclusion, retry budgets, Docker state,
  notifications and hardware-reset qualification requirements.
- Test clean and upgraded configurations in Chromium, including privately supplied
  exact physical-test identity and path. Real Ubuntu Studio acceptance remains pending.

# 1.1.1~rc2 — existing-entry migration candidate

- Correct RC1's rejection of valid UUID entries in desktop/session directories.
- Offer optional migration to /mnt with precise consent, private backup and rollback.
- Resume interrupted migration; retain state identity, retry budgets, queue and history.
- Preserve unrelated fstab entries and existing Docker/dependent paths.
- Inspect USB2/USB3 peer topology read-only and explain the single-port executor limit.
- Document later supervised offline paired-port qualification; no paired reset enabled.
- Add 16 migration, 9 peer and 4 additional browser regressions.
- Actual Ubuntu Studio acceptance remains pending; nothing has been published.

# 1.1.1~rc1 — setup workflow candidate

- Detect virtualization instead of showing a generic VM warning on physical hardware.
- Explain automatic filesystem remounting separately from qualified USB port resetting.
- Propose stable mountpoints for desktop/session mounts, show the exact permanent entry,
  require explicit consent, and guide safe desktop release without automatic unmounts.
- Validate prerequisites before Review and again before Save; focus actionable field errors.
- Preserve existing mount entries, disk contents, USB restrictions and Docker safeguards.
- Show monitoring banners from actual service state; skip Docker discovery when disabled.
- Add 16 backend and 9 Chromium workflow regressions, including clean installed payload tests.
- Fresh Ubuntu Studio acceptance remains required. No GitHub publication.

# Changelog

## 1.1.0

- Re-arm a completed outage on a confirmed new USB disk attachment using kernel
  diskseq and boot identity, preserving per-connection attempt limits and old
  incident records. Restarts and upgrades never renew exhausted budgets.
- Distinguish live storage/recovery progress from recorded historical outcomes
  on both Overview and History; remove stale health claims on connection loss.
- Archive completed Docker records from previous container selections before a
  new incident. Keep unresolved and current-incident action budgets protected.
  Show partial recovery when storage returns but applications or a dependent
  filesystem still need attention.
- Correct recovery over nonempty directories and permit ordinary ext4 journal
  replay. Preserve underlying files, recorded-error rejection and all post-mount
  UUID/ext4/read-write checks. Explicit process namespace and exclusive block
  access checks protect against retained Docker mounts.
- Reprompt CLI disk/port/timing choices with their allowed ranges; accept y/n
  and explain invalid yes/no and TLS selections.
- Responsive authenticated web dashboard, first-time setup, event history and
  separate advanced settings. CLI and headless installations remain available.
- PAM administrator login, short-lived broker sessions, CSRF and origin checks,
  strict host validation and an unprivileged web process.
- Fresh system-disk exclusion, duplicate-UUID refusal, safe permanent mount
  configuration, write-only SMTP credentials and local TLS email testing.
- Docker container and bind discovery with API negotiation and explicit opt-in.
- Localhost default; private LAN access requires explicit authorization and a
  matching, current TLS certificate. No reverse proxy headers are trusted.
- Bounded persistent presentation history; the existing recovery engine remains
  responsible for all disk actions, retries, queues and Docker recovery.
- GUI lifecycle hooks preserve monitoring state and support explicit headless
  installation. Bundled, checksum-pinned Gunicorn 26.2.0 replaces the older
  Ubuntu server dependency; no install-time Python downloads.
- VMware GUI validation and added security, first-run and lifecycle regressions.

## 1.0.0

Initial reusable distribution of the v3.2 storage recovery implementation.

- Separate service, configuration, state and independent SMTP sender.
- Validated filesystem, timing, optional loop, USB and Docker configuration.
- Monitoring-first setup; every mutation requires explicit opt-in.
- Per-target USB qualification with no distributed machine identity.
- Saved USB enable profile survives configuration removal/replacement.
- Configuration fingerprints stop mismatched worker actions.
- Debian and portable packages, maintenance tools and beginner documentation.
- Simulated recovery tests and isolated staged install/upgrade/removal checks.
- Ubuntu 24.04 VM validation with real ext4, systemd, local TLS SMTP and Docker.
- Host-independent xHCI test fixtures; system disks excluded from setup choices.
- Clear unsupported USB topology diagnostics.
- Explicit mount/coreutils dependencies, normalized package directory modes,
  Debian copyright/changelog/manual, and portable/dpkg overlay prevention.
- Portable installation resists permissive caller umasks and preserves state
  across live upgrade, removal and reinstall.
- Bounded dependent-loop verification now waits for incomplete udev identity
  fields, while known UUID/type mismatches still fail immediately.
- Privacy audit inspects the allowlisted compressed Debian documentation with
  a bounded decompression limit.
