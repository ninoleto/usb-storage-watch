#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Private-root package tests. No host service/device/Docker/SMTP operations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import copy
sys.dont_write_bytecode = True
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DEB=ROOT/'dist/usb-storage-watch_2.0.1-beta6_all.deb'
TAR=ROOT/'dist/usb-storage-watch-2.0.1-beta6.tar.gz'
CHECKS=[]


def run(argv,timeout=45,env=None):
    p=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=timeout,env=env)
    if p.returncode: raise RuntimeError('Private test command failed: '+str(argv[0])+'\n'+p.stdout+p.stderr)
    return p.stdout


def passed(name):
    CHECKS.append(name);print('PASS '+name)


def seed(root):
    cfg=root/'etc/usb-storage-watch';cfg.mkdir(mode=0o700,parents=True,exist_ok=True)
    state=root/'var/lib/usb-storage-watch';state.mkdir(mode=0o700,parents=True,exist_ok=True)
    c=json.loads((ROOT/'examples/config.json').read_text());c['disk']['uuid']='11111111-1111-4111-8111-111111111111'
    (cfg/'config.json').write_text(json.dumps(c));(cfg/'smtp.json').write_text('{"test":"SYNTHETIC-CREDENTIAL-PRESERVATION"}')
    (state/'history.fixture').write_text('SYNTHETIC-DELIVERY-HISTORY')
    for p in cfg.iterdir():p.chmod(0o600)
    # Profile data, separate integration tokens and backing-image sentinels are
    # application state, never package payload. Upgrades/removal preserve bytes.
    identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'synthetic-drive-profile-b'))
    childcfg=cfg/'drives'/identifier;childcfg.mkdir(mode=0o700,parents=True)
    childstate=state/'drives'/identifier;childstate.mkdir(mode=0o700,parents=True)
    other=copy.deepcopy(c);other['disk'].update(uuid=str(uuid.uuid5(uuid.NAMESPACE_URL,'synthetic-drive-b')),mountpoint='/mnt/secondary',label='Second fixture drive')
    for index,value in enumerate((c,other)):
        mount=value['disk']['mountpoint'];value['images']=[]
        for number in (1,2):
            value['images'].append(dict(name='Fixture '+str(number),enabled=True,
                uuid=str(uuid.uuid5(uuid.NAMESPACE_URL,f'synthetic-image-{index}-{number}')),
                image=mount+'/volumes/'+str(number)+'.img',mountpoint=mount+'/spaces/'+str(number),
                fstab_options='loop,nofail,nodev,nosuid'))
    (cfg/'config.json').write_text(json.dumps(c));(childcfg/'config.json').write_text(json.dumps(other))
    for directory in (cfg,childcfg):
        (directory/'companion-api.json').write_text('{"fixture":"SYNTHETIC-SEPARATE-INTEGRATION-TOKEN"}')
        (directory/'standby-api.json').write_text('{"fixture":"SYNTHETIC-LEGACY-STANDBY-TOKEN"}')
    (state/'management.token').write_text('SYNTHETIC-RETRIEVABLE-MANAGEMENT-CREDENTIAL')
    (childstate/'state.json').write_text('{"fixture":"SECOND-INDEPENDENT-INCIDENT"}')
    (childstate/'history.fixture').write_text('SECOND-DRIVE-HISTORY')
    (childstate/'backing-image.fixture').write_bytes(b'Existing virtual image data sentinel')
    paths=[p for directory in (cfg,state) for p in directory.rglob('*') if p.is_file() and p.name!='install-manifest.json' and 'backups' not in p.parts]
    for p in paths:p.chmod(0o600)
    return {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def unchanged(snapshot):
    assert all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in snapshot.items())


