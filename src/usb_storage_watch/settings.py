# SPDX-License-Identifier: MIT
"""Strict, versioned configuration. No host-specific defaults or secret discovery."""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

VERSION = '2.0.1~beta2'
# Each process/module has an immutable drive context. No process-wide selection
# is changed by dashboard requests. The original profile keeps all DEV7 paths.
PROFILE = globals().get('PROFILE') or {'id': os.environ.get('USB_STORAGE_WATCH_DRIVE', 'legacy')}
PROFILE_ID = PROFILE['id']
if PROFILE_ID != 'legacy' and str(uuid.UUID(PROFILE_ID)) != PROFILE_ID:
    raise ValueError('Invalid drive profile identifier')
CONFIG_ROOT = Path(PROFILE.get('config_root', '/etc/usb-storage-watch'))
STATE_ROOT = Path(PROFILE.get('state_root', '/var/lib/usb-storage-watch'))
CONFIG = CONFIG_ROOT / 'config.json' if PROFILE_ID == 'legacy' else CONFIG_ROOT / 'drives' / PROFILE_ID / 'config.json'
SMTP = CONFIG_ROOT / 'smtp.json'
STATE_DIR = STATE_ROOT if PROFILE_ID == 'legacy' else STATE_ROOT / 'drives' / PROFILE_ID
SERVICE = 'usb-storage-watch.service' if PROFILE_ID == 'legacy' else 'usb-storage-watch@' + PROFILE_ID + '.service'


def worker_environment():
    return dict(os.environ, USB_STORAGE_WATCH_DRIVE=PROFILE_ID)

DEFAULT = {
    'version': 1,
    'disk': {'uuid': '', 'mountpoint': '/mnt/storage', 'label': 'USB storage', 'fstab_options': ''},
    'monitor': {'interval': 15, 'observations': 2, 'boot_grace': 90},
    'notifications': {'enabled': False},
    'recovery': {'mount': False, 'wait': 15, 'attempts': 1, 'worker_timeout': 120, 'return_timeout_minutes': 5},
    'standby': {'enabled': False, 'idle_seconds': 1800},
    'services': {'units': []},
    'images': [],
    'dependent': {'enabled': False, 'uuid': '', 'mountpoint': '', 'image': '', 'fstab_options': ''},
    'usb': {'enabled': False, 'profile': None, 'disable_seconds': 1, 'enumeration_seconds': 20},
    'docker': {'enabled': False, 'socket': '/var/run/docker.sock', 'api': 'v1.47',
               'health_timeout': 120, 'worker_timeout': 720, 'containers': []},
}


class ConfigError(ValueError):
    pass


def default():
    return copy.deepcopy(DEFAULT)


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ConfigError(label + ': unexpected/missing configuration fields')


def boolean(value, label):
    if type(value) is not bool:
        raise ConfigError(label + ' must be true or false')


def number(value, low, high, label, integer=True):
    if ((type(value) is not int if integer else type(value) not in (int, float))
            or not low <= value <= high):
        raise ConfigError(f'{label} must be between {low} and {high}')


def absolute(value, label):
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or str(Path(value)) != value or '..' in Path(value).parts
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ConfigError(label + ' must be an absolute normalized path without whitespace')
    return value


def below(parent, child):
    return child.startswith(parent.rstrip('/') + '/')


