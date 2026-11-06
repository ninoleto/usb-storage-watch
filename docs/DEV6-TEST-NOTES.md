> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# DEV6 — TEST ONLY

Checkpoint: `checkpoint/pre-dev6-companion-20261030` at DEV5 `9d519db`.
Development stays on `dev/simple-2.0`. The separate local Companion repository is
not published. No production access, physical USB operations or live Docker tests.

DEV6 reuses the existing recovery engine, guarded manual controls, standby,
authentication/session infrastructure, SMTP, image permissions and independent
local/LAN listeners. Engine changes are limited to its version identifier.

- Overview updates existing DOM nodes, retaining expanded technical details and
  text selection across polling. Graphite theme uses green actions, purple primary
  buttons, amber Stop, teal numeric adjustment, orange Reset and red destruction.
- Timing groups separate monitoring, USB, HDD standby and applications. Idle sleep
  has one home under Advanced. Virtual Disk Images have Create new/Add existing
  tabs, revised optional-feature explanation and unchanged stored paths/data.
- Passive flash metadata overrides misleading bridge rotational flags. Unknown
  mechanical capability is reported honestly; no power probes run during polling.
- Dashboard login consistently uses management tokens. Local-only administrator
  bootstrap/recovery generates a one-time token; rotation invalidates all sessions.
  Existing hashes remain valid. LAN Linux-password login is refused even over TLS.
- Certificate help covers public CA verification/trust, SAN identity, expiration,
  platform restrictions and private-key handling. DEV5 listener architecture and
  its HTTP acknowledgement, local access and rollback remain unchanged.
- Scoped Companion API v1 exposes passive status/capabilities and existing guarded
  controls. The legacy sleep endpoint/token remains compatible. See COMPANION.md.

Validation includes focused unit/browser regressions, existing recovery suites,
private real Gunicorn HTTP/HTTPS listeners and rollback, certificate SAN/trust and
reuse, non-root image access on disposable QEMU disks, Debian upgrade preservation,
installed-payload tests and privacy scans. Exact counts/results and artifact
checksums are recorded in the transfer bundle's TEST-VERIFICATION.txt.

Remaining physical checks: Ubuntu Studio DEV5→DEV6 upgrade/reboot, retained token
login, ADATA classification and reconnect, port changes/hubs, real phone/tablet
layout, Windows/Linux/Android certificate trust, supported mechanical HDD standby
and no-wake feedback, Companion 4.1 desktop/Stream Deck loading and commands.
No SMART health, independent electrical-power-cut claim, Zorin certification or
physical Docker validation is made. Wake HDD is disabled. Explicit retry restores
mounts only, without resetting USB/rearming automatic budgets/restarting Docker.
