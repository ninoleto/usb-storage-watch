> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# USB Storage Watch 2.0 UI5 — TEST ONLY

This test package updates the approved UI4 interface and its existing recovery backend.

## Changes

- Advanced Settings > Network access > Connection security: select HTTP or HTTPS, then choose **Apply network settings**. When LAN is enabled, the service changes listeners through its existing guarded asynchronous operation and verifies the result. If a remote browser connection changes scheme, reopen the displayed new URL. Localhost HTTP remains available. HTTP exposes management tokens unless carried by a properly configured encrypted VPN.
- Event History has **Refresh events** and a last-updated stamp. The current drive's Recent Events has its own Refresh action. Both views update automatically every 15 seconds while visible, without navigating away or losing filters.
- Virtual Disk Images > Already configured now has **Mount on recovery** for each image. Changing the switch updates only the image's recovery preference. It does not mount or unmount the image immediately. If an image is manually unmounted, the existing safety behavior disables its auto-restore until intentionally mounted again. Dependencies may prevent disabling.

## Functionality retained from UI4

- Guarded HDD Sleep now, automatic idle standby, passive status and per-drive timing controls (only visible for supported mechanical HDDs).
- Management-token rotation and authenticated local HTTPS certificate/trust download help.
- Disable concurrent confirmation and cancellation during busy operations; operation progress/verified outcomes.
- Drive-specific monitoring, recovery, safe USB reconnect, user history, Virtual Disk Image mount/unmount and multiple Docker dependency configurations.

## Tests and limits

- UI5 targeted image/network unit tests and Chromium UI tests at multiple viewports passed.
- The historical full Python test suite was run in this cloud environment; it contains tests requiring Flask and mkfs.ext4 which are absent here. Those environment-related failures are not counted as successes. The historical suite must be rerun on Ubuntu Studio before release.
- HTTP/HTTPS LAN listener behavior, HDD standby, image recovery persistence after service restart, physical USB reconnect (which occasionally times out in identity/isolation checks) and live Docker recovery must be verified on the user's Ubuntu Studio test system.
- Do not perform destructive formatting just to test UI5. Do not touch production Zorin.
