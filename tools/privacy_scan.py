#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Audit allowlisted source and unpacked artifacts; never print matching values."""
import sys
sys.dont_write_bytecode = True
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
EMAIL=re.compile(r'[A-Za-z0-9_.+%-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})')
UUID=re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',re.I)
PATTERNS=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'\bAKIA[0-9A-Z]{16}\b',
          r'\bgh[pousr]_[A-Za-z0-9]{30,}\b',r'/home/[A-Za-z0-9_.-]+/',
          r'"password"\s*:\s*"(?!"|DUMMY-TEST-SECRET")[^"]+"']
RESERVED={'example.test','example.invalid','example.com','usb-storage-notify.local'}
SYNTHETIC_UUIDS={'11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222','33333333-3333-4333-8333-333333333333'}
GZIP_DOCUMENTS={'usr/share/doc/usb-storage-watch/changelog.gz',
                'usr/share/man/man8/usb-storage-watch.8.gz'}
VENDOR_LOCK=json.loads((ROOT/'tools/vendor-lock.json').read_text())['files']
# Visually reviewed blank login page: no account, host, disk or incident data.
# Any replacement must be reviewed again; arbitrary PNGs remain forbidden.
SCREENSHOTS={'docs/GUI-LOGIN.png':'a03a550f8dc4703d19dc81df89151574db6670276f68bb7204eb4f7469768b1a'}


def audit(label,data,denied,failures,compressed=False):
    if label.endswith('/companion/module.tgz'):
        pinned=json.loads((ROOT/'src/usb_storage_watch/companion/module.json').read_text())
        if hashlib.sha256(data).hexdigest()!=pinned['sha256']:
            failures.append((label,'unreviewed Companion archive'));return
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            members=archive.getmembers()
            expected={'usb-storage-watch/main.js','usb-storage-watch/package.json','usb-storage-watch/LICENSE',
                      'usb-storage-watch/companion/manifest.json','usb-storage-watch/companion/HELP.md'}
            directories={'usb-storage-watch','usb-storage-watch/companion'}
            if any(not m.isfile() and (not m.isdir() or m.name.rstrip('/') not in directories) for m in members):
                failures.append((label,'unsafe Companion directory'));return
            members=[m for m in members if m.isfile()]
            if {m.name for m in members}!=expected or len(members)!=len(expected):
                failures.append((label,'unexpected Companion package members'));return
            for member in members:
                if not member.isfile() or member.size>5*1024*1024:
                    failures.append((label,'unsafe Companion member'));return
                audit(label+':'+member.name,archive.extractfile(member).read(),denied,failures)
        return
    for path, checksum in SCREENSHOTS.items():
        if label == path or label.endswith('/' + path):
            if hashlib.sha256(data).hexdigest() != checksum:
                failures.append((label,'unreviewed screenshot bytes'))
            return
    # Upstream copyright/contact and example text is public, not user data.
    # Permit it only when the entire file matches the reviewed upstream bytes;
    # private-origin checks still apply. No other vendor path is exempted.
    if '/_vendor/' in label:
        relative=label.split('/_vendor/',1)[1]
        if VENDOR_LOCK.get(relative)!=hashlib.sha256(data).hexdigest():
            failures.append((label,'upstream checksum mismatch'));return
        try: upstream=data.decode('utf-8')
        except UnicodeError: failures.append((label,'unexpected binary upstream file'));return
        if any(value and value in upstream for value in denied):failures.append((label,'private origin value'))
        return
    if label.endswith('usr/share/doc/usb-storage-watch/copyright'):
        own_notices=(ROOT/'LICENSE').read_bytes()+b'\n'+(ROOT/'THIRD-PARTY-NOTICES.md').read_bytes()
        expected=own_notices+b'\nBundled Gunicorn 26.2.0:\n\n'+(ROOT/'src/usb_storage_watch/_vendor/gunicorn-LICENSE').read_bytes()
        if data==expected:
            if any(value and value.encode() in data for value in denied):failures.append((label,'private origin value'))
            data=own_notices
    if compressed:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data=stream.read(1024*1024+1)
        except (OSError, EOFError):
            failures.append((label,'invalid compressed documentation'));return
        if len(data)>1024*1024:
            failures.append((label,'compressed documentation exceeds audit limit'));return
    try:text=data.decode('utf-8')
    except UnicodeError:failures.append((label,'unexpected binary payload'));return
    if '\x00' in text:failures.append((label,'NUL/binary payload'))
    for p in PATTERNS:
        if re.search(p,text):failures.append((label,'secret/private pattern'))
    for match in EMAIL.finditer(text):
        if match[1].lower() not in RESERVED:failures.append((label,'non-example email address'))
    for match in UUID.finditer(text):
        if match[0].lower() not in SYNTHETIC_UUIDS:failures.append((label,'non-synthetic literal UUID'))
    if any(value and value in text for value in denied):failures.append((label,'private origin value'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--deny-file',type=Path,help='Optional PRIVATE JSON list, kept outside the source tree')
    args=parser.parse_args();denied=[]
    if args.deny_file:
        if args.deny_file.resolve().is_relative_to(ROOT):raise ValueError('Private denylist must remain outside the distribution')
        denied=json.loads(args.deny_file.read_text());assert isinstance(denied,list) and all(isinstance(x,str) for x in denied)
    spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    failures=[];count=0
    for p in builder.source_files():audit(str(p.relative_to(ROOT)),p.read_bytes(),denied,failures);count+=1
    for p in (ROOT/'dist').glob('*.tar.gz'):
        with tarfile.open(p) as archive:
            for member in archive.getmembers():
                if not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:raise ValueError('Unsafe archive member')
                audit(p.name+':'+member.name,archive.extractfile(member).read(),denied,failures);count+=1
    for p in (ROOT/'dist').glob('*.deb'):
        with tempfile.TemporaryDirectory(prefix='usw-privacy-') as temporary:
            subprocess.run(['dpkg-deb','--raw-extract',str(p),temporary],check=True,timeout=30,stdout=subprocess.DEVNULL)
            for entry in Path(temporary).rglob('*'):
                if entry.is_symlink():raise ValueError('Unexpected package symlink')
                if entry.is_file():
                    relative=str(entry.relative_to(temporary))
                    audit(p.name+':'+relative,entry.read_bytes(),denied,failures,compressed=relative in GZIP_DOCUMENTS);count+=1
    config=json.loads((ROOT/'examples/config.json').read_text())
    assert not any((config['recovery']['mount'],config['usb']['enabled'],config['docker']['enabled']))
    assert not config['disk']['uuid'] and config['usb']['profile'] is None and not config['docker']['containers']
    assert not json.loads((ROOT/'examples/smtp.example.json').read_text())['password']
    if failures:
        for label,reason in sorted(set(failures)):print('FAIL '+label+': '+reason+' (value withheld)')
        raise SystemExit(1)
    print(f'PASS privacy audit: {count} source/package files; example-only identities, no matched secrets/private values; all actions off by default.')

if __name__=='__main__':main()
