> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# DEV7 — TEST ONLY

DEV7 fixes interactive-state loss, management-token retrieval and Email layout.
It retains the DEV6 recovery engine, USB logic, LAN listener separation, SMTP,
virtual disk image permissions/recovery and restricted Companion API. The separate
Companion module is unchanged. No physical systems or USB hardware were accessed.

## What caused the collapsing form

DEV6 preserved the outer Technical drive details node but reconciled its contents
against a fresh status tree. Permission editors were appended only after a click,
so the next poll treated them as obsolete and removed them. Preserving accordion
`open` attributes alone could not preserve the missing form.

Live rendering now has explicit editor boundaries. Technical details contains a
persistent permission-editor slot; polling reconciles display nodes and leaves
interactive subtrees alone. Unchanged text and DOM nodes remain in place. Stale
navigation responses are discarded. Network address updates preserve a draft
selection, even if that address disappears; notification saves no longer reload
SMTP drafts. Monitoring continues throughout editing.

The defect was reproduced against DEV6 in real Chromium at 1280, 768 and 390 CSS
pixels: the nested editor disappeared during actual 10-second polling. Regression
coverage waits 32 seconds, verifies at least three successful status responses per
viewport, and checks parent/nested expansion, selections, unsaved values, focus,
text selection and scrolling. A changed connection state must update while the
form stays open. Other real-poll workflows cover image creation, technical network
forms, file inputs, disappearing IP addresses, timings, service text and Email.

## Retrievable management token

First installation creates a cryptographically random token in the root-owned,
mode-0600 file `/var/lib/usb-storage-watch/management.token`. The state directory
is secured without recursively changing its contents. Retrieve the token with:

```sh
sudo cat /var/lib/usb-storage-watch/management.token
```

DEV6 hashes cannot be reversed. Upgrade adds a new retrievable credential while
keeping the original DEV6 verifier and credential valid. Authenticated Advanced
settings clearly identify this transition. **Replace management token** explicitly
retires every old management credential and all sessions; Companion tokens are
separate and unchanged. Migration itself does not clear live sessions, but the
existing package service restart requires signing in again.

The canonical private token record is atomically replaced and its verification
digest is derived from that same read, avoiding two out-of-sync credential files.
A private initialization marker prevents missing-file fallback from reactivating
retired credentials. Missing files require explicit localhost administrator
recovery, not silent replacement on the next upgrade. A rotation error after the
credential commit still invalidates sessions. Existing tokens are never returned
by HTTP, included in URLs or logged. Normal login remains token-only.

## Verification and limits

Focused tests cover fresh/upgrade provisioning, credential preservation, rotation,
lost-file recovery, interrupted writes, file permissions, CSRF, authorization,
logout and transport boundaries. The full existing recovery, image, Companion,
listener and browser suites remain required. Installation validation uses private
dpkg roots; real root-owned token provisioning uses temporary directories and
checks that a non-root account cannot read the token. Listener tests use a private
network namespace, real HTTP/TLS and synthetic credentials.

The transfer bundle's TEST-RESULTS.txt records final counts, installed-payload
checks, upgrade preservation, privacy results and packaging warnings. These tests
do not establish a booted Ubuntu Studio 26.04.1 installation or physical hardware
compatibility. Physical acceptance should verify token retrieval/login and nested
permission editing over repeated refreshes, including phones/tablets. No physical
USB reset, formatting, live Docker or real SMTP test was performed for DEV7.
