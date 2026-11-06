# USB Storage Watch

Local test module **0.2.6**, for **Companion 5.1+** (module API 2.2 / Node 26) and
Storage Watch **UI36+**. It uses the existing dashboard API; no Storage Watch
engine update is required. Earlier Companion releases need a compatible module
port; do not assume this package runs on 4.1.

## Connect

Enter the complete **Server URL** and the **dashboard management token** in the
secret field. Obtain your token on the Storage Watch computer with:

```sh
sudo cat /var/lib/usb-storage-watch/management.token
```

Keep it private. This is the `usw7_` (or legacy `usw_`) token used to log in to the dashboard, not the
older drive-scoped `uswc_` Companion token. It grants administrator access: protect
Companion's configuration, backups and exports. Secrets use Companion's dedicated
secret storage, never feedback, logs or URL parameters. Do not migrate an old
restricted-token connection by guessing a replacement token or drive.

For the same machine use `http://127.0.0.1:8765` (adjust the configured port).
For another machine, use its verified HTTPS URL. Optionally paste the verified
**public CA certificate** into the CA field. Certificate and hostname checks are
always enabled. There is no insecure TLS option, redirect following or HTTPS
fallback. HTTP is restricted to localhost. This module never changes network/DHCP
settings or discovers network devices.

## Status and selections

Drive/app dropdowns are discovered from Storage Watch, with readable names and
stable drive profile IDs/filesystem UUIDs or **full container IDs**. Identical
container names remain separate. A recreated container must be explicitly selected;
there is no name-based reassignment. Drive/image dependencies remain controlled by
Storage Watch settings. Ordinary folders need no virtual image.

Variables include connection freshness, last result, current review, and for each
drive: name/UUID, availability, mount, monitoring, recovery phase/detail, backend
return-timeout seconds and current failure. App variables include name/ID, running
state, health, saved startup/recovery settings and control restrictions. Variable
IDs are derived from stable identities, not display names. Feedback can match any
of these state fields. Presets include targeted drive/app controls, mount/monitor/recovery/HDD/app status,
and Result pages. Names and short identity suffixes
fit physical buttons; full names and IDs remain in notes, choices and review_text.
HDD awake requires observed I/O; asleep requires a still-valid confirmed standby
record. Idle, stale or missing evidence is **unknown**, never guessed asleep. These indicators do not prove application-file integrity.

Reads poll every five seconds while the server remains reachable. Full connection
failures back off up to sixty seconds. Fleet and Docker freshness are independent. State
becomes unknown after fifteen seconds without a successful observation or immediately
on a failed read. Backend busy/stale state remains unknown. Authentication errors,
missing identities and disconnected service are distinct from a verified stopped
app. No previous healthy observation authorizes an action.

## Command results and connectivity

A confirmed command remains **Completed** (or Refused/Failed as reported) if a
later status read fails. A lost command reply stays **Unknown**, even if subsequent
status is healthy. Do not resend an uncertain command to compensate for feedback.

Online requires a successful authenticated status read. **Online / Status stale**
means the server is reachable but a complete current inventory is unavailable;
target state remains unknown and controls still require fresh safety checks.
`connection_message` gives the read error; `status_fresh` reports inventory freshness.
`last_result` remains the operation outcome. Total read failure or expired evidence
shows Offline without erasing an already confirmed outcome.

Connection **View logs** records sanitized request diagnostics: operation, endpoint,
elapsed time, HTTP status and error code. Enable Debug to see successful reads.
USW_TIMEOUT identifies the client's deadline, ECONNRESET a socket reset and
INVALID_JSON a malformed response. Request bodies, tokens and cookies are excluded.
The reproduced feedback defect is corrected; the historical network interruption
that prompted this release remains unidentified.

## One-press controls

The supplied operating presets **execute with ONE press**. There is no mandatory
review screen, numeric code, keypad or additional confirmation button.

- Each drive: **Sleep HDD now, Mount, Safely unmount, Monitoring ON/OFF**.
- Each app: **Start, Stop, Restart**, pinned to the full container ID.
- Status presets remain read-only. **Result** shows the current explanation;
  press Result to read further pages if needed. Reading it does not execute work.

The operating button shows **Working**, then **Completed**, **Refused** or
**Failed**. Unknown means the outcome could not be verified, for example after a
transport failure. Full explanations are available in `last_result` and the
selected target's `last_result` variable. Amber means pending, red means an error,
grey means unavailable state; a sent request never means completed. Read the
specific refusal before pressing again. Duplicate presses while working are
rejected, never queued, and commands are never retried automatically. The button
callback acknowledges dispatch promptly; Working/result feedback waits for the
verified backend reply, including for operations longer than five seconds.

