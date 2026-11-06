# USB Storage Watch — contributor instructions

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
