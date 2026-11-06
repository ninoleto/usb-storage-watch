# SPDX-License-Identifier: MIT
"""GUI-only lifecycle; never changes the monitor's configuration or enablement."""
import importlib.util
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
sys.dont_write_bytecode = True

spec=importlib.util.spec_from_file_location('web_auth',Path(__file__).with_name('web_auth.py'))
auth=importlib.util.module_from_spec(spec);spec.loader.exec_module(auth)
spec=importlib.util.spec_from_file_location('web_lifecycle',Path(__file__).with_name('web_lifecycle.py'))
lifecycle=importlib.util.module_from_spec(spec);spec.loader.exec_module(lifecycle)
MANAGEMENT = Path('/etc/usb-storage-watch/management-token.json')

STATE = Path('/var/lib/usb-storage-watch')
CONFIG = Path('/etc/usb-storage-watch-web')
UNITS = ('usb-storage-watch-broker.service', 'usb-storage-watch-web.service')
LAN = 'usb-storage-watch-lan.service'
TEST_UNITS = tuple('usb-storage-watch-network-test@'+role+'.service' for role in ('local','lan'))
MARKER = STATE / 'web-installed'
RESTART = STATE / 'web-was-active.json'


def run(args):
    return subprocess.run(args, check=True, timeout=45, stdout=subprocess.DEVNULL)


def available():
    return (all(importlib.util.find_spec(name) for name in ('flask', 'PAM'))
            and Path(__file__).with_name('_vendor').joinpath('gunicorn/__init__.py').is_file())


def systemd_available():
    return Path('/run/systemd/system').exists()


def setup():
    try:
        account = pwd.getpwnam('usb-storage-watch-web')
    except KeyError:
        run(['/usr/sbin/useradd', '--system', '--user-group', '--home-dir', '/nonexistent',
             '--no-create-home', '--shell', '/usr/sbin/nologin', 'usb-storage-watch-web'])
        account = pwd.getpwnam('usb-storage-watch-web')
    if account.pw_uid == 0 or account.pw_shell not in ('/usr/sbin/nologin', '/sbin/nologin', '/bin/false'):
        raise ValueError('Web service account must be an unprivileged non-login account')
    if CONFIG.is_symlink():
        raise ValueError('Refusing a symlink for web configuration')
    CONFIG.mkdir(mode=0o750, exist_ok=True)
    os.chown(CONFIG, 0, account.pw_gid); CONFIG.chmod(0o750)
    path = CONFIG / 'config.json'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(lan=False, address='127.0.0.1', hostname='localhost', port=8765), stream)
        os.chown(path, 0, account.pw_gid)


def main(action, headless=False):
    if os.environ.get('DPKG_ROOT'):
        return
    if os.geteuid() != 0:
        raise PermissionError('Use sudo for web service administration')
    if action in ('finish-upgrade','enable'):
        try:
            outcome=auth.ensure_management_token(MANAGEMENT,STATE)
            if outcome=='recovery-required':print('Management token needs local administrator recovery. Local dashboard recovery remains available.')
        except auth.Denied as exc:
            print('Management token setup needs local administrator review: '+str(exc))
    if not systemd_available():
        return
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if action in ('prepare-upgrade', 'prepare-remove', 'disable'):
        enabled = subprocess.run(['/usr/bin/systemctl','is-enabled','--quiet',UNITS[-1]], timeout=10).returncode == 0
        lifecycle.prepare(action)
        if action in ('prepare-remove', 'disable'):
            for unit in reversed((*UNITS,LAN)):
                run(['/usr/bin/systemctl', 'disable', unit])
            Path('/run/usb-storage-watch-dashboard.port').unlink(missing_ok=True)
            RESTART.unlink(missing_ok=True)
            MARKER.write_text('removed\n' if action == 'prepare-remove' and enabled else 'disabled\n'); MARKER.chmod(0o600)
        return
    if action not in ('finish-upgrade', 'enable'):
        raise ValueError('Unknown GUI lifecycle action')
    if action != 'enable' and (headless or os.environ.get('USB_STORAGE_WATCH_HEADLESS') == '1'):
        lifecycle.prepare('disable')
        for unit in reversed((*UNITS,LAN)):
            run(['/usr/bin/systemctl', 'disable', unit])
        MARKER.write_text('disabled\n'); MARKER.chmod(0o600)
        RESTART.unlink(missing_ok=True)
        return
    if not available():
        if action == 'enable':
            raise ValueError('Install python3-flask, python3-pam and openssl to enable the GUI')
        print('GUI dependencies absent: headless installation retained.')
        return
    setup()
    run(['/usr/bin/systemctl', 'daemon-reload'])
    activate = action == 'enable' or not MARKER.exists() or MARKER.read_text().strip() == 'removed'
    prior = json.loads(RESTART.read_text()) if RESTART.exists() else []
    if activate:
        for unit in UNITS:
            run(['/usr/bin/systemctl', 'enable', '--now', unit])
        MARKER.write_text('installed\n'); MARKER.chmod(0o600)
    elif RESTART.exists():
        for unit in UNITS:
            if unit in prior:
                run(['/usr/bin/systemctl', 'start', unit])
    # Upgrade an existing DEV3 LAN setup without ever applying TLS to localhost.
    # A failed optional listener must not fail local GUI installation.
    try:
        lan=json.loads((CONFIG/'config.json').read_text()).get('lan') is True
        enabled=subprocess.run(['/usr/bin/systemctl','is-enabled','--quiet',UNITS[-1]],timeout=10).returncode==0
        if lan and enabled:
            if activate: run(['/usr/bin/systemctl','enable','--now',LAN])
            elif LAN in prior: run(['/usr/bin/systemctl','start',LAN])
    except (OSError,ValueError,subprocess.SubprocessError):
        print('Local dashboard is available. Review optional LAN access in Advanced settings.')
    RESTART.unlink(missing_ok=True)
    try: local_port=json.loads((CONFIG/'config.json').read_text()).get('http_port',8765)
    except (OSError,ValueError): local_port=8765
    print(f'Web dashboard: http://localhost:{local_port} (optional LAN address appears in Advanced settings).')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as exc:
        print('Web service setup stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