**Sleep HDD now** immediately calls the existing manual standby worker. It does
not wait for the automatic idle timer or enable/change that setting. Busy users
and containers still refuse sleep; writes are flushed and must settle within the
existing bounded window. Monitoring remains unchanged. Standby is displayed only
when the backend confirms it; a sent power command is not enough.

**Safely unmount** stops and verifies explicitly dependent apps, then unmounts
selected images and the physical filesystem. Monitoring stops, pending startup is
withheld and apps remain stopped. Mount/monitoring does not automatically restart
them. One press obtains the existing authenticated, session-bound, one-use safety
snapshot/token and submits it internally. The backend still revalidates current
dependencies, exact identities, mounts and settings under its existing locks.
A changed snapshot or failed stop aborts unmount; no forced/lazy unmount is added.

Every operation refreshes identity/state before admission. Drive presets pin both
the profile and filesystem UUID; app presets pin the full container ID. Recovery
locks, missing-storage restrictions and unrelated-app protections remain in the
backend. A replaced container or changed drive must be explicitly selected again.
There are no USB reset, policy-edit or identity-reassignment actions.

Explicit app Start/Restart requires ready storage and can release that app's
safe-unmount hold. Startup respects later manual stops; enabled drive recovery may
start an app again. This is not an application-crash watchdog.

Older optional review actions remain for compatibility. They do not become direct
writes on upgrade, and preparing a legacy review displays **Review only**, never
Working or Completed. They are not used by the new operating presets.

## Installation / removal

Use the tested `.tgz` package with Companion's local-module package importer, or
extract it to a subfolder of your **Developer modules path** and enable developer
modules. Select **USB Storage Watch** under Connections. The developer path is the
parent containing module folders, not this module folder itself.

Removing/disabling this Companion connection stops polling only. It does not change
Storage Watch settings, stop monitoring, cancel recovery or operate apps/storage.
Read the accompanying project README for build commands, sources and test limits.

### Updating from 0.2.3

1. Back up your Companion configuration.
2. Use **Modules → Import module package**, import the 0.2.4 `.tgz`, then select
   **0.2.4** on the existing USB Storage Watch connection. Retain its URL, CA and token.
3. **Existing 0.2.3 buttons do not need replacement.** Action/feedback IDs, pinned
   targets and existing variables remain compatible. The feedback correction takes
   effect when the connection runs 0.2.4; importing alone may not switch its version.

Rollback: select 0.2.3 on that connection (reimport its preserved package if needed).
Existing 0.2.3 buttons also work after rollback. Restore the Companion backup only
if you separately changed its configuration. No USW reinstall/state restore is needed.

### Updating from 0.2.1 / 0.2.2

1. Import the 0.2.4 package and select **0.2.4** on the existing connection.
   Keep its URL/token; importing or changing version performs no operation.
2. Remove old operating buttons and drag in the new target presets. **Copies keep
   their old actions**; linked review presets are retired. Replace
   either kind explicitly. Unused keypad/review buttons may be removed.
3. Inspect each button's action: it must say **execute now**, such as
   **Sleep HDD now — execute now**, not **Review drive action (does not execute)**.
   Confirm the intended target in its dropdown/notes, then one press operates it.
4. Add the **Result** preset for full outcomes/refusal explanations. It is optional
   for execution, and never a confirmation step.

Backup your Companion configuration before replacing buttons. To roll back, select
0.2.2 and restore the previous buttons from that backup. No Storage Watch reinstall
or settings/state restoration is needed.


## 0.2.5: edit names, live text and colours separately

New target presets use Companion's layered buttons. Place as a **copy** for full
editing. Under **Style**, select **Custom name** and change only its Text (for
example, Toshiba USB). **Live status** contains a status-only variable. **Action**
is an editable caption; **Command outcome** is separate from live drive/app state.
Changing text never changes the pinned target or action. Inspect full filesystem
UUID/profile or container ID under Actions, Feedbacks and Notes; IDs are not drawn
on the new button face. Text shrinks to fit; short names remain easiest to read on
72×72 buttons. Keep the live-variable elements when renaming.

Under **Feedbacks**, each new state is a normal boolean condition. Edit that
condition's **style override → Live state background → colour**. Operating buttons
also have a separate **Command outcome background**; Working may override the whole
background. Text and colour updates do not overwrite your saved styles. A linked
preset must be converted to a copy before freely editing its elements/feedbacks.

