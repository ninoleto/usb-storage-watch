> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI23: failed-mount namespace correction

## Confirmed failure

The supplied UI22 host diagnostic establishes that the selected container was
stopped and verified, and that the old configured ext4 mount was a disconnected
shutdown filesystem. The returned disk had another device number. Recovery
finished without sending any storage command because the namespace-availability
check rejected a reference to the old device in a process mount namespace.

This was not a failure to stop Docker. The actual refusal was before normal
unmount. The earlier suspected sticky blocker was not the reason in this record.

## Correction

An ordinary unmount of the freshly captured failed mount tree no longer requires
all other process namespaces to stop referring to that old tree. Current exact
mount IDs, targets, filesystem identity, configured child-image backing, dead
physical device and stopped selected containers are still checked. The kernel
performs the normal unmount and its result is read back before continuing.

The returned live device still must pass the existing availability and identity
checks before mount. Loop-device detachment retains its namespace guard. No
foreign namespace is entered, no unrelated process is killed, and no force or
lazy filesystem unmount is introduced.

A completed UI22 namespace refusal with no storage actions can resume once under
UI23 after fresh checks. Uncertain writes are not replayed, and the original USB
reset budget and incident history are retained.

The sequence remains: stop selected containers; ordinarily unmount failed
configured storage; recover and mount disk; mount selected images; start selected
containers; verify; queue the outcome email if notifications are enabled.

## Why the previous check was unsuitable here

Linux process namespaces can retain copies of mounts with different mount IDs.
The old check compared those IDs with the current namespace before even allowing
an ordinary unmount. A current-namespace unmount should not be conflated with a
claim that all namespace references to a filesystem have disappeared.

Primary references:
- https://man7.org/linux/man-pages/man7/mount_namespaces.7.html
- https://man7.org/linux/man-pages/man2/umount.2.html

## Verification boundary

The regression uses the actual namespace parser/checker with synthetic procfs
records, plus the recovery engine and container ledgers with simulated kernel
and Docker boundaries. This environment cannot execute the user's physical USB
outage or production Docker/SMTP operations. See TEST-RESULTS.txt in the bundle.
