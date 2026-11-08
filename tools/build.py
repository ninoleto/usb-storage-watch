#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Build deterministic, allowlisted source/portable archive and architecture-all deb."""
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import gzip
import json

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_settings',ROOT/'src/usb_storage_watch/settings.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
VERSION=release.PACKAGE_VERSION
ASSET_VERSION=release.VERSION
EPOCH=1767225600
spec=importlib.util.spec_from_file_location('installer',ROOT/'tools/install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


def maintainer_script(name):
    text=(ROOT/'packaging'/name).read_text()
    if name=='control':
        if text.count('@VERSION@')!=1: raise ValueError('Missing package version marker')
        text=text.replace('@VERSION@',VERSION)
    if name=='prerm':
        if text.count('@WEB_LIFECYCLE@')!=1: raise ValueError('Missing lifecycle embedding marker')
        text=text.replace('@WEB_LIFECYCLE@',(ROOT/'src/usb_storage_watch/web_lifecycle.py').read_text())
    return text


def source_files():
    roots=('src','tools','tests','docs','examples','packaging')
    for name in ('README.md','AGENTS.md','LICENSE','THIRD-PARTY-NOTICES.md','CHANGELOG.md','.gitignore','Makefile'):
        yield ROOT/name
    for name in roots:
        for p in sorted((ROOT/name).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.log'):
                if p.is_symlink(): raise ValueError('Symlink in source')
                yield p


def main():
    vendor=ROOT/'src/usb_storage_watch/_vendor'
    locked=json.loads((ROOT/'tools/vendor-lock.json').read_text())['files']
    actual={str(p.relative_to(vendor)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in vendor.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    if actual!=locked: raise ValueError('Bundled upstream sources differ from their reviewed checksum manifest')
    os.environ['SOURCE_DATE_EPOCH']=str(EPOCH)
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='usw-build-') as temporary:
        tree=Path(temporary)/'deb';tree.mkdir()
        for relative,source in installer.payload().items():
            dest=tree/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);dest.chmod(0o755 if relative=='usr/sbin/usb-storage-watch' else 0o644)
        control=tree/'DEBIAN';control.mkdir()
        for name in ('control','preinst','postinst','prerm','postrm'):
            dest=control/name;dest.write_text(maintainer_script(name));dest.chmod(0o644 if name=='control' else 0o755)
        (control/'conffiles').write_text('/etc/pam.d/usb-storage-watch-web\n')
        (control/'conffiles').chmod(0o644)
        doc=tree/'usr/share/doc/usb-storage-watch'
        (doc/'copyright').write_text((ROOT/'LICENSE').read_text()+'\n'+(ROOT/'THIRD-PARTY-NOTICES.md').read_text()+'\nBundled Gunicorn 26.2.0:\n\n'+(vendor/'gunicorn-LICENSE').read_text())
        (doc/'copyright').chmod(0o644)
        for source, dest in ((ROOT/'packaging/changelog',doc/'changelog.gz'),
                             (ROOT/'packaging/usb-storage-watch.8',tree/'usr/share/man/man8/usb-storage-watch.8.gz')):
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(gzip.compress(source.read_bytes(),mtime=EPOCH))
            dest.chmod(0o644)
        # Directory permissions must not inherit the builder's umask.
        for p in [tree,*tree.rglob('*')]:
            if p.is_dir(): p.chmod(0o755)
        installed_size=sum((p.stat().st_size+1023)//1024 for p in tree.rglob('*')
                           if p.is_file() and 'DEBIAN' not in p.relative_to(tree).parts)
        controlfile=control/'control'
        controlfile.write_text(controlfile.read_text()+f'Installed-Size: {installed_size}\n')
        for p in tree.rglob('*'): os.utime(p,(EPOCH,EPOCH))
        os.utime(tree,(EPOCH,EPOCH))
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(tree),str(dist/f'usb-storage-watch_{ASSET_VERSION}_all.deb')],check=True,timeout=60)
    archive=dist/f'usb-storage-watch-{ASSET_VERSION}.tar.gz'
    with archive.open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=EPOCH) as zipped, tarfile.open(fileobj=zipped,mode='w') as tar:
        for p in source_files():
            info=tar.gettarinfo(str(p),arcname=f'usb-storage-watch-{ASSET_VERSION}/'+str(p.relative_to(ROOT)))
            info.uid=info.gid=0;info.uname=info.gname='root';info.mtime=EPOCH;info.mode=0o644
            with p.open('rb') as data: tar.addfile(info,data)
    companion=ROOT/'src/usb_storage_watch/companion'
    metadata=json.loads((companion/'module.json').read_text())
    module=dist/('usb-storage-watch-companion-'+metadata['version']+'.tgz')
    content=(companion/'module.tgz').read_bytes()
    if hashlib.sha256(content).hexdigest()!=metadata['sha256']:raise ValueError('Bundled Companion checksum mismatch')
    module.write_bytes(content)
    notes=dist/'RELEASE-NOTES.md'
    notes.write_bytes((ROOT/'docs/RELEASE-NOTES.md').read_bytes())
    artifacts=[dist/f'usb-storage-watch_{ASSET_VERSION}_all.deb',archive,module,notes]
    (dist/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts))
    print('Built Debian/source packages and copied verified Companion module; SHA256SUMS matches public filenames.')

if __name__=='__main__': main()