def main():
    assert DEB.is_file() and TAR.is_file(),'Run tools/build.py first'
    assert int(run(['dpkg-deb','--field',DEB,'Installed-Size']).strip()) > 0
    with tempfile.TemporaryDirectory(prefix='usw-isolated-') as tmp:
        base=Path(tmp)
        # Extraction is safe even on Python versions lacking tar filter=.
        source=base/'source';source.mkdir()
        with tarfile.open(TAR) as archive:
            for entry in archive.getmembers():
                assert entry.isfile() and not Path(entry.name).is_absolute() and '..' not in Path(entry.name).parts
                assert entry.uid==entry.gid==0
                out=source/entry.name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(archive.extractfile(entry).read())
        project=source/'usb-storage-watch-2.0.1-beta6'
        passed('portable archive contains only regular safe paths with normalized ownership')
        portable=base/'portable';portable.mkdir()
        tool=project/'tools/install.py'
        # Exercise callers with a permissive umask without changing this process.
        run([sys.executable,'-I','-c',
             'import os,runpy,sys; os.umask(0); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name="__main__")',
             tool,'--root',portable])
        assert not (portable/'etc/usb-storage-watch/config.json').exists()
        assert not (portable/'etc/systemd/system/multi-user.target.wants').exists()
        for p in (portable/'usr').rglob('*'):
            assert not p.stat().st_mode & 0o022, 'Program path is group/world writable'
        passed('portable first install stages code and never configures/enables a service')
        snapshot=seed(portable)
        run([sys.executable,'-I',tool,'--root',portable]);unchanged(snapshot)
        assert list((portable/'var/lib/usb-storage-watch/backups').iterdir())
        passed('portable upgrade preserves configuration, synthetic credentials and history; backs up program')
        cli=portable/'usr/lib/usb-storage-watch/cli.py'
        assert '2.0.1~beta6' in run([sys.executable,'-I',cli,'--version'])
        for command in ('validate','diagnose'): run([sys.executable,'-I',cli,'--root',portable,command])
        passed('installed CLI version, staged validation and staged diagnostics')
        bad=base/'symlink-root';bad.mkdir();(bad/'usr').symlink_to(base/'external')
        p=subprocess.run([sys.executable,'-I',str(tool),'--root',str(bad)],capture_output=True,timeout=20)
        assert p.returncode and not (base/'external').exists()
        passed('portable symlink escape refused')
        ledger=portable/'var/lib/usb-storage-watch/usb-reset.json';ledger.write_text('{"phase":"enable_failed"}')
        p=subprocess.run([sys.executable,'-I',str(tool),'--root',str(portable),'--uninstall'],capture_output=True,timeout=20)
        assert p.returncode and cli.exists();ledger.unlink()
        passed('uninstall refuses unresolved USB enable obligation')
        run([sys.executable,'-I',tool,'--root',portable,'--uninstall']);unchanged(snapshot);assert not cli.exists()
        passed('portable removal retains private configuration and delivery/history data')
        # Separate dpkg root/database/log; no host package database writes.
        debroot=base/'debian';admin=debroot/'var/lib/dpkg';admin.mkdir(parents=True)
        (admin/'status').touch()
        dpkg=(['fakeroot'] if os.geteuid() else [])+['dpkg','--path-include=/usr/share/doc/usb-storage-watch/*',
              '--path-include=/usr/share/man/*','--root='+str(debroot),'--admindir='+str(admin),'--log='+str(base/'dpkg.log'),
              '--force-not-root','--force-script-chrootless','--force-depends']
        env=dict(os.environ);env['DPKG_ROOT']=str(debroot);env['FAKEROOTDONTTRYCHOWN']='1'
        # Verify each script's explicit staged-root exit before dpkg execution.
        control=base/'control';run(['dpkg-deb','--control',DEB,control])
        for script,arg in [('preinst','upgrade'),('postinst','configure'),('prerm','remove'),('postrm','purge')]:
            run(['/bin/sh',control/script,arg],env=env)
        passed('all Debian maintainer scripts exit before host actions with DPKG_ROOT')
        run([*dpkg,'--install',DEB],env=env)
        assert (debroot/'usr/lib/usb-storage-watch/engine.py').exists()
        assert all(not p.stat().st_mode & 0o022 for p in (debroot/'usr').rglob('*'))
        for name in ('copyright','changelog.gz'):
            assert (debroot/'usr/share/doc/usb-storage-watch'/name).is_file()
        assert (debroot/'usr/share/man/man8/usb-storage-watch.8.gz').is_file()
        assert not (debroot/'etc/usb-storage-watch/config.json').exists()
        snapshot=seed(debroot)
        passed('Debian package installs in private dpkg root with no automatic activation')
        # Build a private next-version archive to exercise dpkg upgrade semantics.
        nexttree=base/'next';run(['dpkg-deb','--raw-extract',DEB,nexttree])
        controlfile=nexttree/'DEBIAN/control';controlfile.write_text(controlfile.read_text().replace('Version: 2.0.1~beta6','Version: 2.0.1~beta6+test1'))
        upgrade=base/'private-upgrade.deb';run(['dpkg-deb','--root-owner-group','--build',nexttree,upgrade])
        run([*dpkg,'--install',upgrade],env=env);unchanged(snapshot)
        assert 'Version: 2.0.1~beta6+test1' in (admin/'status').read_text()
        passed('Debian version upgrade preserves configuration, synthetic credentials and history')
        run([*dpkg,'--remove','usb-storage-watch'],env=env);unchanged(snapshot)
        assert not (debroot/'usr/lib/usb-storage-watch/engine.py').exists()
        run([*dpkg,'--purge','usb-storage-watch'],env=env);unchanged(snapshot)
        passed('Debian remove and purge preserve generated configuration and persistent state')
        # Static unit validation in a private synthetic systemd root; no boot/start.
        unitroot=base/'unit-root';units=unitroot/'usr/lib/systemd/system';units.mkdir(parents=True)
        for source_unit in (ROOT/'packaging').glob('usb-storage-watch*.service'):
            shutil.copyfile(source_unit,units/source_unit.name)
        for source_unit in (ROOT/'packaging').glob('usb-storage-watch*.timer'):
            shutil.copyfile(source_unit,units/source_unit.name)
        for name in ('sysinit.target','basic.target','shutdown.target','local-fs.target','network.target','umount.target','multi-user.target','timers.target'):
            (units/name).write_text('[Unit]\nDescription=Isolated validation fixture\nDefaultDependencies=no\n')
        binary=unitroot/'usr/bin/python3';binary.parent.mkdir(parents=True);binary.write_text('#!/bin/sh\nexit 99\n');binary.chmod(0o755)
        run(['systemd-analyze','--root='+str(unitroot),'verify','--man=no','usb-storage-watch.service','usb-storage-watch@'+'33333333-3333-4333-8333-333333333333'+'.service',
             'usb-storage-watch-broker.service','usb-storage-watch-web.service','usb-storage-watch-lan.service',
             'usb-storage-watch-boot.service','usb-storage-watch-boot.timer',
             'usb-storage-watch-network-test@'+'local.service','usb-storage-watch-network-test@'+'lan.service'])
        passed('legacy, per-drive, boot service/timer, web, broker, LAN and temporary network units validate without starting services')
        # Packaged source is self-contained: run its simulated tests from extraction.
        if '--smoke-only' not in sys.argv:
            run([sys.executable,'-B','-I','-m','unittest','discover','-s',project/'tests'],timeout=90)
            passed('complete simulation suite passes from extracted portable archive')
        else:
            print('SKIP full source test suite in smoke-only mode; run it on a host with all Python/Flask dependencies installed.')
    print(f'{len(CHECKS)} isolated lifecycle checks passed. No booted VM or hardware reset was tested.')

if __name__=='__main__':main()
