# USB Storage Watch 2.0.2 — validation and limitations

2.0.2 is a normal release under the maintainer's continuous release policy.
A normal version number does not mean complete automated testing, broad hardware
qualification or guaranteed recovery. Known test gaps are retained below.

## Source provenance and installed ZORIN verification

2.0.2 continues the prepared source at commit
`4478a568721e5a55af1f9004e294001cdd799a83`, which descends from the preserved
Beta 6 baseline `b06286f72f25744cd91331b3bd28918d69b5d0fd`.
It changes release identity, packaging metadata, documentation and release policy.
The recovery engine and installation lifecycle are preserved.

Before preparation, 385 tracked Beta 6 source files, four saved published assets
and 117 packaged runtime files matched retained manifests. On November 8, 2026,
the maintainer supplied read-only output from ZORIN through ANTEC:

```text
install ok installed 2.0.1~beta6
Files: 117
Code SHA256: a347f3cefb690085a1cbf633e8d05508b8ecd083ade1b02dc8a62abf016fbb71
```

This exactly matches the preserved Beta 6 package/source fingerprint. The deployed
source is confirmed; it does not need to be checked again to identify this baseline.
No direct ZORIN connection or host change was performed during preparation.

## Maintainer-reported hardware testing

On **November 8, 2026**, Beta 6 recovered following a host reboot and physical
USB cable disconnection/reconnection on **Zorin OS 18.1**, an **Intel N97 mini PC**,
with an external **Hitachi USB HDD**, **ext4**, Docker containers and dependent
virtual images.

Automatic recovery succeeded on **Attempt 1** in approximately **1 minute 52 seconds**.
The main ext4 filesystem was restored and verified, including UUID, filesystem
type and read/write flags. The dependent virtual image was restored. Erugo, Plex,
Immich and PhotoPrism restarted; container checks passed; application functionality
was manually confirmed.

**Previous ZORIN tests encountered serious mount recovery difficulties.**
The successful result does not erase those failures or guarantee future recovery.
Earlier successful **Ubuntu Studio 26.04.1** testing used different versions and
storage devices. Neither result is a new physical test of the exact 2.0.2 package.

## Checks performed for 2.0.2

Performed on November 8, 2026, with simulated storage, Docker and service
boundaries and temporary private state:

| Fresh check | Result |
| --- | --- |
| Focused Python 3.12.16 suite | **194 passed**, no failures, errors or skips: 184 core/standby/unmount/USB/manual-storage/distribution checks plus 10 HTTP checks. GUI fixtures use the extracted 2.0.2 payload. |
| Packaged identity and API | Rendered title/footer, authenticated Flask-to-broker status, CLI and all five static assets agree on 2.0.2; no-store headers retained. |
| Recovery preservation | 114 of 117 runtime files are byte-identical to Beta 6. Only version constants and the previously prepared HTML/version rendering differ. Settings behavior AST is unchanged. The only runtime difference from the prepared candidate is version constants. |
| Installer preservation | Portable installer, four maintainer scripts, systemd units/timer and example configurations remain byte-identical to Beta 6 (15 files). |
| Private installer smoke checks | **11 passed**. The twelfth check, systemd unit verification, was blocked by sandbox socket permissions. This is not a fully passing installer suite. |
| Package upgrade and rollback | Actual saved Beta 6 package → 2.0.2 → retained Beta 6 in private dpkg roots passed; synthetic configuration, state, credentials, certificates and disabled LAN preserved. No live services were operated. |
| Build and packaging | Existing builder; all application/API/display/Debian versions are 2.0.2. Exact source/archive and installer/payload equality and SHA-256 manifest checked. Companion 0.2.6 bytes unchanged. |
| Privacy and documentation | Full public tree plus source/package privacy scans; current Markdown rendering, local link targets, prominent warning and operator shell syntax checked. Local artifacts/caches/private data excluded. |
| Version ordering | 2.0.2 sorts above both Beta 6 and the unissued prepared candidate. |

The complete automated suite was not rerun for this version/documentation change;
its known incomplete results are preserved below. No new unrestricted browser,
verified-TLS or systemd acceptance is claimed. In-process HTTP checks do not
establish network reachability or physical hardware behavior.

## Inherited automated results — incomplete

The preceding preparation performed:

- 184 passing focused checks across core/standby/unmount/USB/manual-storage/
  distribution modules on Python 3.12.16.
- Packaged title/footer, authenticated Flask-to-broker API, CLI and cache checks.
- Eleven isolated installer checks and private-root Beta 6 upgrade/rollback.
- Exact payload/source comparison, privacy scans, checksum and documentation checks.

Its full Python 3.14.4 suite ran **1,352 tests with 100 errors and 24 skips**.
It was **not a passing full suite**. The errors comprised 60 checks requiring an
unavailable trusted Docker Compose plugin, 28 older recovery fixtures with non-ISO
timestamps, eight sandbox-blocked TLS/Docker socket checks and four browser setup
errors. An expanded 238-test focused run also had one failure and eight error
entries in older web-broker fixtures that insufficiently isolate host configuration.

Eight representative failures reproduced on untouched Beta 6 (one failure, seven
errors). This identifies those examples as inherited/environmental; it does not
establish a completely passing application. The recovery engine was not modified
to silence failures. These results are historical and are not presented as a new
full 2.0.2 run. The maintainer authorized a normal release retaining these limits.

See [the preserved preparation report](VALIDATION-PREPARATION-HISTORY.md) for
details, and [Beta 6 historical validation](VALIDATION-BETA6-HISTORY.md).

## Not performed and compatibility limitations

- No live 2.0.2 installation, production upgrade, service restart, physical cable
  test, USB reset, forced unmount, filesystem repair or reboot during preparation.
- No exact-2.0.2 physical acceptance on ZORIN or Ubuntu Studio.
- No extensive cross-distribution/kernel/controller/adapter or ARM qualification.
- No new real HDD standby/wake, live I/O attribution or electrical power-cycle proof.
- No new application transfer-integrity, inbox-delivery or actual Companion-host proof.
- Historical Companion HTTP 503 remains unexplained; module 0.2.6 is unchanged.

USB controller and adapter capabilities, filesystem errors and busy mounts can
prevent recovery. Some failures need manual intervention or reboot. Required
storage must be verified before Docker services restart. Software reconnect/reset
does not prove electrical port power removal. Recovery is not guaranteed in every
failure scenario and does not guarantee protection against data loss.

The software is provided as-is. It is developed and tested primarily on the
maintainer's own equipment. Other Linux environments and hardware may behave
differently; users must test recovery on their equipment before relying on it.
See the prominent [hardware warning](../README.md#hardware-compatibility-and-testing).

## Publication verification

The local remote is `https://github.com/ninoleto/usb-storage-watch.git`.
This execution sandbox currently rejects network socket creation, so live
repository/permission/release checks and publication cannot be completed here.
No release, Latest designation or downloaded public 2.0.2 checksum is yet verified.
All historical releases and tags remain untouched. Six cached release records,
24 assets and complete Git checkpoints are archived locally. A fresh live inventory
and download verification are required before any historical-release deletion.
