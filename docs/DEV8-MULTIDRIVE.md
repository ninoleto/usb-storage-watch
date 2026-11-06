> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# DEV8 investigation and migration

DEV7 discovery already returns multiple ext4 filesystems and rejects duplicate
UUIDs. The reported SanDisk restriction is imposed later: `renderBasic()` requires
the discovered UUID to equal the one saved in `config.disk.uuid`, and
`web_protection.proposal()` rejects any different saved UUID. Removing that UI
condition alone would overwrite ADATA's configuration and reuse its incident state.

The current configuration schema, engine globals, monitor service, operation locks,
USB cleanup ledger, application recovery ledger, standby state, backups and browser
history each describe one drive. The broker also handles all requests serially.

DEV8 retains the proven single-drive engine in independent instances:

- The existing `config.json`, state directory and `usb-storage-watch.service`
  remain the legacy profile. Existing incidents, queues, images and tokens are
  not moved or rewritten during upgrade.
- Additional profiles have an immutable internal UUID identifier, private
  `drives/ID/config.json` and `drives/ID/` state directories, and their own
  an instance of `usb-storage-watch@.service` named with that ID. Filesystem UUID remains the selected disk's
  identity; reformatting does not silently select another profile.
- Engine workers inherit their profile, so every operation, cleanup obligation,
  lock and delivery queue stays with its drive. Each monitor observes independently.
- Management credentials, sessions, SMTP credentials and LAN listeners remain
  global. Scoped requests select a profile explicitly; there is no global mutable
  "currently selected drive" shared between browser sessions.
- A dashboard lists connected and configured drives. Manage drive opens the
  existing controls/settings for that profile. New-drive setup does not stop an
  existing profile. Interactive controls retain the DEV7 polling boundaries.
- Shared configuration/mount-table changes and hardware actions need cross-profile
  coordination in addition to each drive's existing operation locks. Duplicate
  UUIDs, conflicting mounts and unsafe shared resources must fail closed.

Validation uses synthetic multi-drive discovery, isolated services/state and
browser sessions. No physical USB operation, real Docker/SMTP action, or access to
production Zorin or physical Ubuntu Studio is permitted during development.

## Using multiple drives

Overview shows a card for each connected or configured USB filesystem. Choose
**Add this drive** (or **Start monitoring**) on an unconfigured card, review its
recovery choices in Setup, then save. Existing valid UUID mount settings are
reused. Other monitors continue running. **Manage drive** opens that drive's Mount,
Unmount, Reconnect, HDD, mount-location and recovery controls. Setup, Advanced and
history then refer to that selected drive; the page heading identifies it.
Selection is local to the browser tab. Return to Overview to choose another.

Each profile can have multiple virtual disk images and selected applications.
SMTP account settings, management credentials and LAN listeners remain shared.
Notification preference and the restricted Companion token belong to each drive.
An existing Companion connection continues to select the original drive; another
drive uses its own token and filesystem UUID. The separate module project is unchanged.

A container or service has one recovery owner. Duplicate ownership is refused,
with a clear explanation. Before a container restart, configured storage used by
its bind mounts on other monitored drives must also verify. If required storage
is unavailable, recovery reports the application failure/partial result. There
is no unbounded cross-drive retry or inferred service dependency graph.

Configuration and fstab changes briefly share one lock. Monitoring, incident
queues and ordinary drive operations remain separate. Targeted port operations
share a lock only for the exact port, and unresolved cleanup obligations remain
exclusive across profiles. Existing isolation, current-port rebinding and hub
refusal checks still apply. Connected duplicate UUIDs and changed pinned hardware
refuse actions. Missing hardware metadata does not authorize a USB reconnect.

## Validation and physical acceptance

Focused tests cover independent active monitors, concurrent failures, bounded
budgets, identity refusals, per-drive confirmation tokens, shared-resource locks,
three profiles with multiple images, Companion token scoping, and lifecycle
preservation. Real Chromium workflows add the second drive while the first stays
active, select drives independently across sessions, and preserve nested forms
through three actual polling cycles at desktop, tablet and phone widths.

Disposable QEMU USB disks exercise the real ext4 formatter and guarded ordinary
mount operations. A second disk can be prepared without changing the first one's
configuration, identity or data. Independent and simultaneous remounts preserve
both filesystems. Explicit reformatting retires only the selected identity and
keeps its backup. An untouched third virtual disk retains its full checksum.
No physical port reset, physical formatting, live Docker or SMTP test is performed.

Final counts, package/upgrade checks and any warnings are recorded in the transfer
bundle's TEST-RESULTS.txt. Physical Ubuntu Studio acceptance must still test two
or more actual drives, moving either drive between ports, separate and simultaneous
disconnections, targeted reconnect isolation, hubs, and HDD standby. Public
release readiness and real Docker compatibility are not claimed.