Default meanings (all editable):

- Blue: idle (no recent I/O), unmounted, monitoring off, or stopped app.
- Purple: asleep, confirmed standby for the current connection with unchanged I/O.
- Green: in use (disk I/O observed), mounted, monitoring on, or running app.
- Red: unavailable/fault, failed recovery, or refused/failed command outcome.
- Grey: unknown/stale state, unsupported power detection, or unknown command outcome.
- Amber: operation/recovery in progress. A legacy review is not execution.

These colours describe the selected metric: mounted does not mean busy, awake does
not mean in use, and idle does not prove sleep. UI36's passive status checks observe
kernel block-I/O counters. Its standby evidence is bound to the current boot/device
connection and invalidated by new I/O. The module never uses an old operation result
as current power status and never probes hardware. **Idle / Power ?** means no
recent I/O, with unknown spindle power. **In use / I/O observed** means observed disk
activity, not a claim about every process with an open file. **Unknown** means the
backend cannot establish current evidence, or polling is stale/unavailable. It is
not a continuous hardware power sensor. Mounted, monitoring, recovery, power/activity
and command outcomes each have separate presets/variables/feedback conditions.

Status-only variables include `drive_<profile>_power_state`, `_activity`,
`_power_label`, `_mount_label`, `_monitor_label`, `_recovery_label`, and
`app_<full-id>_state_label`. New drive presets use `drive_<profile>_fs_<uuid>_...`
variables so a reconfigured profile cannot silently show another filesystem.
Punctuation in variable IDs is normalized to underscores. Discover the exact names
in Companion Variables. `_outcome_label` describes the last command, not live state;
`last_result` / target `last_result` provides its full explanation.

### Upgrade / rollback

Back up Companion, import 0.2.5, select it on the existing connection, and preserve
URL, CA and token. **Existing 0.2.3/0.2.4 copies, linked presets, actions, variables
and customizations are retained.** They are not automatically relaid out. To obtain
separate elements, replace only the desired drive/app buttons with new presets
(place as copies), confirm the target and reapply your preferred name/colours.
Old and new preset IDs are distinct. No old review action becomes a direct action.

Alternatively, keep an old button: replace only its `button_name` variable with a
literal custom name while keeping the other variables; remove legacy fixed-colour
feedback and add the new boolean state conditions/styles. Its actions stay intact.
This manual migration avoids overwriting custom layouts.

Rollback: select 0.2.4 and restore your pre-upgrade Companion configuration if you
added 0.2.5 presets (their new variables/feedbacks require 0.2.5). No UI36/backend
installation or storage-state restoration is required. Commands remain one-press;
0.2.4's verified-result preservation and no-replay handling are unchanged.


## 0.2.6: status transport and independent freshness

A server may close an idle HTTPS connection while Node reuses it. For **GET
fleet-status, docker-overview and session only**, one reused-socket ECONNRESET
before response headers may retry on a **fresh connection**, using the remaining
original eight-second request budget. HTTPS verification, CA, origin and session
credentials remain enforced. Diagnostics identify attempt 2 and its original
request ID. No retry applies to POSTs (including login), safety-review/snapshot
GETs, HTTP 503/401/refusals, malformed JSON, timeouts, or a fresh-socket failure.
Storage/container commands are never replayed, including lost replies.

A failed Docker read now leaves fresh drive status visible; a failed fleet read
leaves fresh app status visible. Each stream expires after 15 seconds without a
successful read. `fleet_fresh`, `docker_fresh`, `fleet_status_message` and
`docker_status_message` explain each stream; `status_fresh` requires both. Partial
failure continues polling at five seconds. Unavailable target data remains Unknown;
command admission still requires both inventories fresh and all backend checks.
A preflight failure reports **No command sent**. A failed status GET does not claim
an uncertain command outcome. Confirmed outcomes remain separate from polling;
a lost POST reply remains Unknown even if subsequent status reads succeed.

The broker's “Drive operation unavailable. Other monitors continue independently.”
HTTP 503 is a separate backend observation error, not automatically a network
failure. It is displayed, not retried or suppressed. The existing backend discards
its exception detail, so historical logs cannot establish the underlying cause.
This module release does not change UI36 backend behavior or increase timeouts.

Import 0.2.6, then select it on the existing connection, retaining URL/CA/token.
**No preset replacement is needed when upgrading from 0.2.5.** Editable names,
colours, pinned IDs, actions and variables are retained. Rollback selects 0.2.5;
no button or USW configuration restoration is needed unless separately edited.
