# Bitfocus Companion integration

The separate **0.2.6 local-test module** supports Companion **5.1+**, module API
2.2 / Node 26 and Storage Watch **UI36+**. It uses existing authenticated dashboard
sessions, one-press safe unmount and guarded app controls. The verified UI36 engine,
configuration, recovery and boot behavior remain unchanged.

Source, build instructions and test boundaries:
[integrations/companion-module-usb-storage-watch](../integrations/companion-module-usb-storage-watch/README.md).
Read [module HELP](../integrations/companion-module-usb-storage-watch/companion/HELP.md)
for installation, TLS, credentials, variables, feedback and the **one-press controls** and Working/Completed/refusal result display.

- Configure the server URL and **dashboard management token** in Companion's
  secret field. HTTP is permitted only for localhost; HTTPS always verifies the
  certificate/hostname and optionally accepts an explicitly trusted public CA.
- Drive/app choices use configured names and stable profile/full container IDs.
  Saved startup/recovery settings are distinct from running state. Missing,
  stale or unavailable observations never become healthy feedback.
- Targeted presets cover manual HDD standby, monitoring, mount/safe unmount and app start/stop/restart through
  existing backend locks, current identity/storage checks and one-use backend safety snapshots.
  No command retries, policy changes, USB resets or name-based reassignment.
- Safe unmount preserves deliberate stops. Mount/monitoring does not start those
  apps. This integration is not an application-crash watchdog.
- Management tokens grant dashboard administration. Protect Companion's private
  configuration and exports. No secrets belong in presets, variables or Git.

Installation follows the [official local-module workflow](https://companion.free/for-developers/module-development/local-modules/).
Publication/module-store distribution is not part of this local release. Removing
or disabling the connection only stops integration polling; it does not operate
Storage Watch, storage or apps.

## Setup from Integrations

UI38's **Integrations** page shows the active server URL with Copy, brief token
retrieval instructions, Copy certificate with expandable complete public PEM, and
the unchanged bundled module download. **Manage token** opens Advanced Settings
at the existing token controls; replacement remains there. **Network Settings**
opens the network section with address/ports/HTTPS, certificate download and trust
instructions. Module downloads use the dashboard's own origin on localhost or LAN.
Unavailable network addresses are never offered as working URLs; LAN disabled
shows localhost only. Remote Companion requires HTTPS.

1. Download module **0.2.6**, then use **Modules → Import module package** in Companion.
2. Add USB Storage Watch or select 0.2.6 on the existing connection.
3. Copy the server URL. Retrieve the existing management token with the displayed
   host-terminal command and paste it into Companion's secret field.
4. For HTTPS, verify and copy the **complete public CA PEM**, including its BEGIN
   and END lines, into **Trusted public CA certificate (PEM, optional)**. Keep verification enabled.

Existing 0.2.5 buttons need no replacement. Replacing the management token signs
out dashboard sessions and requires updating Companion too; ordinary setup does
not replace it. Neither private keys nor the existing token are served by setup
endpoints. Module/CA downloads require a dashboard session.

UI37 removes the obsolete drive-scoped Companion v1 and standalone standby-token
APIs and token controls. Those credentials cannot log in or authorize supported
routes. Historical token files are left untouched for rollback; they are not read
or accepted. Current one-press controls use dashboard sessions and all existing
backend locks, CSRF, storage, identity and safe-unmount safeguards.

## 0.2.5 customizable layouts

Import 0.2.5 and select it on the existing connection. Existing 0.2.3/0.2.4 buttons
are preserved; use new drive/app presets (place as copies) for separate Custom name,
Live status, Action and Command outcome elements. Edit names under Style and each
state's colour under Feedbacks. Full IDs remain in action/feedback configuration,
not on the new button face. HELP documents status evidence, variables and optional
manual migration of existing custom layouts. Back up Companion before replacing
buttons; rollback to 0.2.4 plus that backup if new layouts were added. UI36 stays put.


## 0.2.6 status-drop correction

Select 0.2.6 after importing its package. Existing 0.2.5 buttons/customizations need
no replacement. One fresh-connection retry is restricted to read-only status GETs
with a reused-socket reset, within the original deadline; no commands are replayed.
Fleet/Docker freshness is independent. The existing broker 503 remains visible and
is not retried. Rollback selects 0.2.5 with the same buttons. See HELP for evidence
limits, diagnostics and status-only variables; UI36 backend behavior is unchanged.
