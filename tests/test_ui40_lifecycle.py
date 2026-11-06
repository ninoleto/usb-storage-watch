"""Real maintainer-shell/embedded-helper execution; only disposable fake services.

PIDs below are local sleep fixtures. No real systemctl, storage or Docker command
is permitted. The installed payload intentionally retains the old broken helper.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


SYSTEMCTL = r'''#!/usr/bin/python3
import json,os,signal,sys,time
from pathlib import Path
p=Path(__file__).with_name('systemd.json');s=json.loads(p.read_text());args=sys.argv[1:]
def alive(pid):
 try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
 except FileNotFoundError:return False
def save():p.write_text(json.dumps(s))
def row(unit):
 v=s['units'].get(unit)
 if v is None:return dict(LoadState='not-found')
 live=[pid for pid in v['pids'] if alive(pid)]
 return dict(LoadState='loaded',ActiveState='active' if live and not v.get('lie') else 'inactive',
  SubState='running' if live else 'dead',MainPID=str(v['pids'][0]) if live and alive(v['pids'][0]) and not v.get('lie') else '0',
  ControlPID='0',TasksCurrent='[not set]' if v.get('no_accounting') else str(len(live)),
  ControlGroup='/fixture/'+unit if live else '',Restart=v.get('restart','on-failure'),RestartForceExitStatus='',Type='simple')
if args[0]=='show':
 for k,v in row(args[1]).items():print(k+'='+v)
 sys.exit(0)
unit=args[-1];s['calls'].append(args)
if args[0]=='kill':
 assert unit=='usb-storage-watch-broker.service' and '--signal=SIGTERM' in args
 os.kill(s['units'][unit]['pids'][0],signal.SIGTERM)
elif args[0]=='stop':
 # Reproduce the old listener-stop/supervisor-start conflict. Quiescing the
 # real fixture supervisor process removes this source of canceled stops.
 if unit=='usb-storage-watch-lan.service' and (row('usb-storage-watch-broker.service').get('ActiveState')=='active' or s.pop('cancel_once',False)):
  save();print('Job for '+unit+' canceled.',file=sys.stderr);sys.exit(1)
 for pid in s['units'].get(unit,{}).get('pids',[]):
  if alive(pid) and pid!=s.get('retain_worker'):os.kill(pid,signal.SIGTERM)
 if unit in s['units'] and s.get('retain_worker') in s['units'][unit]['pids']:s['units'][unit]['lie']=True
else:raise AssertionError('Unexpected fixture systemctl: '+repr(args))
save()
'''


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.state = self.root/'state'; self.state.mkdir()
        self.payload = self.root/'old-payload'; self.payload.mkdir()
        self.fake = self.root/'systemctl'; self.fake.write_text(SYSTEMCTL); self.fake.chmod(0o700)
        self.broker = 'usb-storage-watch-broker.service'; self.web = 'usb-storage-watch-web.service'; self.lan = 'usb-storage-watch-lan.service'
        self.children = []
        units = {}
        for unit, count in ((self.broker, 1), (self.web, 2), (self.lan, 2)):
            pids = []
            for _ in range(count):
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
                self.children.append(child); pids.append(child.pid)
            units[unit] = dict(pids=pids, enabled=True)
        self.addCleanup(self.cleanup)
        self.data = self.root/'systemd.json'; self.data.write_text(json.dumps(dict(units=units, calls=[])))
        self.receipt = self.state/'web-was-active.json'
        (self.payload/'maintenance.py').write_text(
            "import sys\nfrom pathlib import Path\nassert sys.argv[1]=='prepare-upgrade'\n"
            f"p=Path({str(self.root/'guard')!r});p.write_text(p.read_text()+'guard\\n' if p.exists() else 'guard\\n')\n"
            f"assert not Path({str(self.root/'refuse')!r}).exists(),'Existing maintenance guard refused'\n")
        (self.payload/'web_install.py').write_text(
            "import subprocess,json\nfrom pathlib import Path\n"
            f"Path({str(self.receipt)!r}).write_text(json.dumps({list(units)!r}))\n"
            f"subprocess.run([{str(self.fake)!r},'stop',{self.lan!r}],check=True)\n")
        builder = load('ui40_builder', ROOT/'tools/build.py')
        self.script = builder.maintainer_script('prerm')
        self.assertIn((ROOT/'src/usb_storage_watch/web_lifecycle.py').read_text(), self.script)

    def cleanup(self):
        for child in self.children:
            if child.poll() is None: child.terminate()
        for child in self.children: child.wait(timeout=3)

    def change(self, **values):
        data = json.loads(self.data.read_text()); data.update(values); self.data.write_text(json.dumps(data))

    def run_script(self, action='upgrade', script=None):
        text = script or self.script
        text = text.replace('/usr/lib/usb-storage-watch', str(self.payload))
        text = text.replace("Path('/var/lib/usb-storage-watch')", repr(self.state).replace('PosixPath', 'Path'))
        text = text.replace("Path('/run/systemd/system').is_dir()", 'True')
        text = text.replace('os.geteuid() != 0', 'False')
        text = text.replace("'/usr/bin/systemctl'", repr(str(self.fake)))
        text = text.replace('WAIT = 40', 'WAIT = .5')
        env = dict(os.environ); env.pop('DPKG_ROOT', None)
        return subprocess.run(['/bin/sh', '-s', '--', action], input=text, text=True,
                              capture_output=True, env=env, timeout=15)

    def assert_stopped(self):
        for child in self.children: self.assertIsNotNone(child.poll())

    def test_normal_upgrade_quiesces_before_listener_and_workers_exit(self):
        result = self.run_script(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('workers stopped', result.stdout); self.assert_stopped()
        data = json.loads(self.data.read_text())
        calls = data['calls']; self.assertEqual(calls[0][0], 'kill')
        self.assertEqual(calls[0][-1], self.broker)
        self.assertEqual(json.loads(self.receipt.read_text()), [self.broker, self.web, self.lan])
        self.assertTrue(all(v['enabled'] for v in data['units'].values()))

    def test_old_canceled_stop_then_new_failed_upgrade_before_unpack(self):
        old = '''#!/bin/sh
set -eu
/usr/bin/python3 -I /usr/lib/usb-storage-watch/maintenance.py prepare-upgrade
/usr/bin/python3 -I /usr/lib/usb-storage-watch/web_install.py prepare-upgrade
'''
        result = self.run_script(script=old)
        self.assertNotEqual(result.returncode, 0); self.assertIn('canceled', result.stderr)
        self.assertTrue(all(child.poll() is None for child in self.children))
        receipt = self.receipt.read_bytes()
        result = self.run_script('failed-upgrade')
        self.assertEqual(result.returncode, 0, result.stderr); self.assert_stopped()
        self.assertEqual(self.receipt.read_bytes(), receipt)
        self.assertEqual((self.root/'guard').read_text(), 'guard\nguard\n')

    def test_canceled_stop_fails_then_repeat_preserves_original_intent(self):
        self.change(cancel_once=True)
        result = self.run_script(); self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('workers stopped', result.stdout)
        receipt = self.receipt.read_bytes()
        result = self.run_script('failed-upgrade'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_stopped(); self.assertEqual(self.receipt.read_bytes(), receipt)
        result = self.run_script(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.receipt.read_bytes(), receipt)

    def test_surviving_worker_refuses_even_if_main_pid_and_state_claim_stopped(self):
        self.change(retain_worker=self.children[-1].pid)
        result = self.run_script(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('workers; preparation refused', result.stderr)
        self.assertIsNone(self.children[-1].poll())
        self.assertNotIn('workers stopped', result.stdout)

    def test_existing_maintenance_guard_is_not_bypassed_by_fallback(self):
        (self.root/'refuse').touch()
        result = self.run_script('failed-upgrade'); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.data.read_text())['calls'], [])
        self.assertTrue(all(child.poll() is None for child in self.children))

    def test_unknown_worker_count_does_not_authorize_success_with_retained_cgroup(self):
        data=json.loads(self.data.read_text());data['units'][self.lan]['no_accounting']=True
        data['retain_worker']=self.children[-1].pid;self.data.write_text(json.dumps(data))
        result=self.run_script();self.assertNotEqual(result.returncode,0)
        self.assertIn('workers; preparation refused',result.stderr)
        self.assertIsNone(self.children[-1].poll())

    def test_incompatible_restart_override_refuses_before_signaling(self):
        data = json.loads(self.data.read_text()); data['units'][self.broker]['restart'] = 'always'
        self.data.write_text(json.dumps(data))
        result = self.run_script(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('overrides prevent safe', result.stderr)
        self.assertEqual(json.loads(self.data.read_text())['calls'], [])

    def test_disabled_listener_is_not_added_to_restart_intent(self):
        for child in self.children[-2:]: child.terminate(); child.wait(timeout=3)
        data = json.loads(self.data.read_text()); data['units'][self.lan]['enabled'] = False
        self.data.write_text(json.dumps(data))
        result = self.run_script(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.receipt.read_text()), [self.broker, self.web])
        self.assertFalse(json.loads(self.data.read_text())['units'][self.lan]['enabled'])

    def test_dpkg_root_does_not_touch_host(self):
        result = subprocess.run(['/bin/sh', '-s', '--', 'failed-upgrade'], input=self.script,
                                env=dict(os.environ, DPKG_ROOT=str(self.root)), text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0); self.assertFalse((self.root/'guard').exists())


if __name__ == '__main__': unittest.main()
