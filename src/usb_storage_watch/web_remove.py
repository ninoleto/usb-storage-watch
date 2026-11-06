# SPDX-License-Identifier: MIT
"""Retire one configured drive without touching its storage or shared settings."""
from contextlib import ExitStack, contextmanager
import json
import os
import stat
import subprocess


@contextmanager
def request_lock(instance):
    if not instance.request_lock.acquire(timeout=.5):
        raise ValueError('An operation is already running for this drive. Wait for it to finish before removing it.')
    try:yield
    finally:instance.request_lock.release()


def configuration(fleet, identifier):
    child, instance = fleet.get(identifier)
    return child, instance, read_active(child, identifier)


def read_active(child, identifier):
    if identifier not in dict(child.cli.drives.files(child.s)):
        raise ValueError('This drive has already been removed. Refresh the overview.')
    child.cli.root_path('/', child.s.CONFIG)
    return child.cli.drives.read(child.s, child.s.CONFIG)


def review(fleet, identifier):
    child, instance, _ = configuration(fleet, identifier)
    with request_lock(instance):
        config = read_active(child, identifier)
        return dict(profile_id=identifier, uuid=config['disk']['uuid'], name=config['disk']['label'],
                    mountpoint=config['disk']['mountpoint'], revision=child.s.digest(config),
                    images=len(child.s.storage_images(config, False)),
                    containers=len(config['docker']['containers']), services=len(config['services']['units']))


def usb_cleanup_complete(child):
    path = child.s.STATE_DIR / 'usb-reset.json'
    try:fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:return
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('The USB cleanup record needs administrator review. This drive remains configured.')
        try:value = json.loads(stream.read(1024 * 1024))
        except (ValueError, UnicodeError):value = None
        if not isinstance(value, dict) or value.get('phase') != 'enabled':
            raise ValueError('USB enable cleanup is still unresolved. The drive remains configured with monitoring stopped. Resolve cleanup before removing it.')


def apply(fleet, identifier, data):
    child, instance, _ = configuration(fleet, identifier)
    with request_lock(instance), child.cli.drives.configuration_lock(child.s):
        config = read_active(child, identifier)
        if data['uuid'] != config['disk']['uuid'] or data['revision'] != child.s.digest(config):
            raise ValueError('This drive or its settings changed. Review removal again.')
        if instance.prepare_worker is not None:
            raise ValueError('Drive preparation is still running. Wait for it to finish before removing this drive.')
        if child.migration.pending(child.migration_context()):
            raise ValueError('Finish or roll back this drive’s mount location change before removing it.')
        archived = child.s.CONFIG.with_name('removed-drive.json')
        if archived.exists() or archived.is_symlink():
            raise ValueError('An earlier removal archive already exists. Administrator review is required; this drive remains configured.')
        try:
            child.command(['/usr/bin/systemctl', 'disable', '--now', child.s.SERVICE], 35)
            observed = dict(line.split('=', 1) for line in child.command(
                ['/usr/bin/systemctl', 'show', child.s.SERVICE,
                 '--property=ActiveState,MainPID,UnitFileState']).splitlines() if '=' in line)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError('Monitoring could not be stopped and verified. The drive remains configured. Refresh its status before trying again.') from None
        if (observed.get('ActiveState') not in ('inactive', 'failed') or observed.get('MainPID') != '0'
                or observed.get('UnitFileState') not in ('disabled', 'masked', 'masked-runtime')):
            raise ValueError('Monitoring is not fully stopped and disabled. The drive remains configured.')
        # Stopping systemd alone is insufficient: a child or cleanup worker may
        # still hold a lock. Keep every inode and cleanup ledger in place.
        with ExitStack() as locks:
            try:
                for name in ('monitor.lock', 'recovery.lock', 'preparation.lock', 'usb-io.lock', 'usb-ledger.lock'):
                    locks.enter_context(child.cli.drives.lock(child.s.STATE_DIR, name))
            except BlockingIOError:
                raise ValueError('A drive worker is still finishing. Monitoring is stopped; the drive remains configured. Wait before removing it.') from None
            usb_cleanup_complete(child)
            if child.s.digest(child.cli.drives.read(child.s, child.s.CONFIG)) != data['revision']:
                raise ValueError('Drive settings changed while monitoring stopped. Review removal again.')
            # One atomic rename commits retirement. History, token records,
            # receipts and image files are retained, but the old profile can
            # no longer serve drive actions and will never be reused by Add.
            directory = os.open(child.s.CONFIG.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.replace(child.s.CONFIG, archived)
                os.fsync(directory)
            finally:os.close(directory)
    # Do not take the fleet mutex while owning a profile/configuration lock:
    # Add acquires them in the other order. A stale child also rejects requests.
    with fleet.mutex:
        fleet.cache.pop(identifier, None)
        fleet.children.pop(identifier, None)
    return dict(profile_id=identifier, removed=True,
                message=config['disk']['label']+' removed from Storage Watch. Monitoring and automatic recovery are stopped. Files and current mounts are unchanged. You can add this drive again later.')
