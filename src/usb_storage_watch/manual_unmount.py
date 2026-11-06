# SPDX-License-Identifier: MIT
"""Authenticated unmount review; exact-ID stops precede existing storage guards."""
from contextlib import ExitStack
import secrets
import time


def snapshot(b):
    c = b.configuration()
    boot = b.common.module('boot_start').read(b)
    selected = c['docker']['containers'] if c['docker']['enabled'] else []
    registered = {v['uuid']: v['name'] for v in b.s.storage_images(c, False)}
    apps = []
    docker = b.common.module('web_docker').client(b, [(b.s.PROFILE_ID, c)])[0] if selected else None
    for spec in selected:
        identity = spec.get('container_id')
        if identity not in b.common.module('app_control').identities([identity]):
            raise ValueError('A dependent app has no pinned container ID. Select its explicit identity before unmounting.')
        if not set(spec.get('images', [])) <= registered.keys():
            raise ValueError('A dependent app has an unavailable selected image. Review its selections before unmounting.')
        try: current = docker.inspect(identity)
        except Exception:
            raise ValueError('Cannot verify dependent app ' + spec['name'] + ' (' + identity[:12] + ') with Docker. Nothing was stopped or unmounted.') from None
        if current['id'] != identity or current['name'] != spec['name']:
            raise ValueError('Dependent app identity changed. Refresh and explicitly select the container; nothing was stopped.')
        if any(current.get(k) is not False for k in ('paused', 'restarting', 'dead')):
            raise ValueError('Dependent app ' + spec['name'] + ' is paused, restarting or dead. Resolve its Docker state before unmounting.')
        apps.append(dict(id=identity, name=spec['name'], running=current['running'],
                         started_at=current['started_at'], grace=spec['grace'],
                         images=[registered[v] for v in spec.get('images', [])]))
    b.w.configure(c)
    rows = b.w.read_rows()
    dev = b.w.device_number('/dev/disk/by-uuid/' + c['disk']['uuid'])
    mount = b.w.mounted_checks(rows, c['disk']['mountpoint'], dev, c['disk']['uuid'])
    return dict(uuid=c['disk']['uuid'], revision=b.s.digest(c), boot_revision=b.s.digest(boot),
                mount={k:mount[k] for k in ('id', 'dev', 'root', 'target', 'source', 'fs')},
                apps=sorted(apps, key=lambda v:v['id']),
                boot_ids=sorted(v['id'] for v in boot['containers'] if v['enabled'] and
                                any(d['id'] == b.s.PROFILE_ID for d in v['drives']))), docker


def review(b, data, session):
    key = 'unmount:' + b.s.PROFILE_ID
    session.pop(key, None)
    if set(data) != {'uuid'}: raise ValueError('Select the configured drive to review safe unmount.')
    value, _ = snapshot(b)
    if value['uuid'] != data['uuid']: raise ValueError('Selected drive changed; refresh first.')
    guard = b.common.module('app_control')
    items = [(i, b.cli.drives.read(b.s, p)) for i, p in b.cli.drives.files(b.s)]
    for identity in {v['id'] for v in value['apps']} | set(value['boot_ids']): guard.require_idle(b, items, identity)
    token = secrets.token_hex(24)
    session[key] = dict(token=token, expires=time.monotonic()+300, value=value)
    return dict(token=token, apps=value['apps'], message='Running dependent apps will be stopped and verified before images and the drive are unmounted. Monitoring will stop. Apps stay stopped; mounting the drive again will not start them. Pending startup for this drive is cancelled for this computer session.')


