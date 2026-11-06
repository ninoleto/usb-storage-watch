> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI19 — Detached shutdown mount recovery

Version: `2.0.0~ui19`. Test release.

## The reported failure

A USB filesystem returned with a new Linux device number while its previous
mount remained at the configured location, marked `shutdown`. UI18 reported
the returned device as unmounted, refused to mount over the old mount, and
never reached the image or container restart stages.

UI19 reports the conflict explicitly. Long messages use the action row or
dialog width, instead of a narrow column beneath one button.

## Recovery behavior

While the drive is healthy, monitoring records its mount identity and USB
attachment. After a disconnect, a narrowly verified old shutdown mount can
be removed with one ordinary unmount before the returned drive is mounted.
The existing filesystem checks, selected image mounting and selected Docker
restart sequence then continue.

The cleanup requires the same previously verified mount, in the same boot;
the old block device must have disappeared and the returned drive must have
a different verified attachment. The current target must be unambiguous,
without nested mounts, and its expected filesystem and hardware must pass
the existing checks.

There is no forced/lazy unmount, recursive cleanup, automatic filesystem repair
or automatic stop of containers. Busy storage, other filesystems, surviving
old devices, changed mount identities, nested mounts and insufficient proof
produce an explicit refusal. Each cleanup attempt is recorded before execution;
the same old mount is not automatically retried, including after a busy refusal
or uncertain result. A timeout never proceeds directly to mounting the returned
drive.

Mounts marked shutdown or emergency read-only are unhealthy even if they still
show the rw option. Existing unsafe/uncertain recovery blocks remain blocked.
The configured wait still precedes the single recovery attempt. A drive that
returns after that attempt has failed needs a user-requested Mount operation;
reconnection alone does not grant another automatic attempt.

## First upgrade from UI18

UI18 did not record the exact mount identity required by this cleanup. An
upgrade cannot reconstruct that proof or replay a completed failed incident.
For an already failed drive, restore the mount normally once. Then start
monitoring while it is healthy so UI19 can record the baseline for subsequent
disconnects. No disk or image needs to be formatted or recreated.

For the specific reported example drive incident, the old mount had no nested image
mounts and Erugo was stopped. The user was given one normal unmount of that
configured location, followed by Mount drive in the app. That instruction is
incident-specific; do not apply it indiscriminately to another drive.

## Retained behavior

- Docker Start, Stop and Restart remain available independently of monitoring.
- Docker drive/image restart selections remain user-controlled; detection is advice.
- Selected image mount failures are reported without imposing a new Docker gate.
- Image creation/confirmation, local feedback, separated removal, touch controls,
  network settings and certificate instructions remain included.

## Verification limits

See TEST-RESULTS.txt in the release ZIP for executed tests. Device and Docker
responses are synthetic; the test environment cannot perform kernel mounts.
No physical drive or container on the user's server was operated by the build.

Technical reference: [Linux ext4 shutdown status](https://linux.googlesource.com/linux/kernel/git/torvalds/linux/+/a3d97d1d3fa68253927a6e6c2fdfe7c039073af7/fs/ext4/super.c),
[normal unmount behavior](https://kernel.googlesource.com/pub/scm/utils/util-linux/util-linux/+/refs/heads/stable/v2.41/sys-utils/umount.8.adoc).
