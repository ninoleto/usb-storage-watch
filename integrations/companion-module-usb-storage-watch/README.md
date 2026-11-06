# USB Storage Watch Companion module 0.2.6

A separate local-test module; Storage Watch UI36 remains unchanged. Read
[HELP](companion/HELP.md) for configuration, status variables and the one-press operation and result display. No commands are replayed automatically.

Dependencies are pinned in package-lock.json. Runtime: Node 26, Companion 5.1+.
The official packaging tool 3.1.1 declares Node 22.18+ for its build process.

```sh
# With supported Node 22.23+ for package installation/build:
npm ci --ignore-scripts
npm run package
# With Node 26 for runtime checks:
npm test
# From the full Storage Watch source checkout, optional real-broker fixture:
USW_NODE=/path/to/node26 python3 test/broker_fixture.py
```

The broker fixture uses real HTTP, login/CSRF, existing broker locks and worker
subprocesses, with synthetic storage and Docker. It never targets host storage.
The Node tests use local synthetic HTTP/TLS servers and mocked state for dangerous
actions. They are separate from actual Companion placed-button checks against the
real broker with simulated operating-system boundaries.

Official references consulted:

- [Module setup](https://companion.free/for-developers/module-development/home/)
- [Developer folder](https://companion.free/for-developers/module-development/local-modules/)
- [Node compatibility](https://companion.free/for-developers/module-development/module-lifecycle/updating-nodejs/)
- [Official module-base API](https://github.com/bitfocus/companion-module-base/tree/main/packages/base)
- [JavaScript template](https://github.com/bitfocus/companion-module-template-js)
- [Core development](https://companion.free/for-developers/core-development/development-flow/)

The old drive-scoped Companion API remains unchanged and available to older
clients. This module uses dashboard sessions to discover multiple drives/apps and
reuse the existing reviewed safe-unmount and app-action endpoints. There is no new
privileged endpoint or independent recovery engine. Public publication is separate.

## Local release validation

One-press controllers and actual packaged presets are tested against an isolated
HTTP/broker fixture. `test/companion_broker_fixture.py` supplies the authenticated
web/broker API, temporary locks/configuration and real worker IPC. It runs synthetic
mount/unmount/standby workers with fake hardware, Docker and service boundaries.
`test/placed-buttons.mjs` imports operating presets into a disposable actual
Companion instance and presses each once, then checks worker/command traces,
Working/Completed/refusal text, variables and rendered feedback. It does not enter
codes or invoke review/confirmation buttons.

Run with official Companion core development dependencies (COMPANION_CORE), a
loopback-only test core on port 18000, and this broker fixture on port 8765.
COMPANION_FIXTURE_DB must refer to a disposable database beneath a directory named
`companion-direct`; the fixture seeds its own token. COMPANION_OUTPUT receives
rendered images and evidence. Never use a production Companion configuration.

Node tests cover direct action dispatch, pinned filesystem/container identity,
unmount snapshot races, duplicate presses, no replay, HTTP/TLS/authentication,
unknown state and legacy review compatibility. Broker tests include repeated
intentional unmount/remount/manual starts, stop failure, busy users, real worker
ordering and manual standby with unsettled writes. See HANDOFF on the test host
for release results. Physical Stream Deck and drive operations remain user tests.

The earlier external-host connection/discovery report is operator-provided evidence;
this release is not accessed or deployed there by the agent.

## 0.2.4 response/status correction

Version 0.2.4 separates verified command outcomes from status-read failures.
`connection_message` and `status_fresh` describe inventory availability separately;
Online requires a successful authenticated read. Commands are never replayed.
Action callbacks acknowledge dispatch within Companion's five-second window;
completion is reported asynchronously only from the verified backend response.
Request diagnostics identify endpoint, elapsed time, HTTP status and socket/timeout/
JSON error codes without logging request bodies or credentials. The feedback defect
was reproduced and corrected; the historical network interruption remains
unidentified. Existing 0.2.3 buttons retain their actions and do not need replacement.

`test/companion_https_fixture.py` runs the production Gunicorn HTTPS entrypoint and
real broker with simulated OS operations. Provide generated `certificate.pem` and
`key.pem` under `TLS_FIXTURE_DIR` and a disposable `COMPANION_FIXTURE_DB`. Its parent
configuration directory must contain `fixture-only` with `usw-companion-fixture`.
Run the fixture/core in a loopback-only namespace without USB access. The paired
`test/response-buttons.mjs` imports supplied presets, injects response faults, and
checks confirmed outcomes, read-based reachability and absence of command replay.
It uses the same COMPANION_CORE / COMPANION_OUTPUT variables as the earlier checks;
its test process also needs NODE_EXTRA_CA_CERTS set to the generated certificate.
These injected faults do not prove the cause of a historical network interruption.


## 0.2.5 customizable presets

New opt-in layered target presets provide Custom name, Live status, Action and
Command outcome elements with editable boolean state overrides. Legacy definitions
remain available for existing linked/copy buttons without rewriting their styles.
See HELP for migration, variable names and conservative power/I/O meanings. UI36
backend behavior and the 0.2.4 response-handling correction are unchanged.

API references: [layered presets](https://bitfocus.github.io/companion-module-base/interfaces/CompanionLayeredButtonPresetDefinition.html),
[text elements](https://bitfocus.github.io/companion-module-base/interfaces/ButtonGraphicsTextElement.html).

`test/usability-buttons.mjs` places copied layered presets in the disposable
Companion, edits text/style overrides through Companion's editor APIs, verifies
actual 72×72 pixels, and checks state changes, exact command targets and stale
feedback. It requires Python 3/Pillow for PNG checks, plus the same HTTPS fixture,
COMPANION_CORE, COMPANION_OUTPUT and NODE_EXTRA_CA_CERTS as response-buttons.mjs.
Restart only that fixture Companion with the same private database, then run with
`USW_RELOAD_CHECK=1` to verify saved customizations. Internal action entity IDs may
be regenerated by Companion; action definitions, options and pinned target IDs
must remain identical. Do not use this script against a real deployment.


## 0.2.6 idle-connection transport correction

One bounded fresh-connection retry is limited to allowlisted read-only status GETs
on a reused-socket ECONNRESET before headers. Writes and safety snapshots never
retry. Per-stream freshness preserves valid fleet or Docker observations through
sibling failures. Editable 0.2.5 layouts and confirmed-result behavior are retained.

`test/polling_https_fixture.py` records real Gunicorn idle connection closures;
`test/polling-buttons.mjs` runs ordinary polls and reads near the idle deadline in
actual Companion, checks retry diagnostics, independent status through broker 503,
and lost command replies. OS/storage/Docker effects remain simulated. This is not
a physical network/hardware test. Use only the existing isolated fixture setup.

References: [Node reused-socket race and idempotent requests](https://nodejs.org/api/http.html#requestreusedsocket),
[HTTPS global-agent defaults](https://nodejs.org/api/https.html#httpsglobalagent).
