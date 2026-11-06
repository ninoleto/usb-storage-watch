# SPDX-License-Identifier: MIT
"""Root-owned management credentials, local recovery and memory-only sessions."""
from collections import deque
import grp
import json
import stat
import hashlib
import os
import pwd
import re
import secrets
import time
import tempfile
import fcntl
from pathlib import Path
from contextlib import contextmanager


class Denied(ValueError):
    pass


def administrator(username):
    account=pwd.getpwnam(username)
    groups=os.getgrouplist(username,account.pw_gid)
    admins={g.gr_gid for g in grp.getgrall() if g.gr_name in ('sudo','wheel')}
    if account.pw_uid<=0 or not admins.intersection(groups):raise Denied('The management account is no longer a local administrator.')
    return account


def management_record(path):
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    except FileNotFoundError:return None
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode & 0o077:
            raise Denied('Management-token storage permissions need administrator review.')
        value=json.load(stream)
    if (not isinstance(value,dict) or value.get('version')!=1
            or not isinstance(value.get('sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',value['sha256'])
            or not isinstance(value.get('username'),str) or not 1<=len(value['username'])<=64
            or type(value.get('uid')) is not int or value['uid']<=0):
        raise Denied('Management-token storage is invalid. Recover access locally.')
    return value


# management.token is the single atomic credential record. Its opaque value
# includes the account UID and whether the DEV6 verifier is still accepted.
# Hash verification derives from that same read: plaintext and verifier cannot
# be split across generations by a crash between two file replacements.
PRIMARY = re.compile(r'usw7_([1-9][0-9]{0,9})_([tr])_([A-Za-z0-9_-]{43})')


def private_read(path):
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    except FileNotFoundError:return None
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            raise Denied('Management-token file permissions need local administrator review.')
        return stream.read(256)


def primary_record(state):
    if state is None:return None
    value=private_read(Path(state)/'management.token')
    if value is None:return None
    token=value.rstrip('\n');match=PRIMARY.fullmatch(token)
    if not match:raise Denied('Management-token file is invalid. Recover access locally.')
    return dict(uid=int(match[1]),transition=match[2]=='t',sha256=hashlib.sha256(token.encode('ascii')).hexdigest())


def management_configured(path,state=None):
    try:
        if primary_record(state):return True
        if state is not None and (Path(state)/'management-token-initialized').exists():return False
        return management_record(path) is not None
    except (OSError,ValueError,TypeError):return False


def management_transition(path,state):
    try:
        record=primary_record(state)
        return bool(record and record['transition'] and management_record(path))
    except (OSError,ValueError,TypeError):return False


def new_management_token(username):
    # DEV6 format remains readable and is also used by legacy upgrade fixtures.
    account=administrator(username);token='usw_'+secrets.token_urlsafe(32)
    return token,dict(version=1,username=username,uid=account.pw_uid,sha256=hashlib.sha256(token.encode('ascii')).hexdigest())


def verify_management_token(path,token,state=None):
    if not isinstance(token,str) or not (PRIMARY.fullmatch(token) or re.fullmatch(r'usw_[A-Za-z0-9_-]{43}',token)):
        raise Denied('Invalid management token.')
    try:
        primary=primary_record(state)
        digest=hashlib.sha256(token.encode('ascii')).hexdigest()
        if primary and secrets.compare_digest(primary['sha256'],digest):
            account=administrator(pwd.getpwuid(primary['uid']).pw_name)
            if account.pw_uid!=primary['uid']:raise Denied('Management account identity changed.')
            return account.pw_name
        if primary and not primary['transition']:raise Denied('Invalid management token.')
        if primary is None and state is not None and (Path(state)/'management-token-initialized').exists():
            raise Denied('Recover the management token locally.')
        record=management_record(path)
        if not record or not secrets.compare_digest(record['sha256'],digest):raise Denied('Invalid management token.')
        account=administrator(record['username'])
        if account.pw_uid!=record['uid']:raise Denied('The management account identity changed. Recover access locally.')
        return account.pw_name
    except (OSError,ValueError,KeyError,TypeError):
        raise Denied('Invalid management token or unavailable management account. Recover access locally if needed.') from None


@contextmanager
def token_lock(state):
    state=Path(state).absolute()
    if state.resolve()!=state:raise Denied('Management-token directory must not contain symlinks.')
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    if state.stat().st_uid!=os.geteuid():raise Denied('Management-token directory must be administrator-owned.')
    state.chmod(0o700)  # Directory only: never change existing child data/permissions.
    fd=os.open(state/'management-token.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:raise Denied('Invalid token lock.')
        os.fchmod(fd,0o600);fcntl.flock(fd,fcntl.LOCK_EX)
        yield state
    finally:os.close(fd)


def atomic_secret(path,value):
    fd,temporary=tempfile.mkstemp(prefix='.management-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            if os.geteuid()==0:os.fchown(stream.fileno(),0,0)  # Broker runs with a separate service group.
            os.fchmod(stream.fileno(),0o600);stream.write(value);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def write_management_token(state,username,transition=False):
    account=administrator(username)
    token='usw7_'+str(account.pw_uid)+('_t_' if transition else '_r_')+secrets.token_urlsafe(32)
    atomic_secret(state/'management.token',token+'\n')
    atomic_secret(state/'management-token-initialized','initialized\n')
    return token


def rotate_management_token(state,username):
    with token_lock(state) as directory:
        return write_management_token(directory,username)  # Retires all old hashes.


def installation_account(legacy):
    names=[]
    if legacy:names.append(legacy['username'])
    if os.environ.get('SUDO_USER'):names.append(os.environ['SUDO_USER'])
    try:
        if os.environ.get('PKEXEC_UID'):names.append(pwd.getpwuid(int(os.environ['PKEXEC_UID'])).pw_name)
    except (ValueError,KeyError):pass
    # Package-manager services may omit the invoking user. Use the first named
    # desktop administrator; it is shown as the account after login. Never root.
    names.extend(p.pw_name for p in sorted(pwd.getpwall(),key=lambda p:p.pw_uid) if 1000<=p.pw_uid<65534)
    for name in dict.fromkeys(names):
        try:return administrator(name).pw_name
        except (Denied,KeyError,OSError):pass
    raise Denied('A named local administrator account is required. Use local administrator recovery after creating one.')


def ensure_management_token(path,state):
    """Installation-only: preserve DEV6 credentials; never rotate existing DEV7."""
    with token_lock(state) as directory:
        try:record=primary_record(directory)
        except (OSError,ValueError,TypeError):return 'recovery-required'
        if record:
            if not (directory/'management-token-initialized').exists():atomic_secret(directory/'management-token-initialized','initialized\n')
            return 'preserved'
        if (directory/'management-token-initialized').exists():return 'recovery-required'
        try:legacy=management_record(path)
        except (OSError,ValueError,TypeError):legacy=None
        name=installation_account(legacy)
        write_management_token(directory,name,transition=bool(legacy))
        return 'transition' if legacy else 'created'


def authenticate(username, password):
    if (not isinstance(username, str) or not 1 <= len(username) <= 64
            or not isinstance(password, str) or not 1 <= len(password) <= 1024
            or '\x00' in username or '\x00' in password):
        return False
    try:
        account = pwd.getpwnam(username)
        groups = os.getgrouplist(username, account.pw_gid)
        admins = {grp.getgrnam(name).gr_gid for name in ('sudo', 'wheel')
                  if name in {g.gr_name for g in grp.getgrall()}}
        if account.pw_uid == 0 or not admins.intersection(groups):
            return False  # Use a named local administrator, never a root login.
        import PAM
        def converse(_auth, queries, _data):
            answers = []
            for _prompt, kind in queries:
                if kind == PAM.PAM_PROMPT_ECHO_ON:
                    answers.append((username, 0))
                elif kind == PAM.PAM_PROMPT_ECHO_OFF:
                    answers.append((password, 0))
                elif kind in (PAM.PAM_ERROR_MSG, PAM.PAM_TEXT_INFO):
                    answers.append(('', 0))
                else:
                    raise ValueError('Unsupported authentication prompt')
            return answers
        auth = PAM.pam()
        auth.start('usb-storage-watch-web')
        auth.set_item(PAM.PAM_USER, username)
        auth.set_item(PAM.PAM_CONV, converse)
        auth.authenticate()
        auth.acct_mgmt()
        return True
    except Exception:
        return False  # Neither PAM messages nor credentials cross this boundary.


class Sessions:
    def __init__(self, verifier=authenticate, clock=time.monotonic):
        self.verifier, self.clock = verifier, clock
        self.sessions = {}
        self.failures = deque(maxlen=30)

    def attempt(self):
        now=self.clock()
        while self.failures and self.failures[0]<now-300:self.failures.popleft()
        if len(self.failures)>=10:raise Denied('Too many login attempts. Wait five minutes and try again.')
        self.failures.append(now)

    def login(self, username, password):
        self.attempt()
        if not self.verifier(username,password):raise Denied('Login failed. Use a local administrator account and its password.')
        self.failures.pop()
        return self.issue(username)

    def token_login(self,token,verifier):
        self.attempt();username=verifier(token);self.failures.pop()
        return self.issue(username)

    def issue(self,username):
        now=self.clock()
        self.sessions = {k: v for k, v in self.sessions.items()
                         if now - v['seen'] < 900 and now - v['created'] < 28800}
        if len(self.sessions) >= 32:
            del self.sessions[min(self.sessions, key=lambda k: self.sessions[k]['seen'])]
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[token] = dict(username=username, csrf=csrf, created=now, seen=now)
        return dict(token=token, csrf=csrf, username=username)

    def check(self, token, csrf=None, write=False):
        if not isinstance(token, str):
            raise Denied('Sign in to continue.')
        value = self.sessions.get(token)
        now = self.clock()
        if not value or now - value['seen'] >= 900 or now - value['created'] >= 28800:
            self.sessions.pop(token, None)
            raise Denied('Your session expired. Sign in again.')
        if write and (not isinstance(csrf, str) or not secrets.compare_digest(csrf, value['csrf'])):
            raise Denied('Security token missing or expired. Reload this page.')
        # Reject a session if its administrator account was removed/locked at login
        # policy changes by restarting the broker; credentials are never retained.
        value['seen'] = now
        return value

    def logout(self, token):
        self.sessions.pop(token, None)
