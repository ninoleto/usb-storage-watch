# SPDX-License-Identifier: MIT
"""Complete incident simulations across Monitor, storage workers and Docker ledgers.

Only kernel/device and Docker boundaries are emulated. No physical disk, live
container, service or SMTP operation is performed by this module.
"""
import copy
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MAIN_UUID = '11111111-1111-4111-8111-111111111111'
IMAGE_UUID = '22222222-2222-4222-8222-222222222222'
BOOT = 'synthetic-lifecycle-boot'
CONTAINER = 'a' * 64
UNRELATED = 'b' * 64
MAIN = '/mnt/storage'
IMAGE = MAIN + '/_loop/files.img'
IMAGE_MOUNT = MAIN + '/_loop/files'


def load(name):
    spec = importlib.util.spec_from_file_location('lifecycle_' + name, ROOT / 'src/usb_storage_watch' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerBoundary:
    def __init__(self, machine):
        self.machine = machine
        self.containers = {
            'selected_app': dict(id=CONTAINER, name='selected_app', running=True,
                paused=False, restarting=False, dead=False, started_at='initial',
                pid=1200, healthcheck=False, health=None,
                mounts=[dict(Type='bind', Source=IMAGE_MOUNT + '/uploads',
                             Destination='/uploads', RW=True, Propagation='rprivate')]),
            'unrelated_app': dict(id=UNRELATED, name='unrelated_app', running=True,
                paused=False, restarting=False, dead=False, started_at='unchanged',
                pid=1300, healthcheck=False, health=None, mounts=[]),
        }
        self.fail_stop = False
        self.after_start = lambda: None

    def inspect(self, name):
        if name not in self.containers:
            name = next(key for key, item in self.containers.items() if item['id'] == name)
        return copy.deepcopy(self.containers[name])

    def change(self, name, identity, action):
        self.machine.case.assertEqual(identity, self.containers[name]['id'])
        self.machine.case.assertEqual(name, 'selected_app')
        self.machine.events.append('docker:' + action)
        if action == 'stop':
            if self.fail_stop:
                raise self.machine.w.apps.AppError('Synthetic Docker stop refusal')
            self.containers[name].update(running=False, pid=0)
        elif action == 'start':
            self.machine.case.assertTrue(self.machine.healthy())
            self.machine.case.assertTrue(self.machine.image_healthy())
            self.containers[name].update(running=True, pid=1201,
                                         started_at='started-' + str(self.machine.now))
            self.after_start()
        else:
            raise AssertionError('Automatic lifecycle must use stop then start, not ' + action)


class Machine:
    def __init__(self, case):
        self.case = case
        self.stack = ExitStack()
        case.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='usw-lifecycle-')))
        self.w = load('engine')
        self.now = 0.0
        self.events = []
        self.present = True
        self.dev = '240:17'
        self.diskseq = 10
        self.loop = '7:8'
        self.loop_backing = '240:17'
        self.loop_attached = True
        self.fail_image = False
        self.mount_id = 2
        self.main_row = self.row('2', '1', self.dev, MAIN, '/dev/sdc1')
        self.image_row = self.row('3', '2', self.loop, IMAGE_MOUNT, '/dev/loop8')
        self.rows = [self.row('1', '0', '240:2', '/', '/dev/root'), self.main_row, self.image_row]
        fixture_spec = importlib.util.spec_from_file_location('lifecycle_fixture', ROOT/'tests/fixtures.py')
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        self.config = fixture.configuration(self.w)
        self.config['usb']['enabled'] = False
        self.config['docker']['containers'] = [dict(name='selected_app', container_id=CONTAINER,
            source=IMAGE_MOUNT + '/uploads', destination='/uploads', grace=10, images=[IMAGE_UUID])]
        self.w.configure(self.config)
        self.docker = DockerBoundary(self)
        self.patch(self.w, 'STATE_DIR', self.directory)
        self.patch(self.w, 'CONFIG', self.directory/'profile.json')
        self.patch(self.w, 'boot_id', lambda: BOOT)
        self.patch(self.w, 'clock_now', lambda: self.now)
        self.patch(self.w, 'timestamp', lambda: '2026-01-01T00:%02d:%02d+00:00' % (int(self.now)//60, int(self.now)%60))
        self.patch(self.w, 'log', lambda *_: None)
        self.patch(self.w, 'read_rows', lambda: copy.deepcopy(self.rows))
        self.patch(self.w, 'device_number', self.device_number)
        self.patch(self.w, 'connection_identity', lambda _: dict(boot=BOOT, diskseq=self.diskseq))
        self.patch(self.w, 'udev', self.udev)
        self.patch(self.w, 'block_checks', lambda dev, uuid: 'synthetic-' + dev)
        self.patch(self.w, 'disk_proof', self.disk_proof)
        self.patch(self.w, 'fstab_check', lambda *_: None)
        self.patch(self.w, 'protected_mount_directory', lambda *args, **kwargs: None)
        self.patch(self.w, 'safe_path', self.safe_path)
        self.patch(self.w, 'verify_access', lambda: None)
        self.patch(self.w, 'namespace_available', lambda *args, **kwargs: None)
        self.patch(self.w, 'command', self.command)
        self.patch(self.w, 'config_load', lambda: dict(automatic_recovery=True, usb_reset_enabled=False,
            docker_enabled=True, docker_containers=self.config['docker']['containers']))
        self.patch(self.w.apps, 'READER', self.w.config_load)
        # Storage workers inspect the same live Docker boundary as the stop
        # worker; the production stop guard must remain active in these tests.
        self.patch(self.w.apps, 'Docker', lambda: self.docker)
        self.patch(self.w.apps, 'HEALTH_TIMEOUT', 1)
        self.patch(self.w.apps.time, 'sleep', self.sleep)
        self.patch(self.w.apps.time, 'monotonic', lambda: self.now)
        self.patch(self.w.drives, 'roots', lambda _: (self.directory, self.directory))
        self.patch(self.w.drives, 'files', lambda _: [])
        self.patch(self.w.drives, 'enroll', lambda *args: None)
        self.patch(self.w.drives, 'verify_hardware', lambda *args: None)
        self.patch(self.w.usb, 'bind_current', mock.Mock(side_effect=self.w.Unsafe('Synthetic unqualified USB port')))
        self.patch(self.w.usb, 'incident_record', lambda *args: None)
        self._paths()
        self.monitor = self.w.Monitor(self.directory/'state.json', now=0, boot=BOOT)

    def patch(self, obj, name, value):
        return self.stack.enter_context(mock.patch.object(obj, name, value))

    def row(self, identity, parent, dev, target, source):
        return dict(id=identity, parent=parent, dev=dev, root='/', target=target,
                    fs='ext4', source=source, vfs={'rw', 'nosuid', 'nodev'} if target != '/' else {'rw'}, super={'rw'})

    def sleep(self, amount): self.now += amount

    def device_number(self, path):
        if not self.present: raise FileNotFoundError(str(path))
        if str(path) == '/dev/disk/by-uuid/' + MAIN_UUID: return self.dev
        if str(path).startswith('/dev/loop'): return self.loop
        raise AssertionError('Unexpected device lookup ' + str(path))

    def udev(self, dev):
        return dict(ID_FS_UUID=IMAGE_UUID if dev.startswith('7:') else MAIN_UUID, ID_FS_TYPE='ext4')

    def disk_proof(self, path, uuid, **kwargs):
        dev = self.loop if uuid == IMAGE_UUID else self.dev
        major, minor = map(int, dev.split(':'))
        return types.SimpleNamespace(st_rdev=os.makedev(major, minor))

    def safe_path(self, path, dev, **kwargs):
        return types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_dev=dev, st_ino=17)

    def _paths(self):
        original_exists, original_lstat = Path.exists, Path.lstat
        original_resolve, original_read = Path.resolve, Path.read_text
        original_stat, original_iterdir, original_glob = Path.stat, Path.iterdir, Path.glob
        original_os_stat = os.stat
        def exists(path):
            if str(path) == '/dev/disk/by-uuid/' + MAIN_UUID: return self.present
            return original_exists(path)
        def lstat(path, *args, **kwargs):
            if str(path).startswith('/sys/dev/block/240:'):
                if str(path).rsplit('/', 1)[-1] != self.dev or not self.present: raise FileNotFoundError(str(path))
                return types.SimpleNamespace(st_mode=stat.S_IFDIR)
            return original_lstat(path, *args, **kwargs)
        def resolve(path, *args, **kwargs):
            text = str(path)
            if text == '/dev/disk/by-uuid/' + MAIN_UUID: return Path('/dev/returned-disk')
            if text.startswith('/dev/block/7:'): return Path('/dev/loop' + text.rsplit(':',1)[-1])
            return original_resolve(path, *args, **kwargs)
        def read(path, *args, **kwargs):
            text = str(path)
            if text.startswith('/sys/fs/ext4/') and text.endswith('/errors_count'): return '0\n'
            if text == '/proc/swaps': return 'Filename Type Size Used Priority\n'
            if text.startswith('/sys/dev/block/7:'):
                if text.endswith('/backing_file'):
                    if not self.loop_attached:raise FileNotFoundError(text)
                    return IMAGE
                if text.endswith('/offset') or text.endswith('/sizelimit'): return '0'
            return original_read(path, *args, **kwargs)
        def path_stat(path, *args, **kwargs):
            if str(path) == IMAGE:
                major, minor = map(int, self.dev.split(':'))
                return types.SimpleNamespace(st_dev=os.makedev(major,minor), st_ino=17, st_mode=stat.S_IFREG|0o600, st_nlink=1)
            return original_stat(path, *args, **kwargs)
        def iterdir(path):
            if str(path).startswith('/sys/dev/block/') and str(path).endswith('/holders'): return iter(())
            return original_iterdir(path)
        def glob(path, pattern, *args, **kwargs):
            if str(path) == '/sys/class/block' and pattern == 'loop*/loop/backing_file': return iter(())
            return original_glob(path, pattern, *args, **kwargs)
        def os_stat(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and str(path) == MAIN:
                major, minor = map(int, self.dev.split(':'))
                return types.SimpleNamespace(st_dev=os.makedev(major,minor), st_ino=16)
            return original_os_stat(path, *args, **kwargs)
        for name, fn in [('exists',exists),('lstat',lstat),('resolve',resolve),('read_text',read),
                         ('stat',path_stat),('iterdir',iterdir),('glob',glob)]: self.patch(Path,name,fn)
        self.patch(os, 'stat', os_stat)

    def healthy(self):
        return self.present and any(row['target'] == MAIN and row['dev'] == self.dev and
            'shutdown' not in row['super'] for row in self.rows)

    def image_healthy(self):
        return self.healthy() and self.loop_backing == self.dev and any(row['target'] == IMAGE_MOUNT for row in self.rows)

    def command(self, argv, **kwargs):
        if argv[0] == '/usr/sbin/losetup' and '--list' in argv:
            return json.dumps(dict(loopdevices=[dict(name='/dev/loop' + self.loop.split(':')[1],
                **{'back-file': IMAGE, 'back-maj:min': self.loop_backing, 'back-ino':17, 'offset':0, 'sizelimit':0})] if self.loop_attached else []))
        if argv[0] == '/usr/sbin/losetup' and ('--detach' in argv or '-d' in argv):
            self.events.append('detach:image'); self.loop_attached=False; return ''
        if argv[0] == '/usr/bin/umount':
            self.case.assertFalse(self.docker.containers['selected_app']['running'])
            target=argv[-1]
            self.case.assertNotIn('-f', argv);self.case.assertNotIn('-l', argv)
            self.events.append('unmount:image' if target==IMAGE_MOUNT else 'unmount:disk')
            self.rows=[row for row in self.rows if row['target'] != target]
            if target==IMAGE_MOUNT:self.loop_attached=False
            return ''
        if argv[0] == '/usr/bin/mount':
            self.case.assertFalse(self.docker.containers['selected_app']['running'])
            target=argv[-1]
            if target == MAIN:
                self.case.assertFalse(any(row['target']==MAIN for row in self.rows))
                self.events.append('mount:disk');self.mount_id+=2
                self.rows.append(self.row(str(self.mount_id),'1',self.dev,MAIN,'/dev/returned-disk'))
            elif target == IMAGE_MOUNT:
                self.case.assertTrue(self.healthy());self.events.append('mount:image')
                if self.fail_image:raise self.w.Unsafe('Synthetic selected image mount failure')
                self.loop='7:9';self.loop_backing=self.dev;self.loop_attached=True
                self.rows.append(self.row(str(self.mount_id+1),str(self.mount_id),self.loop,IMAGE_MOUNT,'/dev/loop9'))
            else:raise AssertionError('Unexpected mount target ' + target)
            return ''
        raise AssertionError('Unexpected command ' + repr(argv))

    def sample(self, when):
        self.now=float(when)
        snap=self.w.snapshot()
        self.monitor.sample(snap, now=self.now)
        return snap

    def establish(self):
        self.sample(0);self.sample(15)
        self.monitor.capture_result(dict(incident=None), self.w.apps.capture(self.w,self.docker))
        self.case.assertEqual(self.monitor.state['status'], 'up')

    def disconnect(self, when=30):
        self.present=False
        for row in self.rows:
            if row['target']==MAIN:row['super'].add('shutdown')
        self.sample(when)
        request=self.monitor.stop_request(self.now)
        self.case.assertIsNotNone(request)
        result=self.w.apps.stop_selected(self.w,request,self.docker)
        self.monitor.stop_result(result)
        return result

    def returned(self, when=330):
        self.present=True;self.dev='240:33' if self.dev=='240:17' else '240:17';self.diskseq+=1
        return self.sample(when)

    def recover(self):
        request=self.monitor.work_request(True,self.now)
        self.case.assertIsNotNone(request)
        result=self.w.recovery_work(request,self.directory/'recovery-receipt.json')
        self.monitor.work_result(request,result,self.now+1)
        return result

    def finish(self):
        queued=len(self.monitor.state['pending'])
        self.sample(self.now+15);self.sample(self.now+15)
        self.case.assertEqual(len(self.monitor.state['pending']),queued)
        request=self.monitor.app_request()
        self.case.assertIsNotNone(request)
        result=self.w.apps.recover(self.w,request,self.docker)
        self.monitor.app_result(result)
        return result


class LifecycleTests(unittest.TestCase):
    def setUp(self):self.machine=Machine(self)

    def test_explicit_replacement_pin_controls_both_failure_stop_and_recovery_start(self):
        m=self.machine;replacement='c'*64
        m.docker.containers['selected_app']['id']=replacement
        with self.assertRaises(m.w.apps.AppError):
            m.w.apps.validate_container('selected_app',m.docker.inspect('selected_app'))
        storage_digest=m.w.storage_config_digest(m.config)
        m.config['docker']['containers'][0]['container_id']=replacement
        m.patch(m.w,'runtime_configuration',lambda:copy.deepcopy(m.config))
        m.w.refresh_docker_settings()
        self.assertEqual(m.w.storage_config_digest(m.config),storage_digest)
        sent=[];change=m.docker.change
        def record(name,identity,action):
            sent.append((identity,action));return change(name,identity,action)
        m.docker.change=record
        m.establish();stop=m.disconnect()
        self.assertTrue(stop['all_stopped'])
        self.assertEqual(stop['containers']['selected_app']['container_id'],replacement)
        m.returned();self.assertTrue(m.recover()['main'])
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual(result['containers']['selected_app']['container_id'],replacement)
        self.assertEqual(sent,[(replacement,'stop'),(replacement,'start')])
        self.assertTrue(m.docker.containers['unrelated_app']['running'])

    def test_port_move_cleans_owned_images_then_disk_and_starts_before_one_email(self):
        m=self.machine;m.establish();stop=m.disconnect()
        self.assertTrue(stop['all_stopped']);self.assertEqual(m.events,['docker:stop'])
        for when in (45,60,75):
            m.sample(when)
            self.assertIsNone(m.monitor.work_request(True,when))
            self.assertIsNone(m.monitor.stop_request(when))
        m.sample(90)
        waiting=m.recover()
        self.assertTrue(waiting['waiting_device'],waiting)
        self.assertTrue(waiting['cleanup_complete'],waiting)
        self.assertEqual(m.events,['docker:stop','unmount:image','unmount:disk'])
        for when in range(105,330,15):
            m.sample(when)
            self.assertIsNone(m.monitor.work_request(True,when))
            self.assertIsNone(m.monitor.stop_request(when))
        self.assertEqual(m.monitor.state['incident']['attempts'],[])
        self.assertEqual(m.monitor.state['pending'],[])
        m.returned();result=m.recover()
        self.assertTrue(result['main'],result);self.assertTrue(result['dependent'],result)
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual([v for v in m.events if not v.startswith('detach:')],
            ['docker:stop','unmount:image','unmount:disk','mount:disk','mount:image','docker:start'])
        self.assertEqual(len(m.monitor.state['pending']),1)
        self.assertIn('selected_app',m.monitor.state['pending'][0]['detail'])
        self.assertTrue(m.docker.containers['unrelated_app']['running'])
        self.assertEqual(m.docker.containers['unrelated_app']['started_at'],'unchanged')
        for when in range(375,435,15):m.sample(when)
        self.assertIsNone(m.monitor.stop_request(435));self.assertIsNone(m.monitor.app_request())
        self.assertEqual(m.events.count('docker:start'),1)
        self.assertEqual(len(m.monitor.state['pending']),1)

    def test_selected_image_failure_keeps_container_stopped_and_reports_partial_outcome(self):
        m=self.machine;m.establish();m.disconnect();m.returned();m.fail_image=True
        result=m.recover();self.assertTrue(result['main']);self.assertFalse(result['dependent'])
        result=m.finish();self.assertFalse(result['all_verified'])
        self.assertNotIn('docker:start',m.events)
        self.assertFalse(m.docker.containers['selected_app']['running'])
        self.assertEqual(len(m.monitor.state['pending']),1)
        self.assertIn('Applications require attention',m.monitor.state['pending'][0]['subject'])

    def test_unconfirmed_docker_stop_prevents_all_disk_work(self):
        m=self.machine;m.establish();m.docker.fail_stop=True;result=m.disconnect()
        self.assertFalse(result['all_stopped'])
        m.returned()
        self.assertIsNone(m.monitor.work_request(True,m.now))
        self.assertEqual(m.events,['docker:stop'])
        self.assertTrue(m.docker.containers['selected_app']['running'])

    def test_late_stop_readback_resumes_recovery_without_another_stop_command(self):
        m=self.machine;m.establish();m.docker.fail_stop=True;m.disconnect()
        self.assertEqual(m.monitor.state['incident']['stop']['phase'],'pending')
        m.docker.containers['selected_app']['running']=False
        m.sample(45)
        request=m.monitor.stop_request(m.now);self.assertIsNotNone(request)
        result=m.w.apps.stop_selected(m.w,request,m.docker)
        m.monitor.stop_result(result)
        self.assertTrue(result['all_stopped'])
        self.assertEqual(m.events.count('docker:stop'),1)
        m.docker.fail_stop=False;m.returned();m.recover();m.finish()
        self.assertEqual(m.events.count('docker:start'),1)

    def test_disabled_automatic_mount_waits_then_starts_after_manual_restoration(self):
        m=self.machine;m.establish();m.disconnect()
        m.sample(90)
        self.assertIsNone(m.monitor.work_request(False,m.now))
        self.assertEqual(m.monitor.state['pending'],[])
        m.present=True
        for row in m.rows:row['super'].discard('shutdown')
        m.sample(105);m.sample(120)
        request=m.monitor.work_request(False,m.now);self.assertIsNotNone(request)
        result=m.w.recovery_work(request,m.directory/'recovery-receipt.json')
        m.monitor.work_result(request,result,m.now+1)
        self.assertTrue(result['main'])
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual(m.events,['docker:stop','docker:start'])

    def test_unrecognized_child_mount_is_not_unmounted_or_replaced(self):
        m=self.machine;m.establish();m.disconnect()
        m.rows.append(m.row('9','2','240:49',MAIN+'/foreign','/dev/foreign'))
        m.returned();result=m.recover()
        self.assertFalse(result['main']);self.assertEqual(m.events,['docker:stop'])
        self.assertTrue(any(row['target']==MAIN+'/foreign' for row in m.rows))
        self.assertFalse(m.docker.containers['selected_app']['running'])

    def test_one_bad_sample_still_resumes_container_after_natural_return(self):
        m=self.machine;m.establish();m.disconnect()
        # A short outage is sufficient to stop consumers; its natural return
        # must not leave the stopped container without a recovery incident.
        m.present=True
        for row in m.rows:row['super'].discard('shutdown')
        m.sample(45);m.sample(60);m.now=90
        result=m.recover();self.assertTrue(result['main'],result)
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual(m.events,['docker:stop','docker:start'])
        self.assertEqual(len(m.monitor.state['pending']),1)

    def test_second_outage_uses_new_incident_and_new_stop_start_pair(self):
        m=self.machine;m.establish();m.disconnect();m.returned();m.recover();m.finish()
        first=m.monitor.state['incident']['id']
        m.sample(375);m.disconnect(390);m.returned(510);m.recover();m.finish()
        self.assertNotEqual(first,m.monitor.state['incident']['id'])
        self.assertEqual(m.events.count('docker:stop'),2)
        self.assertEqual(m.events.count('docker:start'),2)
        self.assertEqual(len(m.monitor.state['pending']),2)

    def test_second_selected_drive_blocks_start_until_it_is_mounted(self):
        m=self.machine;m.establish();m.disconnect();m.returned();m.recover()
        other=copy.deepcopy(m.config)
        other['disk'].update(uuid='33333333-3333-4333-8333-333333333333',
                             mountpoint='/mnt/other',label='Other selected disk')
        other['dependent']['enabled']=False
        other['docker']['containers'][0]['images']=[]
        other_path=m.directory/'other.json'
        m.patch(m.w.drives,'files',lambda _: [('other',other_path)])
        m.patch(m.w.drives,'read',lambda *_:copy.deepcopy(other))
        original=m.w.device_number
        other_present=[False]
        def device(path):
            if str(path)=='/dev/disk/by-uuid/'+other['disk']['uuid']:
                if not other_present[0]:raise FileNotFoundError(str(path))
                return '240:49'
            return original(path)
        m.patch(m.w,'device_number',device)
        result=m.finish()
        self.assertTrue(result['waiting_storage']);self.assertFalse(result['complete'])
        self.assertNotIn('docker:start',m.events)
        self.assertEqual(m.monitor.state['pending'],[])
        other_present[0]=True
        m.rows.append(m.row('9','1','240:49','/mnt/other','/dev/other'))
        m.sample(m.now+15)
        request=m.monitor.app_request();self.assertIsNotNone(request)
        result=m.w.apps.recover(m.w,request,m.docker)
        m.monitor.app_result(result)
        self.assertTrue(result['all_verified'],result)
        self.assertEqual(m.events.count('docker:start'),1)
        self.assertEqual(len(m.monitor.state['pending']),1)

    def test_disk_loss_during_start_requests_a_new_stop_and_cannot_report_success(self):
        m=self.machine;m.establish();m.disconnect();m.returned();m.recover()
        m.sample(m.now+15);m.sample(m.now+15)
        def outage_during_start():
            m.present=False
            for row in m.rows:
                if row['target']==MAIN:row['super'].add('shutdown')
            m.sample(m.now+1)
        m.docker.after_start=outage_during_start
        request=m.monitor.app_request();self.assertIsNotNone(request)
        result=m.w.apps.recover(m.w,request,m.docker)
        self.assertTrue(result['interrupted'],result)
        m.monitor.app_result(result)
        stop_request=m.monitor.stop_request(m.now)
        self.assertIsNotNone(stop_request,'A container started during renewed storage loss must be stopped again.')
        stop=m.w.apps.stop_selected(m.w,stop_request,m.docker)
        m.monitor.stop_result(stop)
        self.assertFalse(m.docker.containers['selected_app']['running'])
        self.assertNotEqual(m.monitor.state['status'],'up')

    def test_no_return_after_usb_attempt_keeps_mount_attempt_available(self):
        m=self.machine;m.establish();m.disconnect();m.sample(90)
        def no_return(*args,**kwargs):
            self.assertEqual(m.events,['docker:stop','unmount:image','unmount:disk'])
            m.events.append('usb:attempt')
            return dict(cycled=False,ready=False,reason='Synthetic USB port unavailable')
        m.patch(m.w.usb,'cycle',no_return)
        request=m.monitor.work_request(True,m.now,usb_enabled=True)
        self.assertIsNotNone(request)
        result=m.w.recovery_work(request,m.directory/'recovery-receipt.json')
        self.assertTrue(result['waiting_device'],result)
        m.monitor.work_result(request,result,m.now+1)
        self.assertEqual(m.monitor.state['incident']['attempts'],[])
        self.assertEqual(m.monitor.state['pending'],[])
        m.sample(150)
        self.assertIsNone(m.monitor.work_request(True,m.now,usb_enabled=True))
        m.returned();result=m.recover();self.assertTrue(result['main'],result)
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual(m.events.count('docker:stop'),1)
        self.assertEqual(m.events.count('docker:start'),1)

    def test_old_failed_ui19_incident_with_no_writes_recovers_known_returned_tree(self):
        m=self.machine;m.establish();m.disconnect()
        state=copy.deepcopy(m.monitor.state);incident=state['incident'];old_id=incident['id']
        incident.update(phase='done',notified=True,recovery_generation=19,
            connection=dict(boot=BOOT,diskseq=11),blocked=['main'],
            result=m.w.failed_result('Synthetic legacy retained-mount refusal'))
        incident['attempts']=[dict(number=1,time='2026-01-01T00:01:30+00:00',boot=BOOT,
                                  status='failed',reason='Synthetic legacy refusal',actions=[])]
        incident['applications']['phase']='done'
        m.monitor.commit(state)
        m.returned(330);m.sample(345)
        self.assertNotEqual(m.monitor.state['incident']['id'],old_id)
        self.assertTrue((m.directory/'incidents'/f'{old_id}.json').exists())
        request=m.monitor.stop_request(m.now);self.assertIsNotNone(request)
        m.monitor.stop_result(m.w.apps.stop_selected(m.w,request,m.docker))
        m.sample(405);result=m.recover();self.assertTrue(result['main'],result)
        result=m.finish();self.assertTrue(result['all_verified'],result)
        self.assertEqual(m.events.count('docker:start'),1)

    def test_configured_path_with_wrong_image_uuid_is_never_detached(self):
        m=self.machine;m.establish();m.disconnect();m.returned()
        previous=m.w.udev
        m.patch(m.w,'udev',lambda dev:dict(ID_FS_UUID=MAIN_UUID,ID_FS_TYPE='ext4') if dev.startswith('7:') else previous(dev))
        result=m.recover()
        self.assertFalse(result['main'])
        self.assertIn('UUID',result['reason'])
        self.assertEqual(m.events,['docker:stop'])
        self.assertTrue(any(row['target']==IMAGE_MOUNT for row in m.rows))


if __name__=='__main__':unittest.main()
