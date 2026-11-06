# License and dependency notices

Project source and documentation are provided under the MIT license in LICENSE.
The recovery implementation is derived from the project owner's existing v3.2
monitor; redistribution contains generalized source, not their private runtime
configuration. The GUI bundles the unmodified Python sources and MIT license from Gunicorn
26.2.0. No compiled binaries, container images, third-party fonts or proprietary
assets are bundled. See the provenance and per-file SHA256 manifest in
`tools/vendor-lock.json`; builds reject any change to those upstream files.

The following are **external system dependencies**, installed and licensed by
the target distribution. Their names do not imply endorsement:

| Dependency | Use | Upstream license information |
| --- | --- | --- |
| Flask / Werkzeug / Jinja2 (optional GUI) | Web request handling; distribution security updates | Installed distribution copyright/license files |
| PyPAM / Linux PAM (optional GUI) | Existing administrator authentication | Installed distribution copyright/license files |
| OpenSSL (optional GUI) | Validate uploaded TLS certificate identity and dates | Installed distribution copyright/license files |
| Python 3 standard library | Runtime, SMTP/TLS, tests and builder | [PSF license](https://docs.python.org/3/license.html) |
| Linux kernel/sysfs/procfs | Device and process metadata; optional qualified port control | [Kernel licensing](https://docs.kernel.org/process/license-rules.html) |
| systemd / udev | Service supervision and device metadata | [systemd license information](https://github.com/systemd/systemd/blob/main/LICENSES/README.md) |
| util-linux | Normal mount, blkid and loop metadata | [util-linux COPYING](https://github.com/util-linux/util-linux/blob/master/COPYING) |
| CA certificates / system TLS | Verified SMTP TLS | Distribution-specific certificate/trust-store notices |
| Docker Engine (optional) | Selected container API inspection/recovery | [Moby Apache-2.0 license](https://github.com/moby/moby/blob/master/LICENSE) |
| dpkg / fakeroot (build/test only) | Debian package and isolated lifecycle validation | Installed distribution copyright/license files |
| GNU make / coreutils (build/maintenance) | Build entry points and bounded service hooks | Installed distribution copyright/license files |

System components can contain multiple licenses; consult the exact installed
version's notices. The Debian archive includes this project's code and Gunicorn's unmodified MIT
sources, with its license at `/usr/lib/usb-storage-watch/_vendor/gunicorn-LICENSE`.
Other dependencies are supplied by the operating system. Gunicorn upstream:
https://pypi.org/project/gunicorn/26.2.0/ . Its pinned wheel SHA256 is recorded in
the manifest. The bundle uses the standard-library HTTP/1.1 gthread worker;
HTTP/2, ASGI, optional compiled parsers and third-party worker plugins are off.

## RF433 Button Manager interface reference

The UI13 network-card layout, touch-picker styling and certificate import
walkthrough are adapted from RF433 Button Manager 0.4.0-test.5 by the same project
owner. Copyright (c) 2026 Nino Milin. Licensed under the MIT license below.
The RF application, receiver code and private configuration are not bundled.

MIT License

Copyright (c) 2026 Nino Milin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
