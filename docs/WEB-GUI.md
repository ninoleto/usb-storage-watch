# Web dashboard guide

To remove a drive from the overview without erasing its files, see
[UI14 drive removal](UI14-TEST-NOTES.md).

For the current network interface and detailed certificate setup, see
[UI13 network and touch controls](UI13-TEST-NOTES.md). The historical descriptions
below predate the current UI.

Install the TEST-ONLY Debian package with your graphical package installer and
open **USB Storage Watch** from the application menu. The initial address is
**http://localhost:8765** or **http://127.0.0.1:8765**. Dashboard login uses the
same management token locally and over LAN HTTP/HTTPS. The installer creates a
unique token. Retrieve it on the application computer with:

```sh
sudo cat /var/lib/usb-storage-watch/management.token
```

Enter your local administrator's sudo password if asked. Copy the displayed token,
paste it above **Connect**, then connect. The root-owned file has mode `0600` inside
the private state directory; HTTP never returns an existing saved token.

DEV6 upgrades keep the old credential valid and add a retrievable token. To retire
old credentials, use **Advanced → Management access → Replace management token**.
This explicitly revokes all earlier management tokens and sessions. Companion uses the same management token and must be updated after replacement. Package service restarts require a
fresh login; migration itself does not clear active sessions.

If the token file is missing, expand **Additional setup and token recovery** at
localhost and choose **Create or recover a token**. Your named local administrator
account authorizes regeneration; the new root-only file and its derived verifier
change as one atomic credential record. Old credentials/sessions are revoked.
Normal dashboard login remains token-only. Recovery using a Linux password is
never available over LAN. CSRF, Origin checks and login rate limits remain.

The token is associated with the existing DEV6 administrator, otherwise the
installing sudo/polkit administrator, otherwise the first named desktop
administrator. A machine without a named administrator needs local recovery after
creating one. Existing permissions and image ownership are never rewritten.

- **Overview:** all configured drives, including disconnected ones, and connected
  supported USB filesystems. **Add USB drive** opens an eligible-drive selection;
  **Refresh drives** reports completion and its timestamp. Media icons use passive
  hardware evidence; unknown devices retain a generic icon.
- **Manage Drive:** opened from a drive card, with the target identified in its
  URL and heading. Start/Stop monitoring and Enable/Disable automatic recovery
  are separate controls. Mount, Unmount safely, guarded Reconnect USB port,
  Change mount location, virtual images, applications, timings, standby and
  drive-specific history belong here. Existing permanent mounts are reused.
  Expanded technical forms retain their drafts and focus during status polling.
- **Email & Notifications:** shared **Email account settings** has SMTP credentials,
  **Save email settings** and **Send test email**. **Email notifications** lists
  each configured drive with its own preference and Save action. Blank passwords
  preserve saved credentials. SMTP editing does not stop monitoring; changing a
  drive's notification preference may briefly restart only that monitor, after
  existing operation locks permit it. SMTP acceptance is not inbox delivery.
- **Prepare drive:** independently select a physical USB disk and explicitly
  erase it to create one ext4 filesystem. Close applications and safely unmount
  first. Confirmation stops only the target's monitor and backs up its settings;
  other drives remain monitored. Review physical identity and the typed erasure
  confirmation. Recovery never formats. See [Prepare drive](PREPARE-DRIVE.md).
- **Event History:** combined chronological incidents, labeled by drive. Its
  optional drive filter persists independently of Manage Drive navigation.
- **Advanced:** global management access and network settings. Drive-specific
  advanced settings are in that drive's Manage page. The redundant Setup page is
  removed; reviewed transactions and backend safety checks are retained.

In **Docker & Application Recovery**, optional **Virtual Disk Images (.img)**
are files that work like separate disks with their own capacity, accessible through
normal folders. Only files inside a virtual disk count towards its limit;
applications with permission to write elsewhere are not restricted.

Enter an image name, capacity in GB and access permissions (your signed-in account
by default). Applications / Docker, selected local users and advanced custom IDs
are also available. Containers must use matching user/group IDs. The app chooses
an accessible folder under `usb-storage-watch-volumes` and a protected backing file
in `.images`. Custom paths remain in Technical settings. Existing images retain
their paths; import detects their UUID without formatting or permission changes.

New images are verified by browsing, creating, reading, modifying and deleting a
temporary file as each intended writable user. Mount status and folder access are
reported separately: access denial does not mean unmounted. Existing images offer
**Change permissions / Fix folder access**, with review and explicit confirmation.
This grants mount-root access and required parent traversal, preserves existing
ownership/access, and never recursively changes user files or `lost+found`.
**Copy folder location** copies the path for Dolphin. Edit/remove recovery settings
only after safe unmount; removing configuration keeps the image file and data.
Recovery restores required images in dependency order before applications.