def apply(b, data, session, unmount):
    chosen = session.pop('unmount:' + b.s.PROFILE_ID, None)
    if (set(data) != {'uuid', 'action', 'token', 'confirm'} or data['action'] != 'unmount'
            or data['confirm'] is not True or not chosen or chosen['expires'] < time.monotonic()
            or data['token'] != chosen['token'] or data['uuid'] != chosen['value']['uuid']):
        raise ValueError('Review Unmount safely again and explicitly confirm. Nothing was stopped or unmounted.')
    expected = chosen['value']; ids = sorted({v['id'] for v in expected['apps']} | set(expected['boot_ids']))
    root = b.cli.drives.roots(b.s)[1]; intent = b.common.module('manual_intent')
    guard = b.common.module('app_control'); path = b.s.STATE_DIR / 'manual-unmount.json'
    try:
        with ExitStack() as held:
            fds = [held.enter_context(b.cli.drives.lock(b.s.STATE_DIR, 'manual-unmount.lock'))]
            owner = (b.s.PROFILE_ID, fds[0])
            for identity in ids:
                fds.append(held.enter_context(b.cli.drives.lock(root / 'shared-locks', 'docker-restart-' + identity + '.lock')))
            items = [(i, b.cli.drives.read(b.s, p)) for i, p in b.cli.drives.files(b.s)]
            for identity in ids: guard.require_idle(b, items, identity, unmount_owner=owner)
            current, docker = snapshot(b)
            if current != expected:
                raise ValueError('Drive, app execution or selections changed since review. Review Unmount safely again; nothing was stopped or unmounted.')
            # Mark intent before any stop. Crashes never authorize startup or a
            # replay; a new authenticated review is needed for another operation.
            receipt = dict(boot=b.w.boot_id(), phase='active', control_ids=ids,
                           held_ids=[v['id'] for v in expected['apps']], uuid=expected['uuid'])
            def unchanged():
                if (b.s.digest(b.configuration()) != expected['revision'] or
                        b.s.digest(b.common.module('boot_start').read(b)) != expected['boot_revision']):
                    raise ValueError('Storage or startup selections changed; unmount aborted. Review again.')
            with b.cli.drives.configuration_lock(b.s), b.cli.drives.lock(b.s.STATE_DIR, 'manual-intent.lock'):
                unchanged()
                for identity in ids: guard.require_idle(b, items, identity, unmount_owner=owner)
                previous = intent.read(root, b.s.PROFILE_ID, b.w.boot_id())
                if previous: receipt['held_ids'] = sorted(set(receipt['held_ids']) | set(previous['held_ids']))
                b.cli.save(path, receipt)
            stopped = []
            def observe(app):
                try: return docker.inspect(app['id'])
                except Exception:
                    raise ValueError('Cannot verify ' + app['name'] + ' (' + app['id'][:12] + ') with Docker. Unmount aborted.') from None
            try:
                for identity in ids: b.common.module('boot_start').cancel(b, identity)
                for app in expected['apps']:
                    unchanged()
                    error = ''
                    # No name lookup or inferred bind mapping grants authority.
                    observed = observe(app)
                    if observed['id'] != app['id'] or observed['name'] != app['name'] or observed['started_at'] != app['started_at']:
                        raise ValueError('App ' + app['name'] + ' changed after confirmation. Unmount aborted.')
                    unchanged()
                    if observed['running']:
                        try:
                            docker.request('POST', '/containers/' + app['id'] + '/stop?t=' + str(app['grace']),
                                           timeout=app['grace']+10, allowed_status=(304,))
                        except Exception as exc:
                            error = str(exc) if getattr(exc, 'status', None) is not None else 'Docker stop response was unavailable or timed out.'
                    observed = observe(app)
                    if (observed['id'] != app['id'] or observed['name'] != app['name'] or
                            any(observed.get(k) is not False for k in ('running', 'paused', 'restarting'))):
                        raise ValueError('Cannot confirm ' + app['name'] + ' (' + app['id'][:12] + ') stopped. ' + (error or 'Docker still reports an active app.') + ' Unmount aborted.')
                    stopped.append(app['name'])
                # Recheck all apps together immediately before the storage worker.
                for app in expected['apps']:
                    observed = observe(app)
                    if (observed['id'] != app['id'] or observed['name'] != app['name'] or
                            any(observed.get(k) is not False for k in ('running', 'paused', 'restarting'))):
                        raise ValueError('App ' + app['name'] + ' is no longer confirmed stopped. Unmount aborted.')
                unchanged()
                result = unmount(tuple(fds))
                receipt['phase'] = 'complete' if result.get('ok') else 'failed'
                if stopped: result['message'] += ' Apps left stopped: ' + ', '.join(stopped) + '.'
                result['message'] += ' Automatic startup is withheld for this computer session; Mount does not start apps. Use Start app explicitly when storage is ready.'
                if result.get('last_operation'): result['last_operation']['message'] = result['message']
                return result
            except Exception as exc:
                receipt['phase'] = 'failed'
                detail = str(exc) if isinstance(exc, (ValueError, b.w.Unsafe)) else 'Dependent app state could not be verified; unmount aborted.'
                raise ValueError(detail + (' Apps already confirmed stopped: ' + ', '.join(stopped) + '.' if stopped else '') +
                                 ' No app restart was requested. Automatic startup remains withheld; check app status before retrying.') from None
            finally:
                if receipt['phase'] == 'active': receipt['phase'] = 'failed'
                with b.cli.drives.lock(b.s.STATE_DIR, 'manual-intent.lock'):
                    current = intent.read(root, b.s.PROFILE_ID, b.w.boot_id())
                    current['phase'] = receipt['phase']
                    b.cli.save(path, current)
    except BlockingIOError:
        raise ValueError('Another operation controls this drive or a dependent app. Nothing was queued; review again after it finishes.') from None
