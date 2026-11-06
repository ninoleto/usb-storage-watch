# SPDX-License-Identifier: MIT
"""Same-boot deliberate unmount receipts; never modify saved app selections."""
import fcntl
import http.client
import json
import os
import re

MESSAGE = 'Safe unmount in progress. Controls are temporarily unavailable.'


def directory(root, profile):
    return root if profile == 'legacy' else root / 'drives' / profile


def read(root, profile, boot):
    try:
        path = directory(root, profile) / 'manual-unmount.json'
        with path.open() as stream: value = json.loads(stream.read(65537))
    except FileNotFoundError: return None
    if (not isinstance(value, dict) or value.get('phase') not in ('active', 'complete', 'failed')
            or any(not isinstance(value.get(key), list) or len(value[key]) > 512 or
                   any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in value[key])
                   for key in ('control_ids', 'held_ids'))):
        raise ValueError('Manual unmount receipt needs review; automatic startup is withheld.')
    return value if value.get('boot') == boot else None


def active(root, profile, value, *, owner_fd=None):
    if not value: return False
    # A broker interruption must not leave controls disabled forever. The
    # durable stop intent still suppresses automatic starts for this boot.
    try:
        with (directory(root, profile) / 'manual-unmount.lock').open('rb') as stream:
            # Admission inside an already-held unmount lock must not mistake its
            # own lock plus an older durable receipt for competing work. This FD
            # comes only from the broker's live lock context, never request data.
            if owner_fd is not None:
                owned, observed = os.fstat(owner_fd), os.fstat(stream.fileno())
                if (owned.st_dev, owned.st_ino) == (observed.st_dev, observed.st_ino):
                    return False
            try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return True
    except FileNotFoundError: pass
    return False


def stopped(w, identity):
    root = w.drives.roots(w.settings)[1]
    for profile, _ in w.drives.files(w.settings):
        value = read(root, profile, w.boot_id())
        if value and identity in value['held_ids']: return True
    return False


def release(b, identity):
    """Only an explicitly requested, verified manual Start/Restart clears a hold."""
    root = b.cli.drives.roots(b.s)[1]
    for profile, _ in b.cli.drives.files(b.s):
        folder = directory(root, profile)
        with b.cli.drives.lock(folder, 'manual-intent.lock'):
            value = read(root, profile, b.w.boot_id())
            if value and identity in value['held_ids']:
                value['held_ids'].remove(identity)
                b.cli.save(folder / 'manual-unmount.json', value)


def ready_apps(b, config, probe):
    """Read-only explanation, never authorization to mount/start or clear intent."""
    if probe.get('healthy') is not True or probe.get('dependent') is not True:
        return []
    try:
        root = b.cli.drives.roots(b.s)[1]
        value = read(root, b.s.PROFILE_ID, b.w.boot_id())
        if (not value or value.get('uuid') != config['disk']['uuid'] or not value['held_ids']
                or active(root, b.s.PROFILE_ID, value)):
            return []
        held = set(value['held_ids'])
        items = [(drive, b.cli.drives.read(b.s, path)) for drive, path in b.cli.drives.files(b.s)]
        if held & b.common.module('app_control').restrictions(b, items).keys(): return []
        names, choices = {}, {}
        # Retained selections are conservative display evidence, not permission
        # to enable recovery. Verify all selected storage for these held IDs.
        for drive, c in items:
            for app in c['docker']['containers']:
                if app.get('container_id') in held:
                    names[app['container_id']] = app['name']
                    choices.setdefault(drive, set()).update(app.get('images', []))
        boot = b.common.module('boot_start')
        for app in boot.read(b)['containers']:
            if app['id'] in held:
                names.setdefault(app['id'], app['name'])
                for choice in app['drives']: choices.setdefault(choice['id'], set()).update(choice['images'])
        if held != names.keys() or not choices: return []
        docker = b.common.module('web_docker').client(b, items)[0]
        for identity, name in names.items():
            current = docker.inspect(identity)
            if (current['id'] != identity or current['name'] != name or
                    any(current.get(k) is not False for k in ('running', 'paused', 'restarting', 'dead'))):
                return []
        configs = dict(items)
        for drive, images in choices.items():
            w = boot.engine(b, drive, configs[drive])
            w.verify_main()
            registered = {v['uuid']: v for v in w.settings.storage_images(w.SETTINGS, False)}
            if not images <= registered.keys(): return []
            for image in sorted(images): w.verify_dependent(registered[image])
        if read(root, b.s.PROFILE_ID, b.w.boot_id()) != value: return []
        return [dict(id=identity, name=names[identity]) for identity in sorted(held)]
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, b.w.Unsafe, b.w.apps.AppError):
        return []  # Unavailable evidence must never become a "Drive ready" claim.
