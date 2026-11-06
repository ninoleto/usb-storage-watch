> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI15 — Docker restart controls and audit

Version: `2.0.0~ui15`. Test build, with UI14 drive removal and UI13 network settings retained.

## What this setting does

**Restart containers after drive recovery** selects existing Docker containers
that should be restarted when their storage has recovered from an outage.
It does not install applications or modify Docker Compose/YAML.

1. Select the drive in Docker & Applications.
2. Stop drive monitoring before editing these settings. Containers keep running.
3. Select the containers to restart, enable the restart setting and save.
4. Run Check storage access, then start drive monitoring.

A container observed running before an outage is restarted after its required
storage is verified, even if the container process remained running throughout
the outage. If it exited during the outage, it is started. Containers observed
stopped or paused are left untouched. A missing or stale pre-outage observation
does not authorize guessing that a stopped container should be started.

## Storage requirements

| Existing Docker storage mapping | Required before a start/restart |
| --- | --- |
| Ordinary folder on the selected USB drive | Verified USB filesystem |
| Folder inside a configured virtual image | Verified USB filesystem and that image |
| Several folders using different images | Every image those folders require |
| Unrelated image used only by a backup program | No dependency on that image |

Requirements are detected from Docker's actual folder mappings. Required images
must have Mount on recovery enabled. The restart controls do not move data or
change Docker's storage paths. Technical mappings are in Details. When there
are multiple eligible folders, the access-check choice selects an existing
mapping for verification; it cannot bypass another actual storage dependency.

## Interface changes

- Docker controls and results describe start/restart actions rather than saying
  the container is recovered.
- Single-choice storage-folder dropdowns are removed. Required storage is
  explained beside each container.
- Saved settings, unsaved selections and validation messages are distinguished.
  Enabling restart requires at least one selected container.
- Drive removal is separated from normal controls at the right of overview
  cards, with its own separated row on narrow screens. Confirmation is retained.

## Audit corrections

- Pre-outage container observations are checked against the first failed drive
  observation and the configured polling interval, rather than a fixed 30-second
  window measured after confirmation. Long polling intervals and additional
  confirmation checks no longer discard a valid recent running-state sample.
  Wrong-boot, future, invalid and stale evidence is still rejected.
- Removing a drive checks whether another active drive's selected containers
  use its storage. Such a dependency blocks removal with the container/owner
  named. Unavailable Docker inspection fails closed where this check is needed.
  The check runs before monitoring is stopped and again before retirement.
- An older asynchronous status response cannot overwrite newer settings or
  monitoring state. A lost save response is reconciled by reading the saved
  configuration without replaying the write.
- The existing kernel process-exit test now explicitly skips executors whose
  exposed procfs does not match their PID namespace. Its real assertions remain
  active on matching Linux hosts; production process safety checks are unchanged.

## Audit boundaries

Container identity, existing folder mappings, filesystem identities, required
images and inside-container access remain checked. One start/restart intent is
recorded durably per container per incident. A lost response is verified without
blindly repeating the action. Intentionally stopped containers remain stopped.

This is not a general Docker crash watchdog. An old container mount namespace
may prevent safe filesystem recovery; the app does not stop containers merely
to bypass that refusal. Verification does not establish file integrity or full
application correctness. No production Docker installation or physical drive
was changed while preparing this release. See the included TEST-RESULTS.txt for
the exact automated checks and remaining host acceptance limits.
