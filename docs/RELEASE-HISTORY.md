## Historical release notes

The records below describe earlier releases. Their login, activation, recovery and
validation statements do not override the current README or validation above.

# USB Storage Watch 1.1.1~rc3 — simple setup candidate

Setup now offers a drive list, automatic recovery, optional email and one
**Activate protection** button. Existing valid connection settings are preferred;
a mounted drive stays in place. Hardware recovery, Docker and optional location
migration remain in Advanced settings. Basic recovery never requires port qualification.

A necessary narrow recovery fix permits protected desktop drive directories on
the host's `/run` tmpfs, with safe recreation of directories removed by desktop
cleanup. All existing disk identity, filesystem and conflicting-mount checks
remain enforced. No repair, unmount or USB reset is introduced by setup.

**Not release-ready.** [RC3 evidence and physical acceptance](SIMPLE-SETUP-RC3-VALIDATION.md)
distinguish automated fixture results from the still-required real Ubuntu Studio test.
Prior recovery and physical USB results below remain historical evidence.

# USB Storage Watch 1.1.1~rc2 — migration correction candidate

RC1 failed physical setup with an existing UUID-based entry at a desktop path.
RC2 allows that valid entry to be kept and adds optional stable-path migration
with private backup, interruption recovery and protected rollback. USB2/USB3
peer diagnostics now distinguish a potential connector pair from missing proof
or unsupported controls. Paired resetting remains unavailable in this release.

**Not release-ready:** the actual Ubuntu Studio configuration workflow must pass.
See [RC2 validation and acceptance steps](MIGRATION-RC2-VALIDATION.md) and the
[offline peer qualification plan](USB-PEER-QUALIFICATION.md). Earlier candidate
reports below are historical; they do not certify this workflow.

# USB Storage Watch 1.1.1~rc1 — setup correction candidate

This candidate corrects the physical-computer setup wizard failures. It is **not
release-ready** until the fresh Ubuntu Studio user workflow passes. The
[validation report](WIZARD-RC-VALIDATION.md) explains the changes, evidence,
remaining limits and browser-only acceptance steps. USB hardware resetting,
Docker recovery and email can all remain disabled while normal automatic
filesystem remounting is configured and monitoring is enabled.

The earlier 1.1.0 recovery results below are retained as historical evidence.
They do not establish that this candidate passes Ubuntu Studio acceptance.

# USB Storage Watch 1.1.0

Repeated physical reconnect validation passed, including two consecutive
storage-plus-Docker recoveries. See the [investigation and results](RECONNECT-INVESTIGATION.md).

Initial public GUI release candidate. Publication requires project-owner
approval; no repository, tag or release has been published by this validation.

USB Storage Watch monitors a removable ext4 filesystem, reports incident
outcomes by authenticated TLS email, and optionally restores storage and
selected Docker containers. The authenticated dashboard provides disk setup,
email testing, recovery settings, container discovery, service controls and
readable event history. Advanced controls remain separate.

This corrected release permits normal mounting over a nonempty directory and
ordinary ext4 journal replay after a disconnect. Underlying directory contents
are preserved. Exact UUID/type, occupied-target, active-namespace, exclusive
block-device, error-state and post-mount read/write checks remain enforced.
Docker actions occur only after storage verification and at most once per
selected container per incident. No forced mount, automatic fsck, formatting or
destructive repair is performed.

Completed outages re-arm on a confirmed new USB attachment, while service
restarts and upgrades retain exhausted budgets. Completed Docker records from
older selections are archived before the new incident runs. The dashboard
separates live disk health, recovery progress, partial application recovery and
historical outcomes.

The CLI now explains and reprompts invalid disk, port, timing, yes/no and TLS
choices. The existing dashboard design, PAM authentication, CSRF protection,
protected SMTP storage, localhost default and explicit HTTPS LAN configuration
are retained.

## Downloads and installation

- `usb-storage-watch_1.1.0_all.deb`: Debian/Ubuntu installer.
- `usb-storage-watch-1.1.0.tar.gz`: complete source tree and portable installer.
- `SHA256SUMS`: checksums of both artifacts.

Verify the manifest in the download directory, then install:

```sh
sha256sum -c SHA256SUMS
sudo apt install ./usb-storage-watch_1.1.0_all.deb
```

Open `http://localhost:8765` on the installed machine and sign in with a named
local administrator account. Monitoring and recovery require explicit setup.
See [installation](../README.md), [GUI setup](WEB-GUI.md),
[configuration](CONFIGURATION.md), and [validation results](FINAL-VALIDATION.md).

## Supported validation scope

Validated on Ubuntu 24.04 in VMware with a real approximately 29.5 GiB ext4 USB
flash drive, rootful Docker, systemd and local authenticated TLS SMTP. The
validation includes operator-performed physical USB disconnect/reconnect cycles,
normal journal replay, preserved checksums and repeated Docker recovery through
the installed service. Earlier guest storage-driver tests separately exercised
failure, loop and timeout paths. This does not establish electrical USB reset
compatibility. USB port resets remain disabled on the unqualified VMware
topology. Other distributions, separate power-fault injection and external
provider inbox delivery are not claimed tested.

Retained active mounts of the returned device, filesystem errors and read-only
storage still require operator intervention. The service does not stop
containers to force a mount. LAN access requires an administrator-supplied
trusted certificate. Builds are reproducible and checksummed, but unsigned.

Project code is MIT licensed. The unmodified bundled Gunicorn 26.2.0 sources
include their MIT license and a per-file integrity manifest; other dependencies
come from the operating system. See [dependency notices](../THIRD-PARTY-NOTICES.md).
Historical 1.0.0 and earlier unpublished 1.1.0 binaries are preserved separately
as local baselines and are not the corrected release assets.
