# Beta 6 candidate validation

Candidate `2.0.1~beta6` extends published Beta 5 with guarded mounted standby and
passive per-container I/O diagnostics. No release publication or host installation
is part of preparation. Prior validation below is historical evidence, not repeated
physical acceptance of this change.

Focused tests use temporary kernel/cgroup fixtures and simulated Docker, mounts,
power and flush operations. They cover idle running consumers/open files, continuing
reads/writes/discards/flushes and pending requests, image order and activity, changed
identities/mounts, swap and incomplete counters, missing/shared cgroup metrics,
no double counting and invalidation of confirmed sleep after subsequent I/O.
Affected unmount, recovery cleanup, USB identity and manual app-start guards pass.

Chromium checks run the packaged UI and authenticated broker at 320/768/1440 px.
Companion production 0.2.6 client/controller checks use localhost verified HTTPS,
management-token/session/CSRF authentication and the same guarded standby path.
Worker launching/storage/Docker/power are simulated; the locks and backend are real.
These are client integration tests, not actual Companion host/Stream Deck tests.
No physical drive was put to sleep and no production service/container was operated.

Private-root fresh/upgrade, package/payload/version/privacy and unchanged Companion
checks are recorded with the candidate. See [HDD standby](HDD-STANDBY.md) for hardware
acceptance steps. Adapter standby confirmation, normal wake/access with running
apps, automatic physical standby and target-host compatibility remain unverified.
The old optional Companion review-only description still says “busy users”; the
supported one-press controls use the corrected backend and return its actual reason.
Companion 0.2.6 bytes are preserved; no button replacement is needed for this backend
change. The legacy review wording can be updated in a separate module release.

## Previous Beta 5 evidence

# Current validation and limits

Beta **2.0.1~beta5**, prepared tag **v2.0.1-beta.5**, completes reviewed access changes
for eligible Compose project directories and configuration files. It separately
corrects Portainer product-label ownership classification. Green saved-state badges,
Companion **0.2.6**, network behavior and automatic recovery are unchanged.

Focused checks cover a PhotoPrism-like project directory and Compose file writable
by a shared group containing a synthetic `plex` account, while writable application
data remains in a child directory. Immich-like project/environment/setgid modes,
only-necessary write removal, stale confirmations, app locks, other-app data mounts,
missing inventory, partial restoration/uncertainty and normal settings save are
covered. Docker/services/account lookup are simulated; temporary Unix permissions,
descriptor operations and Compose rendering are real. A separate root-only kernel
fixture drops a child process to disposable numeric credentials: project entry writes
are removed while child-data creation/rename/read/write continue. No host accounts,
production permissions, real apps, disks or services are operated.

Chromium at **320/768/1440 px** uses real localhost HTTP/session/broker handlers to
confirm the combined access plan, stale refusal, retained drafts/child permissions,
normal explicit save and green collapsed badges. Python **3.12.16**, Flask **3.0.2**
and private PyYAML **6.0.3** cover compatibility; not the target's exact dependency set.
Exact payload/source/module/checksum/privacy and private-root fresh/upgrade checks
are part of packaging, not a live distribution installation or target-host test.

Source inspection distinguishes Portainer's documented product and external
access-control labels from management evidence. Compose-deployed server/agent
fixtures pass normal source verification. Explicit management markers stay refused;
unknown namespace hints or manager-private paths stay unverified. No live Portainer
control database/API was queried; absence of an external controller is not proven.
See [Docker setup](DOCKER-SETUP.md) for source references and exact limitations.

Remaining GUI stops: unsafe ancestors outside the project, ACLs/links/ownership,
account-home/mount/shared-storage roots, direct app-data use, unavailable inventory
or memberships, missing/non-directory child data sources, and unsupported/ambiguous
Compose sources or external management. Native services are not fully inventoried;
the confirmation explains lost directory-entry writes rather than claiming safety
for native media/FTP consumers. The supplied target-host screenshot did not establish
numeric modes; only fixture modes are stated. Target acceptance is pending.

Earlier Beta 3 disposable loop-mount/SMTP TLS and Beta 2 verified HTTPS/rollback
checks are carried forward. No new physical storage/reboot or TLS test is claimed.

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
