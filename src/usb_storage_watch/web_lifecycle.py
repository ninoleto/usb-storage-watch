# SPDX-License-Identifier: MIT
"""Stop the web supervisor before its listeners, including before dpkg unpack.

The builder embeds this stdlib-only helper in prerm: failed-upgrade must not
depend on a corrected file that has not yet replaced the old payload.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

STATE = Path('/var/lib/usb-storage-watch')
BROKER = 'usb-storage-watch-broker.service'
WEB = 'usb-storage-watch-web.service'
LAN = 'usb-storage-watch-lan.service'
UNITS = (BROKER, WEB, LAN)
TEST_UNITS = tuple('usb-storage-watch-network-test@' + role + '.service' for role in ('local', 'lan'))
RESTART = STATE / 'web-was-active.json'
WAIT = 40


def command(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], check=True, timeout=45,
                          capture_output=True, text=True)


def service(unit):
    props = 'LoadState,ActiveState,SubState,MainPID,ControlPID,TasksCurrent,ControlGroup,Restart,RestartForceExitStatus,Type'
    return dict(line.split('=', 1) for line in command('show', unit, '--property=' + props).stdout.splitlines() if '=' in line)


def stopped(row):
    if row.get('LoadState') == 'not-found':
        return True
    return (row.get('ActiveState') in ('inactive', 'failed') and
            row.get('MainPID') == '0' and row.get('ControlPID') == '0' and
            (row.get('TasksCurrent') == '0' or
             (row.get('TasksCurrent') in ('[not set]', '18446744073709551615') and
              row.get('ControlGroup') == '')))


def wait_stopped(unit):
    deadline = time.monotonic() + WAIT
    while True:
        if stopped(service(unit)):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(unit + ' still has an active process/job or workers; preparation refused.')
        time.sleep(.1)


def quiesce():
    row = service(BROKER)
    if stopped(row):
        return
    # A stop job alone obeys reverse After= ordering and stops LAN before the
    # broker. Terminate the supervisor first with the same clean SIGTERM used
    # by systemd. Stock Restart=on-failure does not restart after SIGTERM.
    # Refuse incompatible overrides instead of changing service policy.
    if (row.get('Restart') not in ('no', 'on-failure', 'on-abnormal', 'on-abort', 'on-watchdog')
            or row.get('RestartForceExitStatus') or row.get('Type') not in ('simple', 'exec')):
        raise RuntimeError('Broker service overrides prevent safe supervisor shutdown. Review Restart/Type settings.')
    if row.get('MainPID', '0') != '0':
        command('kill', '--kill-who=main', '--signal=SIGTERM', BROKER)
    wait_stopped(BROKER)


def prepare(action):
    if os.environ.get('DPKG_ROOT') or not Path('/run/systemd/system').is_dir():
        return
    if os.geteuid() != 0:
        raise PermissionError('Root required for web lifecycle preparation')
    if action not in ('prepare-upgrade', 'prepare-remove', 'disable'):
        raise ValueError('Unknown web preparation action')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if action == 'prepare-upgrade':
        if RESTART.exists():
            prior = json.loads(RESTART.read_text())
            if not isinstance(prior, list) or any(unit not in UNITS for unit in prior):
                raise ValueError('Invalid saved web restart intent; preparation refused.')
        else:
            active = [unit for unit in UNITS if service(unit).get('ActiveState') in ('active', 'activating', 'reloading')]
            with RESTART.open('x') as stream:
                os.chmod(RESTART, 0o600)
                json.dump(active, stream); stream.flush(); os.fsync(stream.fileno())
    quiesce()
    for unit in (*TEST_UNITS, LAN, WEB, BROKER):
        if service(unit).get('LoadState') != 'not-found':
            command('stop', unit)
        wait_stopped(unit)
    # Recheck the entire set, including workers, before declaring success.
    for unit in (*UNITS, *TEST_UNITS):
        if not stopped(service(unit)):
            raise RuntimeError(unit + ' became active during preparation; upgrade refused.')
    print('Web preparation verified: supervisor, listeners and workers stopped.')


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except Exception as exc:
        # systemctl exceptions include only these fixed commands, never config.
        print('Web service preparation stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
