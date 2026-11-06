# SPDX-License-Identifier: MIT
"""Plain-language setup over the existing guarded monitor and mount policy.

Planning is read-only. One explicit, revision-bound activation authorizes only
the changes described by that plan. No unmount, mount, repair or reset runs here.
"""
import copy
import json
import re
import secrets
import subprocess


class Problem(ValueError):
    def __init__(self, message, field='automatic-recovery', action='advanced'):
        super().__init__(message)
        self.field, self.action = field, action


def text(path):
    return path.read_text() if path.exists() else None


def email_revision(path):
    if not path.exists():
        return None
    info = path.stat()
    return [info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def proposal(b, uuid, automatic, allow_active=False):
    if type(automatic) is not bool:
        raise Problem('Choose whether to reconnect your drive automatically.')
    old = b.configuration()
    if b.migration.pending(b.migration_context()):
        raise Problem('An earlier location change is unfinished. Open Advanced settings to finish or undo it.')
    if not allow_active and b.service_state().get('ActiveState') not in ('inactive', 'failed'):
        raise Problem('Stop monitoring before changing settings.', 'protection-status', 'pause')
    try:
        if not allow_active: b.cli.stopped()
    except ValueError:
        raise Problem('An earlier recovery is still unfinished. Open Advanced settings to check its progress.',
                      'protection-status') from None
    try:
        row = b.target(uuid)
    except ValueError:
        raise Problem('Choose an available supported USB drive. Reconnect it if it is missing.', 'drive-choice', 'refresh') from None
    if old['disk']['uuid'] and old['disk']['uuid'] != uuid:
        raise Problem('These settings belong to another drive. Use Add USB drive on Overview to configure an independent monitor.', 'drive-choice', 'refresh')
    if row['transport'] != 'usb' and old['disk']['uuid'] != uuid:
        raise Problem('Choose a USB drive from the list.', 'drive-choice', 'refresh')
    c = copy.deepcopy(old)
    c['disk'].update(uuid=uuid, label=old['disk']['label'] if old['disk']['uuid'] else row['model'][:40])
    c['recovery']['mount'] = automatic
    c['usb']['enabled'] = automatic  # Actual writes still require a current isolated port binding.
    addition = None
    try:
        entries = [entry for entry in b.fstab_entries() if b.same_source(entry[0], row)] if automatic else []
        path = (old['disk']['mountpoint'] if old['disk']['uuid'] else
                b.w.unescape_mount(entries[0][1]) if len(entries) == 1 else
                row['mountpoint'] or '/mnt/usb-storage-watch-' + uuid)
        c['disk']['mountpoint'] = path
        if automatic:
            if any(len(entry) != 6 or entry[4] != '0' or entry[5] not in ('0', '1', '2') for entry in entries):
                raise ValueError('Incomplete mount entry')
            addition = b.mount_plan(c, row, ['fstab'], allow_desktop=True)
        else:
            c['disk']['fstab_options'] = ''
        b.s.validate(c)
    except (ValueError, b.w.Unsafe):
        raise Problem('This drive has conflicting connection settings. Choose monitoring only, or review the conflict in Advanced settings.',
                      action='monitor-only') from None
    try:
        # Includes identity, both read/write flags, ext4 error metadata and
        # duplicates. USB qualification is never a prerequisite for remounting.
        b.w.configure(c)
        observed = b.w.snapshot()
        if automatic:
            if not observed['detected']:
                raise Problem('The drive disconnected. Reconnect it, then refresh the drive list.', 'drive-choice', 'refresh')
            if observed.get('unsafe') or (row['mountpoint'] and not observed['healthy']):
                raise Problem('This drive cannot be reconnected safely right now. Choose monitoring only and check the drive in your Disks application.',
                              action='monitor-only')
            rows = b.w.read_rows()
            dev = b.w.device_number('/dev/disk/by-uuid/' + uuid)
            b.w.block_checks(dev, uuid)
            if not row['mountpoint']:
                b.w.mount_available(rows, path, dev)
            backing = b.w.recovery_backing(rows, path, dev, mounted=bool(row['mountpoint']))
            b.w.protected_mount_directory(path, backing, mounted=bool(row['mountpoint']))
            if b.s.storage_images(c):
                for item in b.s.storage_images(c): b.w.fstab_check(item['mountpoint'])
    except Problem:
        raise
    except (OSError, ValueError, b.w.Unsafe):
        raise Problem('The drive’s current location cannot be used safely for recovery. Choose monitoring only, or review location options in Advanced settings.',
                      action='monitor-only') from None
    token = b.s.digest(dict(config=old, fstab=text(b.FSTAB), smtp=email_revision(b.s.SMTP),
                           row=row, automatic=automatic, proposed=c['disk']))
    message = ('Your existing connection settings will be used. Your files stay where they are.' if automatic and not addition else
               'Allow this computer to remember where to reconnect this drive. Your files stay where they are; a missing drive will not prevent startup.' if automatic else
               'Your drive will be watched for problems. It will not be reconnected automatically.')
    return dict(ready=True, token=token, message=message,
                consent='Activating saves these choices and starts monitoring now and at startup.',
                change=bool(addition), advanced_enabled=bool(c['usb']['enabled'] or c['docker']['enabled'] or c['dependent']['enabled']),
                _config=c, _addition=addition, _row=row)


def plan(b, uuid, automatic):
    try:
        return {key: value for key, value in proposal(b, uuid, automatic).items() if not key.startswith('_')}
    except Problem as exc:
        return dict(ready=False, message=str(exc), field=exc.field, action=exc.action)
    except (OSError, ValueError, subprocess.SubprocessError, b.w.Unsafe):
        return dict(ready=False, message='Monitoring settings could not be checked. Open Advanced settings to check the service.',
                    field='protection-status', action='advanced')


def email(b, data):
    if not isinstance(data, dict):
        raise Problem('Enter your email provider’s settings.', 'email-enabled', 'edit')
    for key, label in [('host', 'Email server'), ('username', 'Email login'), ('password', 'Email password'),
                       ('sender', 'Sender address'), ('recipient', 'Notification address')]:
        value = data.get(key)
        if key == 'password' and not value and b.s.SMTP.exists():
            continue
        valid = isinstance(value, str) and 0 < len(value) <= 4096
        if valid and key == 'host':
            valid = bool(re.fullmatch(r'[A-Za-z0-9.-]+', value))
        if valid and key in ('sender', 'recipient'):
            try:
                b.n.address(value)
            except ValueError:
                valid = False
        if not valid:
            raise Problem(label + ': enter a valid value.', 'smtp-' + key, 'edit')
    if type(data.get('port')) is not int or not 1 <= data['port'] <= 65535:
        raise Problem('Email port: enter a number from 1 to 65535.', 'smtp-port', 'edit')
    if data.get('security') not in ('starttls', 'tls'):
        raise Problem('Choose a secure email connection.', 'smtp-security', 'edit')
    return b.prepare_smtp(data)


def activate(b, data, start_monitor=True):
    if (set(data) - {'uuid', 'automatic', 'notifications', 'smtp', 'token', 'consent'}
            or data.get('consent') is not True):
        raise Problem('Review your choices and click Start monitoring to allow them.', 'activate-protection', 'review')
    if 'notifications' in data and type(data['notifications']) is not bool:
        raise Problem('Choose whether to send email notifications.', 'email-enabled', 'edit')
    # Lock also excludes surviving recovery workers. Never stop them implicitly.
    try:
        with b.migration.exclusive(b.migration_context()):
            chosen = proposal(b, data.get('uuid'), data.get('automatic'))
            if data.get('token') != chosen['token']:
                raise Problem('The drive or settings changed. Review the updated choices before activating.', 'activate-protection', 'review')
            c, addition = copy.deepcopy(chosen['_config']), chosen['_addition']
            if 'notifications' in data:c['notifications']['enabled'] = data['notifications']
            # The normal Setup screen never rewrites independent Email settings.
            smtp = email(b, data['smtp']) if c['notifications']['enabled'] and 'smtp' in data else None
            b.s.validate(c)
            before = {name: text(path) for name, path in [('fstab', b.FSTAB), ('config', b.s.CONFIG), ('smtp', b.s.SMTP)]}
            # Retain a private immutable record before any configuration mutation.
            b.cli.save(b.s.STATE_DIR / 'setup-backups' / (secrets.token_hex(16) + '.json'), before)
            if proposal(b, data['uuid'], data['automatic'])['token'] != chosen['token']:
                raise Problem('The drive or settings changed. Review the updated choices before activating.', 'activate-protection', 'review')
            written = {}
            try:
                if c['recovery']['mount']:
                    path = c['disk']['mountpoint']
                    rows = b.w.read_rows()
                    dev = b.w.device_number('/dev/disk/by-uuid/' + c['disk']['uuid'])
                    mounted = bool(chosen['_row']['mountpoint'])
                    backing = b.w.recovery_backing(rows, path, dev, mounted=mounted)
                    if not mounted:
                        b.w.protected_mount_directory(path, backing, create=True)
                if addition:
                    content = before['fstab'] + addition
                    if text(b.FSTAB) != before['fstab']:
                        raise Problem('Connection settings changed. Review your choices again.', action='review')
                    b.w.atomic_write(b.FSTAB, content, mode=0o644)
                    written[b.FSTAB] = (before['fstab'], content)
                    b.command(['/usr/bin/systemctl', 'daemon-reload'])
                # A desktop mounter may have raced the write. Re-evaluate identity,
                # current location and all safety observations before saving.
                fresh = proposal(b, data['uuid'], data['automatic'])
                if fresh['_config'] != chosen['_config'] or fresh['_row'] != chosen['_row']:
                    raise Problem('The drive changed while saving. Refresh the drive list.', 'drive-choice', 'refresh')
                if text(b.s.CONFIG) != before['config'] or text(b.s.SMTP) != before['smtp']:
                    raise Problem('Settings changed while saving. Review your choices again.', 'activate-protection', 'review')
                b.w.configure(c)
                if c['recovery']['mount']:
                    b.w.fstab_check(b.w.MOUNT)
                if smtp is not None:
                    content = json.dumps(smtp, indent=2) + '\n'
                    b.cli.save(b.s.SMTP, smtp)
                    written[b.s.SMTP] = (before['smtp'], content)
                b.cli.save(b.s.CONFIG, c)
                written[b.s.CONFIG] = (before['config'], json.dumps(c, indent=2) + '\n')
            except Exception:
                # Never replace an administrator's concurrent edits.
                for path, (original, expected) in reversed(list(written.items())):
                    if path == b.FSTAB and text(b.s.CONFIG) != before['config']:
                        # A concurrent configuration may now use this entry.
                        # Retain it and the backup instead of breaking that config.
                        continue
                    if text(path) == expected:
                        if original is None:
                            path.unlink()
                        else:
                            b.w.atomic_write(path, original, mode=0o644 if path == b.FSTAB else 0o600)
                if addition and text(b.FSTAB) == before['fstab']:
                    try:
                        b.command(['/usr/bin/systemctl', 'daemon-reload'])
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                raise
    except Problem:
        raise
    except (ValueError, b.w.Unsafe, OSError, subprocess.SubprocessError):
        raise Problem('Monitoring could not be saved safely. Open Advanced settings to check the service and connection settings.',
                      'protection-status') from None
    # Release the engine lock before starting it. Starting never grants new
    # capabilities: the engine repeats identity, namespace and filesystem checks.
    if not start_monitor:
        return dict(message='Automatic recovery settings saved.',service=b.service_state())
    try:
        b.command(['/usr/bin/systemctl', 'enable', '--now', b.cli.SERVICE], 30)
        service = b.service_state()
        if service.get('ActiveState') != 'active':
            raise ValueError()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Problem('Your choices are saved, but monitoring could not start. Open Advanced settings to check the service.',
                      'protection-status') from None
    return dict(message='Monitoring is on.', service=service)


def recovery_plan(b,data):
    if set(data)!={'enabled'} or data['enabled'] not in ('true','false'):
        raise ValueError('Choose whether to enable automatic recovery for this drive.')
    c=b.configuration();enabled=data['enabled']=='true'
    if not c['disk']['uuid']: raise ValueError('Add a drive before configuring recovery.')
    if enabled:
        chosen=proposal(b,c['disk']['uuid'],True,allow_active=True)
        return {k:v for k,v in chosen.items() if not k.startswith('_')} | dict(uuid=c['disk']['uuid'],enabled=True)
    return dict(ready=True,uuid=c['disk']['uuid'],enabled=False,
                token=b.s.digest(dict(config=c,fstab=text(b.FSTAB),automatic=False)),
                message='Automatic mounting and USB recovery will be disabled. Monitoring keeps its current on/off setting.')


def recovery_settings(b,data):
    if set(data)!={'enabled','uuid','token','consent'} or type(data['enabled']) is not bool or data['consent'] is not True:
        raise ValueError('Review and explicitly confirm this drive’s recovery settings.')
    chosen=recovery_plan(b,dict(enabled=str(data['enabled']).lower()))
    if data['uuid']!=chosen['uuid'] or data['token']!=chosen['token']:
        raise ValueError('Drive settings changed. Review the recovery options again.')
    service=b.service_state().get('ActiveState')
    if service not in ('active','inactive','failed'): raise ValueError('Wait for this drive’s monitor to settle.')
    active=service=='active'
    # The same reviewed transaction and operation locks remain authoritative.
    # Stop only this monitor; an unfinished incident prevents the configuration write.
    if active:b.command(['/usr/bin/systemctl','stop',b.cli.SERVICE],35)
    try:
        b.cli.stopped()
        if data['enabled']:
            activate(b,dict(uuid=data['uuid'],automatic=True,token=data['token'],consent=True),start_monitor=False)
        else:
            with b.migration.exclusive(b.migration_context()):
                fresh=recovery_plan(b,dict(enabled='false'))
                if fresh['token']!=data['token']:raise ValueError('Settings changed. Review again.')
                c=b.configuration()
                b.cli.save(b.s.STATE_DIR/'setup-backups'/(secrets.token_hex(16)+'.json'),dict(config=c,fstab=text(b.FSTAB)))
                c['recovery']['mount']=False;c['usb']['enabled']=False
                b.cli.save(b.s.CONFIG,b.s.validate(c))
    finally:
        if active:b.command(['/usr/bin/systemctl','start',b.cli.SERVICE],30)
    state=b.service_state()
    if active and state.get('ActiveState')!='active':raise ValueError('Recovery settings saved, but this drive’s monitor could not restart. Start monitoring again after checking its journal.')
    return dict(message='Automatic recovery '+('enabled.' if data['enabled'] else 'disabled.'),service=state)
