# Current validation and limits

Beta **2.0.1~beta3**, tag **v2.0.1-beta.3**, fixes recovery activation with registered
mounted images and actionable SMTP-setup refusals. Companion **0.2.6** remains
byte-identical. Beta 2's first-HTTPS and reviewed image-adoption fixes remain.
No target-host acceptance is implied.

Beta 3 reproduces both failures on unchanged Beta 2. The fresh authenticated setup
sequence covers physical registration, mounted-image adoption, monitoring,
recovery activation, SMTP save/test and drive notifications. An isolated mount
namespace exercises two actual disposable ext4 loop mounts, their kernel/backing
identities and unchanged fstab/data/permissions. A localhost SMTP TLS sink uses
certificate verification. Discovery, PAM, service control and Docker are simulated;
no production service, physical drive or container is operated. This is not a
real systemd service/boot test. Refusal cases cover unknown/changed topology and
identities, stale reviews, locks, missing/unreadable/invalid email and distinct
service errors. Existing Docker/Compose, optional-image, manual-start storage,
repeated recovery and boot regressions are retained.

Packaged browser checks use real localhost HTTP/session/broker handlers at
320/768/1440 px. Private-root fresh/upgrade tests preserve configuration/state,
synthetic credentials and disabled LAN. Python 3.12.16 / Flask 3.0.2 are checked
separately from the development interpreter, not the target host's exact Python
patchlevel. Beta 2's real verified HTTPS, rollback and certificate/hostname refusal
regressions also pass against the package. Source/payload/module checksums match.

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
