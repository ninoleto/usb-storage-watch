# SPDX-License-Identifier: MIT
"""Admission checks for user operations, not automatic recovery workers.

Incident state covers the gaps between workers. The existing per-container flock
serializes acceptance with worker operations; refusal never waits or queues work.
"""
from contextlib import contextmanager, ExitStack
import json
import re

MESSAGE = 'Recovery in progress. Controls are temporarily unavailable.'
UNAVAILABLE = 'Recovery status is unavailable. Refresh or check the drive before changing this app.'
ACTIVE = {'wait1', 'wait2', 'return_failed', 'running', 'verify', 'applications'}


def identities(values):
    return {v for v in values if isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)}


def timeout_storage_ready(b, items, identity):
    """A terminal timeout cannot authorize Start into absent storage/images.

    Reuse physical identity/mount verification, including under the existing
    app operation lock. No mounts or app operations; only explicit selections.
    """
    try:
        found = False
        for drive, config in items:
            for app in config['docker']['containers'] if config['docker']['enabled'] else []:
                if app.get('container_id') != identity: continue
                found = True
                w = b.common.module('boot_start').engine(b, drive, config)
                w.verify_main()
                registered = {v['uuid']: v for v in w.settings.storage_images(w.SETTINGS, False)}
                for image in app.get('images', []): w.verify_dependent(registered[image])
        return found
    except Exception:
        return False  # Missing/uncertain evidence never authorizes a start.


def restrictions(b, items, *, unmount_owner=None):
    """Union current incidents only; never treat archived history as active work."""
    _, root = b.cli.drives.roots(b.s)
    result = {}
    manual = b.common.module('manual_intent')
    for drive, config in items:
        selected = identities(v.get('container_id') for v in config['docker']['containers']) if config['docker']['enabled'] else set()
        directory = root if drive == 'legacy' else root / 'drives' / drive
        try:
            intent = manual.read(root, drive, b.w.boot_id())
            owner_fd = unmount_owner[1] if unmount_owner and unmount_owner[0] == drive else None
            if manual.active(root, drive, intent, owner_fd=owner_fd):
                result.update({identity: manual.MESSAGE for identity in intent['control_ids']})
        except (OSError, ValueError, TypeError):
            for identity in selected: result.setdefault(identity, UNAVAILABLE)
        try:
            path = directory / 'state.json'
            with path.open() as stream:
                text = stream.read(4 * 1024 * 1024 + 1)
            if len(text) > 4 * 1024 * 1024: raise ValueError('State too large')
            state = json.loads(text)
            incident = state.get('incident')
            if incident is None: continue
            if not isinstance(incident, dict): raise ValueError('Invalid incident')
            timeout_hold = bool(incident.get('return_deadline', {}).get('reported_at'))
            if incident.get('phase') in ('done', 'legacy') and not timeout_hold: continue
            if incident.get('phase') not in ACTIVE | {'done', 'legacy'}: raise ValueError('Invalid phase')
            # New incidents pin their original IDs before the stop stage. Older
            # receipts use explicit current selections and observed exact IDs.
            if 'control_ids' in incident:
                values = incident['control_ids']
                if not isinstance(values, list) or len(identities(values)) != len(values):
                    raise ValueError('Invalid incident identities')
                selected = set(values)
            for capture in ((incident.get('stop') or {}).get('result'),
                            (incident.get('applications') or {}).get('baseline'),
                            (incident.get('applications') or {}).get('detected')):
                if isinstance(capture, dict):
                    for entry in capture.get('containers', {}).values():
                        selected.update(identities((entry.get('id'), entry.get('container_id'))))
            detail = ''
            if incident.get('latest', {}).get('detected') is False:
                detail = b.common.module('return_deadline').message(incident, b.w.clock_now(), b.w.boot_id())
            for identity in selected:
                if incident.get('phase') in ('done', 'legacy') and timeout_hold:
                    if timeout_storage_ready(b, items, identity): continue
                    result[identity] = 'Required storage is unavailable after the drive return timeout. Controls are temporarily unavailable.'
                    continue
                result[identity] = (detail + ' Controls are temporarily unavailable.' if timeout_hold and detail else
                                    MESSAGE + (' ' + detail if detail else ''))
        except FileNotFoundError:
            continue  # No monitor incident has been recorded for this drive.
        except (OSError, ValueError, TypeError, AttributeError):
            for identity in selected: result.setdefault(identity, UNAVAILABLE)
    return result


def require_idle(b, items, identity, *, unmount_owner=None):
    reason = restrictions(b, items, unmount_owner=unmount_owner).get(identity)
    if reason: raise ValueError(reason)


@contextmanager
def operation(fleet, identity):
    b = fleet.context()
    directory = b.cli.drives.roots(b.s)[1] / 'shared-locks'
    try:
        with b.cli.drives.lock(directory, 'docker-restart-' + identity + '.lock'):
            items = []
            for drive, config, error in fleet.records():
                if error: raise ValueError(error)
                items.append((drive, config))
            require_idle(b, items, identity)
            yield
    except BlockingIOError:
        raise ValueError('Another operation is controlling this app. Nothing was queued; try again after it finishes.') from None


def requested_identities(data):
    values = data.get('containers', []) if isinstance(data, dict) else []
    return identities(v.get('id') for v in values if isinstance(v, dict)) if isinstance(values, list) else set()


@contextmanager
def drive_settings(b, config, requested=()):
    """Guard legacy per-drive editors as well as the container-first interface."""
    items = [(b.s.PROFILE_ID, config)]
    affected = identities(v.get('container_id') for v in config['docker']['containers']) | set(restrictions(b, items)) | identities(requested)
    with ExitStack() as held:
        for identity in sorted(affected):
            held.enter_context(b.cli.drives.lock(b.cli.drives.roots(b.s)[1] / 'shared-locks', 'docker-restart-' + identity + '.lock'))
        def recheck():
            all_items = [(drive, b.cli.drives.read(b.s, path)) for drive, path in b.cli.drives.files(b.s)]
            for identity in affected: require_idle(b, all_items, identity)
        recheck()
        yield recheck