def disk_uuid(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ConfigError('Expected a lowercase canonical ext4 UUID') from None


def options(value, loop=False):
    if not isinstance(value, str) or not value:
        raise ConfigError('Guarded mounts require exact reviewed fstab_options')
    allowed = {'defaults', 'rw', 'nofail', 'nodev', 'nosuid', 'noexec', 'noatime',
               'relatime', 'lazytime', 'errors=remount-ro'}
    if loop:
        allowed.update(('loop','noauto'))  # Disabled images must not remount at system boot.
    for item in value.split(','):
        if item not in allowed and not re.fullmatch(
                r'x-systemd\.(device-timeout=[1-9][0-9]*s|requires-mounts-for=/[A-Za-z0-9_./-]+)', item):
            raise ConfigError('Unreviewed/unsafe mount option: ' + item)
    if loop and 'loop' not in value.split(','):
        raise ConfigError('Dependent image mount must use the loop option')


PROFILE_KEYS = ('controller', 'controller_real', 'controller_ids', 'root_hub', 'root_hub_ids',
                'port', 'canonical', 'device', 'device_real', 'firmware', 'vid', 'pid',
                'disk_serial', 'qualified', 'qualification')


def usb_profile(p, qualified=False):
    software = isinstance(p, dict) and p.get('mode') == 'software'
    exact(p, (*PROFILE_KEYS, 'mode') if software else PROFILE_KEYS, 'usb.profile')
    for key in ('controller', 'controller_real', 'root_hub', 'port', 'canonical', 'device', 'device_real', 'firmware'):
        absolute(p[key], 'usb.' + key)
    # Only directly attached PCI xHCI root ports are supported. Never a shared hub.
    match = re.fullmatch(r'/sys/bus/usb/devices/(\d+)-0:1\.0/usb\1-port([1-9]\d*)', p['port'])
    pci = re.fullmatch(r'/sys/bus/pci/devices/([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7])', p['controller'])
    if not match or not pci:
        raise ConfigError('USB recovery supports only qualified direct PCI root ports')
    bus, port = match.groups()
    base = p['controller_real']
    if (not base.startswith('/sys/devices/') or Path(base).name != pci[1]
            or p['root_hub'] != f'/sys/bus/usb/devices/usb{bus}'
            or p['canonical'] != f'{base}/usb{bus}/{bus}-0:1.0/usb{bus}-port{port}'
            or p['device'] != f'/sys/bus/usb/devices/{bus}-{port}'
            or p['device_real'] != f'{base}/usb{bus}/{bus}-{port}'
            or not p['firmware'].startswith('/sys/devices/')):
        raise ConfigError('USB controller, root port and device topology disagree')
    exact(p['controller_ids'], ('vendor','device','subsystem_vendor','subsystem_device','class','revision'), 'controller_ids')
    exact(p['root_hub_ids'], ('idVendor','idProduct','serial'), 'root_hub_ids')
    if p['controller_ids']['class'] != '0x0c0330' or p['root_hub_ids']['serial'] != pci[1]:
        raise ConfigError('Expected a matching PCI xHCI root-hub identity')
    for value in p['controller_ids'].values():
        if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-f]{2,6}', value):
            raise ConfigError('Invalid controller identity')
    for value in (p['vid'], p['pid'], p['root_hub_ids']['idVendor'], p['root_hub_ids']['idProduct']):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{4}', value):
            raise ConfigError('Invalid USB VID/PID')
    if (not isinstance(p['disk_serial'], str) or not p['disk_serial'] or len(p['disk_serial']) > 256
            or any(ord(x) < 32 for x in p['disk_serial'])):
        raise ConfigError('A unique known-good disk identity is required')
    boolean(p['qualified'], 'usb.qualified')
    q = p['qualification']
    if p['qualified']:
        exact(q, ('date','evidence','isolated_port','reenable_verified','expected_disk_returned'), 'qualification')
        if (not isinstance(q['date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', q['date']) or not isinstance(q['evidence'], str)
                or not 20 <= len(q['evidence'].strip()) <= 1000
                or any(q[k] is not True for k in ('isolated_port','reenable_verified','expected_disk_returned'))):
            raise ConfigError('Independent offline qualification evidence is incomplete')
        try:
            datetime.date.fromisoformat(q['date'])
        except ValueError:
            raise ConfigError('Invalid independent qualification date') from None
    elif q is not None:
        raise ConfigError('Unqualified candidate must have qualification=null')
    if qualified and not (p['qualified'] or software):
        raise ConfigError('USB reconnect needs a verified software port binding')
    return p


def validate(c, allow_unconfigured=False):
    # Additive upgrade: preserve existing disk, SMTP, Docker and loop settings.
    c = copy.deepcopy(c)
    for key in ('standby', 'services', 'images'):
        c.setdefault(key, copy.deepcopy(DEFAULT[key]))
    if isinstance(c.get('recovery'), dict):
        c['recovery'].setdefault('return_timeout_minutes', 5)
    exact(c, DEFAULT, 'configuration')
    if type(c['version']) is not int or c['version'] != 1:
        raise ConfigError('Unsupported configuration version')
    for key in DEFAULT:
        if key not in ('version', 'images'):
            exact(c[key], DEFAULT[key], key)
    d, m, r, dep, u, a = (c[k] for k in ('disk','monitor','recovery','dependent','usb','docker'))
    if d['uuid'] or not allow_unconfigured:
        disk_uuid(d['uuid'])
    absolute(d['mountpoint'], 'disk.mountpoint')
    if d['mountpoint'] in ('/usr','/etc','/var','/home','/boot','/sys','/dev','/proc'):
        raise ConfigError('System directories cannot be monitored as removable mountpoints')
    if any(below(p,d['mountpoint']) for p in ('/sys','/dev','/proc','/etc','/usr','/var/lib/usb-storage-watch')):
        raise ConfigError('Unsafe mountpoint location')
    if not isinstance(d['label'],str) or not 1 <= len(d['label']) <= 40 or not d['label'].isprintable():
        raise ConfigError('disk.label must be 1–40 printable characters')
    number(m['interval'], 5, 3600, 'monitor.interval')
    number(m['observations'], 1, 10, 'monitor.observations')
    number(m['boot_grace'], 0, 3600, 'monitor.boot_grace')
    number(r['wait'], 15, 86400, 'recovery.wait')
    number(r['attempts'], 1, 2, 'recovery.attempts')
    number(r['worker_timeout'], 80, 300, 'recovery.worker_timeout')
    number(r['return_timeout_minutes'], 1, 1440, 'recovery.return_timeout_minutes')
    boolean(c['standby']['enabled'], 'standby.enabled')
    number(c['standby']['idle_seconds'], 60, 86400, 'standby.idle_seconds')
    units = c['services']['units']
    if (not isinstance(units, list) or len(units) > 10 or len(set(units)) != len(units)
            or any(not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\.service', unit)
                   or unit.startswith(('usb-storage-watch', 'systemd-', 'dbus.', 'docker.', 'containerd.')) for unit in units)):
        raise ConfigError('Select up to 10 application .service units; system and Docker daemons are excluded')
    for value, name in ((c['notifications']['enabled'],'notifications'),(r['mount'],'mount recovery'),
                        (dep['enabled'],'dependent'),(u['enabled'],'usb'),(a['enabled'],'docker')):
        boolean(value,name)
    if d['fstab_options'] or r['mount']:
        options(d['fstab_options'])
    if not isinstance(c['images'], list):
        raise ConfigError('Application storage must be a list')
    for item in c['images']:
        exact(item, (*DEFAULT['dependent'], 'name'), 'storage image')
        boolean(item['enabled'], 'storage image enabled')
        if not isinstance(item['name'],str) or not 1 <= len(item['name']) <= 40 or not item['name'].isprintable():
            raise ConfigError('Give each storage image a name of 1–40 printable characters')
    seen = {key:set() for key in ('uuid','image','mountpoint')}
    for item in ([dep] if dep['enabled'] else []) + c['images']:
        disk_uuid(item['uuid'])
        for key in ('mountpoint','image'):
            absolute(item[key], 'storage image ' + key)
            if not below(d['mountpoint'], item[key]):
                raise ConfigError('Application storage must be inside the primary filesystem')
        if item['uuid'] == d['uuid'] or item['image'] == item['mountpoint'] or below(item['mountpoint'],item['image']):
            raise ConfigError('Dependent filesystem/image identities conflict')
        options(item['fstab_options'], loop=True)
        for key in seen:
            if item[key] in seen[key]: raise ConfigError('Application storage identities and paths must be unique')
            seen[key].add(item[key])
    storage_images(c)  # Also checks dependency cycles and disabled prerequisites.
    if u['profile'] is not None:
        usb_profile(u['profile'])  # Live topology is qualified before each operation.
    if u['enabled'] and not r['mount']:
        raise ConfigError('USB reconnect needs automatic recovery enabled')
    number(u['disable_seconds'], .1, 2, 'usb.disable_seconds', False)
    number(u['enumeration_seconds'], 1, 60, 'usb.enumeration_seconds', False)
    if r['worker_timeout'] < u['enumeration_seconds'] + 50:
        raise ConfigError('recovery.worker_timeout must allow enumeration plus 50 seconds')
    absolute(a['socket'], 'docker.socket')
    if not a['socket'].startswith(('/run/','/var/run/')) or not re.fullmatch(r'v1\.\d{2}',a['api']):
        raise ConfigError('Docker requires a local /run socket and explicit API version')
    number(a['health_timeout'], 5, 300, 'docker.health_timeout')
    number(a['worker_timeout'], 60, 3600, 'docker.worker_timeout')
    if not isinstance(a['containers'],list):
        raise ConfigError('Select Docker containers from the discovered list')
    names=set()
    image_ids={item['uuid'] for item in storage_images(c, False)}
    for app in a['containers']:
        if isinstance(app, dict):
            app.setdefault('container_id', '')
            app.setdefault('images', [])
        exact(app,('name','source','destination','grace','container_id','images'),'container')
        if not isinstance(app['name'], str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',app['name']) or app['name'] in names:
            raise ConfigError('Container names must be unique Docker names')
        names.add(app['name'])
        # Legacy bind fields are advisory hints, never restart eligibility gates.
        for key in ('source', 'destination'):
            if app[key] != '': absolute(app[key], 'container.' + key)
        if not isinstance(app['container_id'], str) or (app['container_id'] and not re.fullmatch('[0-9a-f]{64}', app['container_id'])):
            raise ConfigError('Container identity must be a full Docker ID')
        if (not isinstance(app['images'], list) or any(not isinstance(v, str) for v in app['images'])
                or len(set(app['images'])) != len(app['images']) or not set(app['images']) <= image_ids):
            raise ConfigError('Select virtual images registered on this drive')
        number(app['grace'], 5, 120, 'container.grace')
    if a['enabled'] and not a['containers']:
        raise ConfigError('Select at least one container to restart after drive recovery.')
    return copy.deepcopy(c)


def storage_images(c, enabled=True):
    """Legacy configuration remains readable; return dependencies before consumers."""
    items = ([dict(c['dependent'], name=Path(c['dependent']['image']).stem)] if c['dependent']['enabled'] else []) + c.get('images', [])
    result, pending = [], list(items)
    while pending:
        ready = [item for item in pending if not any(other is not item and
                 (below(other['mountpoint'],item['image']) or below(other['mountpoint'],item['mountpoint'])) for other in pending)]
        if not ready: raise ConfigError('Application storage has a circular dependency')
        for item in ready:
            parents = [other for other in result if below(other['mountpoint'],item['image']) or below(other['mountpoint'],item['mountpoint'])]
            if item['enabled'] and any(not other['enabled'] for other in parents):
                raise ConfigError('Enable required parent storage before its dependent image')
            result.append(item);pending.remove(item)
    return [item for item in result if item['enabled']] if enabled else result


def digest(c):
    return hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read(path=CONFIG, protected=True):
    if protected:
        info=path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ConfigError('Configuration directory must be root-owned mode 0700')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    with os.fdopen(fd,'r') as handle:
        info=os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConfigError('Configuration must be a single regular file')
        if protected and (info.st_uid != 0 or info.st_mode & 0o077):
            raise ConfigError('Configuration must be root-owned mode 0600')
        return validate(json.load(handle))
