"""Opt-in disposable loop mounts + verified loopback SMTP TLS setup sequence.

Run only as root in a separate private mount namespace with --disposable-mounts.
Creates its own temporary /mnt directory and files; never uses a physical disk.
PAM, USB discovery, systemd and Docker are simulated; mounts/probes/TLS are real.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading
from types import FunctionType
import unittest
from unittest.mock import Mock,patch
from gui_fixture import Machine,UUID,load
from test_beta3_setup import SetupFixture,SMTP,IMAGE_UUID

def run(argv):
    return subprocess.run(argv,check=True,capture_output=True,text=True,timeout=20).stdout

class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(8);self.wfile.write(b'220 isolated SMTP fixture\r\n')
        while True:
            line=self.rfile.readline(8192)
            if not line:return
            verb=line.split(b' ',1)[0].strip().upper()
            if verb==b'EHLO':reply=b'250-fixture\r\n250 AUTH PLAIN\r\n'
            elif verb==b'AUTH':reply=b'235 Accepted synthetic credentials\r\n'
            elif verb in (b'MAIL',b'RCPT'):reply=b'250 OK\r\n'
            elif verb==b'DATA':
                self.wfile.write(b'354 End with dot\r\n')
                total=0
                while True:
                    data=self.rfile.readline(8192)
                    if data==b'.\r\n':break
                    if not data or total>65536:raise ValueError('Fixture DATA limit')
                    total+=len(data)
                self.server.accepted+=1;reply=b'250 Message accepted in memory\r\n'
            elif verb==b'QUIT':self.wfile.write(b'221 Bye\r\n');return
            else:raise ValueError('Unexpected SMTP fixture command')
            self.wfile.write(reply)

class RealSetup(SetupFixture,unittest.TestCase):
    def setUp(self):
        self.base=Path(tempfile.mkdtemp(prefix='usw-beta3-',dir='/mnt'));self.mounts=[]
        self.addCleanup(self.cleanup_storage)
        private=self.base/'private';private.mkdir(mode=0o700)
        self.m=Machine(root=private);self.addCleanup(self.m.close)
        self.b=self.m.b;self.w=self.b.w;self.root=self.m.root
        self.m.patch(self.b.cli,'root_path',lambda root,path:Path(path))
        self.disk=self.base/'disk';self.disk.mkdir()
        main=self.base/'physical.img'
        with main.open('wb') as f:f.truncate(160*1024**2)
        run(['/usr/sbin/mkfs.ext4','-q','-F','-U',UUID,str(main)])
        run(['/usr/bin/mount','-t','ext4','-o','loop,noatime,nodev,nosuid,noexec','--',str(main),str(self.disk)])
        self.mounts.append(self.disk)
        self.file=self.disk/'backup.img'
        with self.file.open('wb') as f:f.truncate(32*1024**2)
        run(['/usr/sbin/mkfs.ext4','-q','-F','-U',IMAGE_UUID,str(self.file)])
        self.target=self.disk/'ftp'/'files';self.target.mkdir(parents=True)
        run(['/usr/bin/mount','-t','ext4','-o','loop,noatime,nodev,nosuid,noexec','--',str(self.file),str(self.target)])
        self.mounts.append(self.target);self.target.chmod(0o750)
        (self.target/'existing-file').write_bytes(b'Disposable existing FTP contents')
        run(['/usr/bin/sync','-f',str(self.target)]);run(['/usr/bin/sync','-f',str(self.disk)])
        self.dev=self.number(self.disk.stat().st_dev);loopdev=self.number(self.target.stat().st_dev)
        self.m.current=str(self.disk);self.m.dev=self.dev
        self.options='loop,defaults,nofail,noatime,x-systemd.requires-mounts-for='+str(self.disk)
        self.entry=f'{self.file} {self.target} ext4 {self.options} 0 0\n'
        self.m.fstab.write_text(f'# Isolated fixture fstab\nUUID={UUID} {self.disk} ext4 defaults 0 2\n'+self.entry)
        raw=load('engine')
        for name in ('read_rows','device_number','block_checks','disk_proof','safe_path','fstab_check','protected_mount_directory','loop_inventory'):
            fn=getattr(raw,name)
            self.m.patch(self.w,name,FunctionType(fn.__code__,vars(self.w),name,fn.__defaults__))
        # Private UUID symlink avoids adding/changing host udev rules or /dev links.
        links=self.root/'by-uuid';links.mkdir();(links/UUID).symlink_to(Path('/dev/block',self.dev).resolve())
        self.m.patch(self.w,'Path',lambda p:self.m.fstab if str(p)=='/etc/fstab' else links if str(p)=='/dev/disk/by-uuid' else Path(p))
        nodes={self.dev:Path('/dev/block',self.dev).resolve(),loopdev:Path('/dev/block',loopdev).resolve()}
        def udev(dev):
            assert dev in nodes
            fields=dict(line.split('=',1) for line in run(['/usr/sbin/blkid','-p','-o','export',str(nodes[dev])]).splitlines() if '=' in line)
            return dict(ID_FS_UUID=fields['UUID'],ID_FS_TYPE=fields['TYPE'])
        self.m.patch(self.w,'udev',udev)
        self.m.patch(self.w,'assert_internal_state',Mock())
        self.m.patch(self.w,'recover_image',Mock(side_effect=AssertionError('Setup cannot remount')))
        self.m.patch(self.m,'mount_rows',self.w.read_rows)
        self.rows=self.w.read_rows()
        self.config=self.b.s.default();self.config['disk'].update(uuid=UUID,mountpoint=str(self.disk),fstab_options='defaults')
        self.b.cli.save(self.b.s.CONFIG,self.config);self.w.configure(self.config)
        self.data=dict(mode='existing',name='Existing backups',image=str(self.file))
        self.session=self.m.broker.sessions.login('admin','synthetic');self.ctx=self.b.protection_context()
        notifier=load('notify');notifier.CONFIG=self.b.s.SMTP
        self.m.patch(self.b.n,'load_config',notifier.load_config)
        # Synthetic SMTP endpoint; real certificate and hostname verification.
        cert=self.root/'smtp.pem';key=self.root/'smtp.key'
        run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-subj','/CN=localhost',
             '-addext','subjectAltName=IP:127.0.0.1','-addext','basicConstraints=critical,CA:TRUE',
             '-keyout',str(key),'-out',str(cert),'-days','1'])
        server=socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPHandler);server.daemon_threads=True;server.accepted=0
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
        server.socket=tls.wrap_socket(server.socket,server_side=True)
        threading.Thread(target=server.serve_forever,daemon=True).start();self.server=server
        self.addCleanup(lambda:(server.shutdown(),server.server_close()))
        context=ssl.create_default_context(cafile=str(cert))
        def send(payload):
            with patch.object(notifier.ssl,'create_default_context',return_value=context):
                notifier.smtp_send(notifier.load_config(),payload)
            return True,'SMTP accepted by the isolated certificate-verified TLS fixture.'
        self.m.patch(self.b.n,'bounded_send',send)
        self.smtp=copy.deepcopy(SMTP);self.smtp.update(host='127.0.0.1',port=server.server_address[1],security='tls')

    @staticmethod
    def number(dev):return f'{os.major(dev)}:{os.minor(dev)}'

    def request(self,action,data=None,csrf=True):
        if action=='smtp':data=self.smtp
        return super().request(action,data,csrf)

    def cleanup_storage(self):
        # Ordinary unmount only, exactly the two paths this fixture created.
        for target in reversed(self.mounts):
            run(['/usr/bin/umount','--',str(target)])
        shutil.rmtree(self.base)

    def test_complete_sequence_real_mounts_and_smtp_tls(self):
        self.run_sequence();self.assertEqual(self.server.accepted,1)
        # Insecure saved file is a real permission-policy refusal, not a mocked exception.
        self.b.s.SMTP.chmod(0o644);before=self.b.s.CONFIG.read_bytes();calls=len(self.m.calls)
        refused=self.notification();self.assertEqual(refused['status'],400,refused)
        self.assertIn('cannot be read safely',refused['error'])
        self.assertEqual(self.b.s.CONFIG.read_bytes(),before);self.assertEqual(len(self.m.calls),calls)
        self.assertTrue(self.m.active)
        self.b.s.SMTP.chmod(0o600)
        with self.assertRaises(self.w.Unsafe):self.w.recovery_backing(self.w.read_rows(),str(self.disk),self.dev,mounted=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--disposable-mounts',action='store_true',required=True);parser.parse_args()
    assert os.geteuid()==0 and os.readlink('/proc/self/ns/mnt')!=os.readlink('/proc/1/ns/mnt'),'Use sudo -n unshare --mount --propagation private'
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RealSetup))
    raise SystemExit(not result.wasSuccessful())
