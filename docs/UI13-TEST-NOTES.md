> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI13 — network interface and touch controls

This build corrects the UI12 network-interface delivery. It uses the actual
RF433 Button Manager 0.4.0-test.5 source as the visual and interaction reference.
USB Storage Watch keeps its own default ports: HTTP 8765 and HTTPS 8766.

## Corrected Apply behavior

UI12 silently disabled Apply when a changed HTTPS endpoint needed a prepared
trust certificate. The page only said that changes were not applied. This was
reproduced in Chromium before the fix with a saved HTTPS connection, an edited
HTTPS port, and no prepared public CA.

In UI13, a valid changed address, protocol, LAN setting or port enables
**Apply network settings**. Apply prepares missing certificate material before
staging the connection. Downloading the certificate also prepares it if needed.
A bad port or unavailable address has an explicit explanation beside Apply.
No certificate-preparation prerequisite silently disables the action.
The button disables while sending, while a connection test is pending, after
confirmed saving, or when there are no valid changes. Errors stay visible through
background polling. Writes are never automatically repeated after lost responses.

## Matching network interface

The card uses RF's layout, colors, spacing and controls:

- LAN switch, saved Network URL and Localhost URL cards, each with Copy URL.
- Expandable connection-security section with large HTTP / HTTPS choice cards.
- Advanced: address and ports, with a full-width address picker, interface labels,
  separate large minus / number / plus controls, and full-width Reset buttons.
- Apply, local feedback, generated new-connection link, three-minute countdown,
  Confirm connection and Cancel change.
- An expandable certificate guide with separate numbered instructions for
  Windows Chrome/Edge, Linux Chrome/Chromium, Firefox desktop, Android Chrome,
  macOS Safari/Chrome, and iPhone/iPad Safari.

The picker selects an existing private IPv4 interface address supported by USB
Storage Watch; it does not assign an IP to the computer. Docker bridge addresses
are labeled as advanced virtual networks; VPN interfaces are identified separately.
The RF app has additional IPv6 backend support that this USB Watch build does not.

The current connection stays available while the proposed listener is tested.
Only the proposed origin can confirm. Cancellation or timeout retains the previous
settings. When disabling LAN, use a browser on the Linux server to open localhost.
Localhost on a phone or another computer refers to that other device.

## Certificate download and renewal

**Download local HTTPS trust certificate** downloads `usb-storage-watch-ca.crt`.
The file contains the public CA, never its private key. Verify its fingerprint
through the server's localhost page or a trusted connection before importing.
Downloading alone does not establish browser trust. Follow the expandable guide
for the device and browser being used, then return to Apply and confirm HTTPS.

**Renew server certificate** uses the same existing issuer. Its new leaf is
verified after restarting only the app's LAN listener. A durable before-image
restores the old certificate and saved settings after failure or interrupted
commit; the localhost listener and configured ports are unchanged.
An external/older certificate without this retained issuer is not silently
replaced by renewal. The page explains how to migrate through a verified HTTPS
connection on an unused port. Resolve unsaved network edits before renewing.

The guide is adapted from the RF source and checked against primary browser/OS
references on 1 November 2026. Labels can differ by browser or OS version:

- Chromium certificate-manager FAQ:
  https://chromium.googlesource.com/chromium/src/+/main/net/data/ssl/chrome_root_store/faq.md
- Microsoft certificate stores:
  https://learn.microsoft.com/en-us/windows-server/identity/ad-cs/inspect-certificates-manage-certificate-stores
- Mozilla private certificate authorities:
  https://support.mozilla.org/en-US/kb/setting-certificate-authorities-firefox
- Apple Keychain trust:
  https://support.apple.com/guide/keychain-access/kyca11871/mac
- Apple iOS/iPadOS full certificate trust:
  https://support.apple.com/en-us/102390
- Android certificate settings:
  https://support.google.com/pixelphone/answer/2844832

## Touch pickers throughout the app

All dropdown controls use a modal picker, including drive selection, event
filters, image folder access, SMTP security and Docker bind folders. Each option
is a large card (at least 70 pixels high) with a clear selection mark. The list
scrolls independently; a 56-pixel close button remains visible. Escape closes,
arrows/type-ahead navigate, and Tab stays in the picker. Closing restores focus.
Background updates defer rendering while a picker is open. Values remain ordinary
form selections and trigger their existing change handlers.

Native number spinner arrows are hidden throughout the interface. Network ports
have the RF layout with 48-pixel step buttons and a separate full-width Reset row.
Other existing timing/standby plus/minus controls are retained.

## Verification and limits

`TEST-RESULTS.txt` in the release ZIP records exact final results. Checks include
the pre-fix Apply reproduction, real Chromium interactions under the production
Content Security Policy at phone/tablet/desktop widths, all selectors operated
through visible touch controls, six certificate guides, actual OpenSSL certificates,
renewal/rollback, staged origins, deadlines, authentication and CSRF boundaries.

Host APIs, devices and service lifecycle boundaries in browser tests are
synthetic. This development environment has not installed the build on the user's
Ubuntu or Zorin host, changed their LAN, operated their USB drives, or restarted
Erugo. UI12's per-container storage dependency fix is retained. No Docker watchdog,
Codex backup job rerun, or production deployment is added by UI13.
