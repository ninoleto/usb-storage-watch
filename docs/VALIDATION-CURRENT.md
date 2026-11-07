# Current validation and limits

Beta **2.0.1~beta4**, prepared tag **v2.0.1-beta.4**, improves Docker setup permission
diagnostics and reviewed adjustments, and marks saved enabled settings with green
header borders. Companion **0.2.6** and automatic recovery are unchanged.

Focused isolated tests use real temporary file modes, descriptor checks, group
membership fixtures and actual Compose configuration rendering. Docker responses,
service control and account/group membership are simulated. They cover shared-group
files, environment files, exact writable project/ancestor identification, stale
reviews, identity/ACL/hardlink/bind-mount refusals, competing app locks, permission
failure/rollback, multiple inputs, source conflicts and partial saves. Erugo-like,
PhotoPrism-like and Immich-like Compose layouts are exercised. No real containers,
production permissions or services are operated.

Real Chromium/localhost HTTP/session/broker checks at **320/768/1440 px** verify
permission review/confirmation, refused stale requests, unchanged media modes,
remaining Not configured until save, and green saved badges in expanded/collapsed
cards. Unknown/off/unsaved settings and recovery locks retain their safeguards.
Python **3.12.16**, Flask **3.0.2** and a private pure-Python **PyYAML 6.0.3** copy
are used for compatibility checks; this is not the target's exact dependency set.
Fresh/upgrade package checks use isolated roots; no live Beta 4 installation or
Zorin acceptance is claimed. Exact source/payload/module/version/privacy checks
are part of packaging.

Earlier Beta 3 actual disposable loop-mount/localhost SMTP TLS setup tests and
Beta 2 verified HTTPS/rollback tests are carried forward, not new Beta 4 hardware
or network acceptance. The runtime recovery engine and network implementation
are unchanged by this release. Permission adjustment supports eligible files only;
directories, ACLs, unsafe ownership/links and known app bind-mounted configuration
need separate owner review. The target's specific offending ancestor has not been
identified from the supplied evidence; the new diagnostics must establish it.

| Evidence | Scope |
| --- | --- |
| UI36 physical tests | Five-minute drive-return timeout/failure email, late return/recovery email, connected-storage reboot; storage ready before app starts and no repeated startup |
| UI39 simulations/browser/HTTPS | Backend manual Start/Restart storage refusal, wrong/missing storage/images, monitoring off, retained stops and dashboard/Companion response handling |
| UI40 simulated lifecycle tests | Normal/canceled/fallback upgrade, old payload installed, repeated preparation, surviving workers, disabled LAN and existing-image CLI registration |
| UI40 installed Ubuntu host | Actual canceled old hook followed by corrected fallback; old web/broker processes and workers replaced; authenticated localhost/verified HTTPS; settings, mounts, receipts and container start times preserved |
| UI40 manual acceptance, operator-reported | Safe unmount stopped dependent apps; dashboard disabled starts and Companion refused without sending a command; remount left apps stopped; explicit starts succeeded and existing files were visible; Immich briefly showed Starting before Running |
| Companion 0.2.6 | Prior actual Companion HTTPS tests with simulated storage/Docker; unchanged module in this beta |

The manual acceptance above is user-reported, not an independently captured trace of
each command. Because clients blocked starts before execution, it does not prove a
physical backend-refusal attempt; that guard has separate simulated/HTTPS coverage.
Do not repeat the completed physical timeout, reboot or manual cycle for packaging.

Erugo authenticated upload/download on Ubuntu is deliberately deferred to target-host
acceptance. Visible files and Running status do not establish transfer integrity.
Immich's observed normal startup does not establish arbitrary delayed database/cache
readiness. Direct Docker starts do not execute Compose dependency ordering.

Exact beta package checks and checksums are recorded with the release artifacts.
No live installation of this beta or Zorin deployment is claimed; installed UI40
evidence is carried forward separately. Installer tests use isolated roots and
simulated service processes, not a fresh booted distribution test.

Remaining deployment requirements: one recovery owner; reviewed existing watcher
shutdown/USB cleanup; correct filesystem/image identity; native media-server, FTP
and backup-job coordination; authoritative Compose/runtime policy agreement; and
direct-start application dependency readiness. USW's optional systemd-service
restarts after recovery do not provide pre-unmount shutdown or boot storage gating.

The historical Companion HTTP 503 cause remains unidentified. Its existence does
not by itself establish a core recovery failure. Status freshness is independent
and confirmed command results are retained; no universal transport guarantee is
claimed. USB capabilities vary; software reconnect is not proof of electrical power
loss. Packages are unsigned; checksums verify integrity, not publisher identity.
