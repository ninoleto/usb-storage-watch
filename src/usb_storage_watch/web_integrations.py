# SPDX-License-Identifier: MIT
"""Fixed public setup assets, served only through the dashboard session boundary."""
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat

PACKAGE_DIR = Path(__file__).with_name('companion')


def read_file(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError('Public setup asset unavailable.')
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError('Public setup asset unavailable.')
        return value


def certificate(path):
    pem = read_file(path, 24000).decode('ascii')
    # Serve a complete public certificate only, never appended private material.
    if not re.fullmatch(r'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*', pem):
        raise ValueError('Public trust certificate unavailable.')
    ssl.PEM_cert_to_DER_cert(pem)
    return pem


def module_package():
    info = json.loads(read_file(PACKAGE_DIR / 'module.json', 1000))
    if not isinstance(info, dict) or not re.fullmatch(r'\d+\.\d+\.\d+', str(info.get('version', ''))):
        raise ValueError('Module package unavailable.')
    content = read_file(PACKAGE_DIR / 'module.tgz', 5 * 1024 * 1024)
    digest = hashlib.sha256(content).hexdigest()
    if digest != info.get('sha256'):
        raise ValueError('Module package checksum mismatch.')
    return dict(available=True, version=info['version'], sha256=digest), content
