#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Install the deb into a clean private dpkg root, then run Chromium regressions.

OS boundaries remain synthetic in tests/gui_fixture.py. No host services, disks,
PAM accounts or configuration are modified. This does not establish a booted
Ubuntu Studio installation or real hardware/desktop compatibility.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deb', type=Path)
    parser.add_argument('--fixture', type=Path, help='Private runtime JSON with the exact upgrade uuid and mountpoint')
    args = parser.parse_args()
    version = next(line.removeprefix('Version: ') for line in (ROOT / 'packaging/control').read_text().splitlines() if line.startswith('Version: '))
    deb = (args.deb or ROOT / 'dist' / f'usb-storage-watch_{version}_all.deb').resolve()
    with tempfile.TemporaryDirectory(prefix='usw-browser-install-') as temporary:
        base = Path(temporary)
        root = base / 'root'
        admin = root / 'var/lib/dpkg'
        admin.mkdir(parents=True)
        (admin / 'status').touch()
        env = dict(os.environ, DPKG_ROOT=str(root), FAKEROOTDONTTRYCHOWN='1')
        subprocess.run(['fakeroot', 'dpkg', '--root=' + str(root), '--admindir=' + str(admin),
                        '--log=' + str(base / 'dpkg.log'), '--force-not-root', '--force-script-chrootless',
                        '--force-depends', '--install', str(deb)], env=env, check=True, timeout=45,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert not (root / 'etc/usb-storage-watch/config.json').exists()
        assert not (root / 'etc/usb-storage-watch/smtp.json').exists()
        assert not (root / 'etc/systemd/system/multi-user.target.wants').exists()
        env['USW_GUI_PAYLOAD'] = str(root / 'usr/lib/usb-storage-watch')
        if args.fixture:
            env['USW_GUI_FIXTURE'] = str(args.fixture.resolve())
        # Fail explicitly when browser dependencies are absent; never report skipped tests as validation.
        if not importlib.util.find_spec('playwright') or not importlib.util.find_spec('flask'):
            raise SystemExit('Install the development Playwright and Flask dependencies before running this test.')
        subprocess.run([sys.executable, '-B', '-I', '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'),
                        '-p', 'test_gui*.py', '-v'], env=env, check=True, timeout=360)
        print('PASS: clean private Debian install and installed-payload browser workflows. OS operations are isolated fixtures.')
        if args.fixture:
            print('PASS: private runtime identity/path supplied to both browser suites; fixture SHA256 ' +
                  hashlib.sha256(args.fixture.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