In **Docker & Applications**, every detected container has its own card.
Expand or collapse it using the header or the arrow beside its Running/Stopped
status. Collapsing preserves unsaved choices. The page remembers collapsed cards.

Within the card, turn on each drive that should stop this container on failure
and start it after recovery. Below an enabled drive, choose **None** or the
virtual images that must be mounted before this container starts. Save with
**Save recovery settings**. Monitoring on/off never locks these options. Saving
does not stop or start the container now, move files or change Docker storage.

At the first detected disk failure, Storage Watch requests a graceful stop of
the selected containers. It then waits for and recovers the physical disk,
mounts images with **Mount on recovery** enabled plus explicitly selected images,
and starts the selected containers. A container stays stopped if one of its
explicitly selected images cannot be mounted. An unrelated image failure does
not block it. Choosing **None** means wait for the disk only. Docker bind-folder
detection provides advice and never changes these choices.

The final outcome email is queued after the storage/container stages, when email
notifications are enabled. A selected container may be started even if it was
already stopped before the outage. Turn off its drive switches to exclude it.
Container identity, current selection and verified storage are checked before
starting; uncertain Docker commands are not blindly repeated.

The same container can depend on multiple selected drives. It stays stopped
while another selected drive or selected image is unavailable. Unselected
containers are not controlled. This is storage recovery, not a watchdog for
unrelated application failures. The interface does not install containers or
edit Compose files.

A hub permits monitoring and normal mounting, but **Reconnect USB port is
disabled**. Direct-port support is automatically rediscovered after moving a
known drive. Software reconnect does not prove electrical power was removed.

**Change mount location** changes where the same files appear; it never copies,
moves or erases them. Applications using the old path may need updating. Existing
image/container paths must be reviewed before changing the primary location.
Private transaction backups and rollback remain available on that screen.

Under **Advanced → Network access**, edit the LAN switch, HTTP/HTTPS choice,
server address or ports, then select **Apply network settings**. The current
connections stay available while proposed listeners are tested. Open the generated
link in a new tab, sign in with the existing token, and confirm from that proposed
connection within three minutes. The token is never included in the link.
Cancel, timeout or a broker restart before confirmation retains the old settings.
Only confirmed changes update the saved URL cards. Failed commits restore and
verify the previous configuration, or report when local review is needed.

Disabling LAN requires confirmation through localhost on the Linux server.
The default localhost HTTP port is 8765; default LAN HTTPS is 8766. The server
address picker and touch port controls are grouped under **Advanced: server
address & ports**. They choose existing host addresses, not new OS IP assignments.
Changing the HTTP port also changes localhost; the menu launcher follows it.

LAN access defaults off. HTTP exposes management tokens and commands on that
network; read the warning before applying it. Use a trusted private network or
VPN. The app never configures the router, firewall or public internet exposure.

For HTTPS, prepare and download the public trust certificate, verify its
fingerprint on the Linux server, and install it in the client device's trusted
certificate store before testing the generated link. The UI12 private issuer
persists across address changes. Existing saved certificates remain unchanged
until an explicit change; the first UI12 HTTPS change may need new client trust.
The server certificates last one year. To test a replacement on the same address,
choose an unused HTTPS port so the existing connection can remain available.
See the UI12 notes for the complete confirmation and acceptance sequence.

Routine monitoring reads kernel metadata and does not query HDD power state.
Idle means no observed I/O; it does not prove the spindle stopped. Standby is
shown only after confirmed standby with no subsequent block activity.

Installation and automated browser checks do not establish physical compatibility.
This development version still needs Ubuntu Studio acceptance testing.

The interface uses one high-contrast dark theme. On phones, open the hamburger
menu; desktop navigation remains in the sidebar. Numeric controls allow direct input, minus/plus and individual
Reset. Group resets restore tested defaults in the form; Save applies them.

Technical drive details and nested permission editors stay open during live updates.
Status refreshes preserve draft values, focus, selections and scrolling. Virtual Disk Images use Create new / Add existing tabs; configured images remain below the form. Advanced timing groups separate monitoring, USB, HDD standby and application recovery.

## UI17 action feedback and image fixes

Action progress and results appear below the relevant controls, including
image operations and confirmation errors. Image mounting no longer treats
its own configuration lock as a competing save. Partial image creation is
reported without automatically resubmitting it.
See [UI17 changes and verification](UI17-TEST-NOTES.md).

## UI18 manual Docker controls

Each expanded container card offers Start when stopped, or Stop and Restart
when running. Manual commands are independent of monitoring and saved drive
restart choices. Progress and outcomes appear below the controls.
See [UI18 changes and verification](UI18-TEST-NOTES.md).
