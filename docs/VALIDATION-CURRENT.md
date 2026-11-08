# USB Storage Watch 2.0.1 RC1 — validation

RC1 is a release candidate undergoing further reliability testing.
This report distinguishes source/package checks, isolated simulations and hardware
observations. Final publication requires deployed-source identification and
successful GitHub verification; neither is inferred from a build.

## Source provenance

The frozen Beta 6 baseline is commit
`b06286f72f25744cd91331b3bd28918d69b5d0fd`.
Before RC1 changes, all 385 tracked source files, four saved published downloads
and 117 packaged runtime files matched the retained manifests. A local annotated
checkpoint and verified Git bundle preserve that source. The UI's “Beta 5” footer
is present in those exact Beta 6 bytes; the runtime version is `2.0.1~beta6`.

The maintainer reports the installed Beta 6 hardware result below. An independent
fingerprint of the installed ZORIN code is still pending; preparation has not
connected to ZORIN. Publication and historical-release deletion remain gated on
that match. No new RC1 hardware test is claimed.

## Maintainer-reported hardware evidence

On November 8, 2026, Beta 6 recovered after physical USB cable disconnection and
reconnection following a host reboot: Zorin OS 18.1, Intel N97 mini PC, external
Hitachi USB HDD, ext4, Docker containers and dependent virtual images.

Automatic recovery succeeded on Attempt 1 in approximately 1 minute 52 seconds.
The main filesystem, UUID, filesystem type and read/write flags were verified;
the dependent image was restored; Erugo, Plex, Immich and PhotoPrism restarted;
container checks passed; and application functionality was confirmed manually.

Previous ZORIN tests had serious mount recovery difficulties. This pass does not
erase earlier failures. Earlier successful Ubuntu Studio 26.04.1 tests used other
versions/devices and do not verify the exact RC1 build.

## RC1 automated checks

Completed on November 8, 2026, using temporary fixture state. Hardware, Docker,
service and email mutations are simulated unless explicitly stated otherwise.

| Check | Result and scope |
| --- | --- |
| Source preservation | 114 of 117 runtime files are byte-identical to Beta 6. Only settings version constants, web index rendering and HTML labels differ. Settings AST is otherwise identical. |
| Installation behavior | Portable installer, four Debian lifecycle scripts, systemd units/timer and example configurations are byte-identical (15 files). |
| Build/artifacts | Existing builder produces Debian/source packages, unchanged Companion 0.2.6, release notes and SHA-256 manifest. Exact source/archive and installer/payload equality verified. |
| Version/communication | Extracted package's title/footer, authenticated Flask-to-broker status API, CLI, static assets and no-store headers verified. Application `2.0.1-rc.1`; Debian `2.0.1~rc.1`; Beta 6 < RC1 < stable ordering checked. |
| Focused Python 3.12.16 checks | All 184 tests in ten core/standby/unmount/USB/manual-start/distribution modules passed. These include 148 carried-forward Beta 6 affected checks and 36 distribution checks. GUI fixtures use the extracted payload. |
| Broader focused run | 238 tests ran; the older web broker fixture had 1 failure and 8 error entries, including subtests. It accesses protected host configuration instead of fully isolating that boundary. Representative failures reproduce on unchanged Beta 6. |
| Full Python 3.14.4 suite | 1,352 tests ran: 100 errors and 24 skips. **Not a passing full suite.** See details below. |
| Isolated lifecycle | 11 installer checks passed, covering portable and private-root Debian install/upgrade/remove/purge, preservation and maintainer-script staged-root exits. The final systemd verifier was blocked by sandbox socket permissions. |
| Actual package upgrade/rollback | Published Beta 6 package → RC1 → retained Beta 6 in a private dpkg root passed, preserving synthetic settings, credentials, certificates, state and disabled LAN. No live service installation. |
| Privacy | Full candidate tree and source/package scan passed; no matched credentials, personal email, private key or machine-specific secret patterns. Pinned upstream license/contact text remains. |
| Documentation | Current Markdown rendered locally, local link targets checked, compatibility warning placement and code/table rendering checked. Upgrade/rollback shell blocks passed syntax checking. The operator block was not executed on production. |

The full-suite errors comprise 60 checks requiring an unavailable trusted Docker
Compose plugin, 28 old recovery fixtures passing non-ISO timestamp strings, eight
socket-based TLS/Docker checks blocked by the sandbox, and four browser-class setup
errors (missing browser or Playwright event-loop state). The separate packaged
Chromium attempt failed at launch with `setsockopt: Operation not permitted`.
No new browser/verified-TLS/Companion client acceptance is claimed.

Eight representative timestamp, Compose, old web-fixture and socket failures
were rerun on untouched Beta 6 and reproduced (one failure, seven errors).
This establishes those examples as inherited/environmental; it does not turn
the complete RC1 suite green. No recovery code was changed to silence tests.
Unrestricted systemd/browser/TLS checks and a clean, isolated full-suite result
remain outstanding before claiming complete automated release validation.

GitHub CLI access in this preparation environment failed DNS resolution for
`api.github.com`. The live release inventory, publication, Latest designation,
public downloads and final GitHub presentation have not been verified. All
historical releases/tags remain untouched. Six cached release records and 24
saved assets were hash-verified and backed up locally, pending fresh enumeration.

## Not performed and limitations

- No automatic production upgrade, live RC1 installation, physical disconnect,
  USB reset, forced unmount, filesystem repair or production reboot.
- No exact-RC1 hardware acceptance on ZORIN or Ubuntu Studio.
- No electrical per-port power-cycle proof, broad adapter/controller/kernel
  matrix or ARM architecture qualification.
- No new real HDD standby/wake or live container I/O attribution acceptance.
- No new application transfer-integrity or inbox-delivery proof.
- Historical Companion HTTP 503 remains unexplained; module 0.2.6 is unchanged.

See [hardware compatibility](../README.md#hardware-compatibility-and-testing).
Some filesystem failures need manual intervention or reboot; busy mounts can
prevent recovery; storage verification precedes dependent Docker starts.
Recovery does not guarantee protection against data loss.

[Earlier Beta 6 validation](VALIDATION-BETA6-HISTORY.md) and
[historical reports](README.md#historical-evidence) remain available. They are
historical evidence rather than repeated RC1 hardware testing.
