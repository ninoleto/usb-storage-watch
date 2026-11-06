# SPDX-License-Identifier: MIT
"""Open only this machine's dashboard; no administrative privileges required."""
import os
from pathlib import Path
import stat
import subprocess

PORT_HINT = Path('/run/usb-storage-watch-dashboard.port')


def dashboard_url(path=PORT_HINT):
    port = 8765
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 6:
                raise ValueError('Invalid public port hint')
            value = os.read(fd, 7).decode('ascii').strip()
            if not value.isdecimal() or not 1024 <= int(value) <= 65535:
                raise ValueError('Invalid port')
            port = int(value)
        finally:
            os.close(fd)
    except (OSError, ValueError, UnicodeError):
        pass
    return 'http://127.0.0.1:'+str(port)+'/'


if __name__ == '__main__':
    subprocess.run(['/usr/bin/xdg-open', dashboard_url()], check=False)
