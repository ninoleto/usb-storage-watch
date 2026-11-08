# USB Storage Watch — contributor instructions

## Release policy — maintainer decision, 2026-11-08

Use a continuous release model with normal versions such as 2.0.2, 2.0.3,
2.0.4 and 2.1.0. Do not automatically introduce Beta, RC or Preview releases.
The current target is **USB Storage Watch 2.0.2**, application/display/Debian
version 2.0.2, tag `v2.0.2`, as a regular GitHub release marked Latest.
The unissued RC1 naming plan is abandoned; retain its work and history.

Publish useful fixes and improvements regularly without waiting for perfect
software. Record known bugs, hardware limitations and incomplete testing honestly.
Prioritize filesystem integrity and data safety over release frequency; never
publish a known data-corruption risk as an ordinary bug fix. Preserve backwards
compatibility whenever practical. Release notes describe actual changes rather
than narrating development history. Do not imply extensive Linux/hardware
qualification or promise protection against data loss.

For 2.0.2, reuse the prepared source/docs/validation and preserve the proven Beta 6
recovery engine without functional changes. Version changes and rebuilding are
authorized. Do not install on ZORIN, alter its configuration or restart services.
Retain archived releases/assets, Git history and source branches. Delete previous
GitHub releases only after the new release and all downloads are verified.
Remove only Beta tags proven unnecessary to automation, documentation and active
branches; preserve unrelated tags. The goal is one published 2.0.2 release, Latest.
These instructions apply to future sessions unless the maintainer changes them.

Read README.md and docs/VALIDATION-CURRENT.md before changing behavior.
Keep changes focused and use isolated storage/Docker/email fixtures for tests.
Do not operate real hardware or services without explicit authorization.

Preserve exact filesystem/container identity, storage verification, recovery locks,
incident-scoped cleanup, durable no-return deadlines and uncertain-action receipts.
Never use forced/lazy unmount, implicit formatting or automatic reassignment by name.
Ordinary bind-mounted folders work without virtual images. Startup and recovery
selections remain independent; monitoring off does not disable healthy manual use.
Manual Start/Restart verifies saved storage before Docker mutation. Stop retains
its existing restrictions. Safe unmount stops/verifies selected dependent apps;
remounting must not undo deliberate app stops.

Keep authentication, CSRF, privileged broker boundaries and TLS verification.
Companion controls share backend guards and must not replay uncertain commands.
Keep configuration, tokens, certificates, logs, host identities and private state
out of Git and release artifacts. Preserve upstream licenses/checksums.

Run focused affected tests. Build before artifact/privacy/installer checks.
Use tools/integration_test.py --smoke-only for isolated installer checks.
Distinguish simulations, observed host tests and unverified behavior in reports.
No publishing, remote deployment or broad refactoring is implied by a code task.
