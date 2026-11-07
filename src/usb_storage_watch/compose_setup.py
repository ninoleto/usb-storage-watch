# SPDX-License-Identifier: MIT
"""Narrow Compose restart-field editor; paths come only from verified Docker labels.

No up/restart/build/pull commands. Complete effective models stay private.
Unsupported syntax/ownership/context is an instruction, never a guessed edit.
"""
import copy
from contextlib import ExitStack
import errno
import hashlib
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile


class Unavailable(ValueError):
    def __init__(self, message, diagnostics=()):
        super().__init__(message)
        self.diagnostics = list(diagnostics)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def private_writes(info, owner):
    """An owner-private Unix group is as narrow as owner write permission."""
    if info.st_mode & 0o002: return False
    if not info.st_mode & 0o020: return True
    try:
        group = grp.getgrgid(info.st_gid)
        members = {pwd.getpwnam(name).pw_uid for name in group.gr_mem}
        members.update(p.pw_uid for p in pwd.getpwall() if p.pw_gid == info.st_gid)
        return members <= {0, owner}
    except (KeyError, OSError):
        return False


def group_access(gid):
    """Report only the relevant group, including primary group membership."""
    try:
        group = grp.getgrgid(gid)
        members = {p.pw_uid: p.pw_name for p in pwd.getpwall() if p.pw_gid == gid}
        for name in group.gr_mem:
            account = pwd.getpwnam(name); members[account.pw_uid] = name
        return dict(id=gid, name=group.gr_name, known=True,
                    members=[dict(uid=uid, name=name) for uid, name in sorted(members.items())])
    except (KeyError, OSError):
        return dict(id=gid, name=str(gid), known=False, members=[])


def identity(info, *, file=False):
    value = dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid,
                 gid=info.st_gid, mode=info.st_mode)
    if file: value.update(links=info.st_nlink, size=info.st_size, modified=info.st_mtime_ns, changed=info.st_ctime_ns)
    return value


def access_acl(path):
    try: os.getxattr(path, 'system.posix_acl_access', follow_symlinks=False); return 'present'
    except OSError as exc:
        return 'none' if exc.errno in (errno.ENODATA, errno.ENOTSUP) else 'unknown'


def path_diagnostic(path, info, owner, role, problem, chain):
    if info is None:
        return dict(path=str(path), type='unknown', role=role, owner=None,
                    group=dict(id=None, name=None, known=False, members=[]), mode=None,
                    problem='unavailable', acl='unknown', hard_links=None, affected_users=[], affects_others=False,
                    adjustable=False, proposed_mode=None,
                    limitation='This path is missing or its metadata cannot be read. Restore access to the recorded configuration location, then review again. No permission change is offered.',
                    _identity=None, _owner=owner, _chain=chain)
    try: username = pwd.getpwuid(info.st_uid).pw_name
    except (KeyError, OSError): username = str(info.st_uid)
    group = group_access(info.st_gid); mode = stat.S_IMODE(info.st_mode)
    directory = stat.S_ISDIR(info.st_mode)
    kind = 'directory' if directory else 'file' if stat.S_ISREG(info.st_mode) else 'symlink' if stat.S_ISLNK(info.st_mode) else 'other'
    affected = [m['name'] for m in group['members'] if m['uid'] not in (0, owner)] if mode & 0o020 else []
    acl = access_acl(path)
    eligible = (problem == 'shared_write' and kind == 'file' and info.st_uid == owner
                and info.st_nlink == 1 and info.st_size <= 1024 * 1024 and not mode & 0o7000
                and acl == 'none' and group['known'])
    limitation = ('Directory permissions affect creating, deleting and renaming other files. '
                  'Storage Watch will not change this directory or its children. Ask its owner to review shared application/media access.' if directory else
                  'Only an ordinary single-link Compose or environment file owned by the project owner, without an access ACL or special mode bits, can be adjusted here.')
    if problem == 'read_failed':
        limitation = ('The broker cannot read this configuration file. Ask the owner to check filesystem access or security policy. '
                      'Changing its Unix mode alone is not a verified remedy, so no adjustment is offered.')
    return dict(path=str(path), type=kind, role=role, owner=dict(uid=info.st_uid, name=username),
                group=group, mode=f'{mode:04o}', problem=problem, acl=acl,
                hard_links=info.st_nlink if kind == 'file' else None,
                affected_users=affected, affects_others=bool(mode & 0o002),
                adjustable=eligible, proposed_mode=f'{mode & ~0o022:04o}' if eligible else None,
                limitation='' if eligible else limitation,
                _identity=identity(info, file=True), _owner=owner, _chain=chain)


def path_issues(path, owner, role='compose_file', project=None):
    """Metadata only: never read rejected configuration or environment contents."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise Unavailable('Compose paths must be absolute and unambiguous.')
    issues = []; chain = []
    for parent in reversed(path.parents):
        kind = 'project_directory' if project and parent == Path(project) else 'parent_directory'
        try: info = parent.lstat()
        except OSError:
            return issues + [path_diagnostic(parent, None, owner, kind, 'unavailable', chain)]
        chain.append(dict(path=str(parent), identity=identity(info)))
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner):
            issues.append(path_diagnostic(parent, info, owner, kind, 'ownership_or_type', list(chain)))
            if not stat.S_ISDIR(info.st_mode): return issues
        elif not private_writes(info, owner) and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            issues.append(path_diagnostic(parent, info, owner, kind, 'shared_write', list(chain)))
    try: info = path.lstat()
    except OSError:
        return issues + [path_diagnostic(path, None, owner, role, 'unavailable', chain)]
    problem = ('ownership_or_type' if not stat.S_ISREG(info.st_mode) or info.st_uid != owner else
               'links_or_size' if info.st_nlink != 1 or info.st_size > 1024 * 1024 else
               'shared_write' if not private_writes(info, owner) else None)
    if problem:
        item = path_diagnostic(path, info, owner, role, problem, chain)
        if issues and item['adjustable']:
            item.update(adjustable=False, proposed_mode=None,
                        limitation='A parent directory also needs review. No file permission change is offered through an unsafe parent.')
        issues.append(item)
    return issues


def check_paths(paths, owner, project):
    issues = {}
    for path, role in paths:
        for issue in path_issues(path, owner, role, project): issues.setdefault(issue['path'], issue)
    if issues:
        first = next(iter(issues.values()))
        raise Unavailable('Deployment permissions need review: ' + first['path'], issues.values())


def public_diagnostic(value):
    return {k: v for k, v in value.items() if not k.startswith('_')}


def adjust_permission(value, before_write):
    """One pinned file, remove write bits only. No directory/path arguments from UI."""
    path = Path(value['path']); owner = value['_owner']
    if not value['adjustable']: raise Unavailable('This path cannot be adjusted here.')
    fresh = path_issues(path, owner, value['role'])
    if len(fresh) != 1 or fresh[0] != value:
        raise Unavailable('Permissions, identity or group membership changed. Review again; nothing was changed.')
    with ExitStack() as held:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        held.callback(os.close, parent)
        if identity(os.fstat(parent)) != value['_chain'][0]['identity']:
            raise Unavailable('The parent path changed. Review again.')
        for index, part in enumerate(path.parts[1:-1], 1):
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            held.callback(os.close, parent)
            if identity(os.fstat(parent)) != value['_chain'][index]['identity']:
                raise Unavailable('A parent directory changed. Nothing was changed; review again.')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        held.callback(os.close, fd)
        if identity(os.fstat(fd), file=True) != value['_identity'] or path_issues(path, owner, value['role']) != [value]:
            raise Unavailable('The reviewed file changed. Nothing was changed; review again.')
        before_write()  # Durable private record before the single metadata change.
        if identity(os.fstat(fd), file=True) != value['_identity'] or path_issues(path, owner, value['role']) != [value]:
            raise Unavailable('The file or permissions changed before applying. Nothing was changed; review again.')
        mode = int(value['mode'], 8); proposed = int(value['proposed_mode'], 8)
        try:
            os.fchmod(fd, proposed)
            after = os.fstat(fd)
            if (after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_nlink, stat.S_IMODE(after.st_mode)) != (
                    value['_identity']['device'], value['_identity']['inode'], value['owner']['uid'], value['group']['id'], 1, proposed):
                raise Unavailable('Permission readback changed.')
            if (after.st_size, after.st_mtime_ns) != (value['_identity']['size'], value['_identity']['modified']):
                raise Unavailable('Configuration contents changed during permission adjustment.')
            if identity(path.lstat(), file=True) != identity(after, file=True) or path_issues(path, owner, value['role']):
                raise Unavailable('The path changed during permission readback.')
        except Exception:
            current = os.fstat(fd)
            if identity(current, file=True) == value['_identity']:
                raise Unavailable('Permission change was refused. The original permissions are unchanged; ask the file owner to check filesystem access.') from None
            if (current.st_dev, current.st_ino, current.st_uid, current.st_gid, current.st_nlink, stat.S_IMODE(current.st_mode)) == (
                    value['_identity']['device'], value['_identity']['inode'], value['owner']['uid'], value['group']['id'], 1, proposed):
                os.fchmod(fd, mode)
                if stat.S_IMODE(os.fstat(fd).st_mode) == mode:
                    raise Unavailable('Permission verification failed. The original mode was restored; review again.') from None
            raise Unavailable('Permission outcome needs administrator review. No container action was requested.') from None


def read_file(path, owner, role='compose_file', project=None):
    path = Path(path)
    check_paths([(path, role)], owner, project)
    try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        try: info = path.lstat()
        except OSError: info = None
        raise Unavailable('Configuration file could not be opened safely: ' + str(path),
                          [path_diagnostic(path, info, owner, role, 'read_failed', [])]) from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner
                or not private_writes(info, owner) or info.st_size > 1024 * 1024):
            raise Unavailable('Compose file ownership, permissions, links or size need manual review.')
        with os.fdopen(fd, 'rb', closefd=False) as handle: data = handle.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024: raise Unavailable('Compose source exceeds the review limit.')
        return dict(path=str(path), text=data.decode('utf-8'), sha256=hashlib.sha256(data).hexdigest(),
                    dev=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
                    mode=stat.S_IMODE(info.st_mode))
    finally:
        os.close(fd)


def parse(text):
    try:
        import yaml
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken))
               for token in yaml.scan(text)):
            raise Unavailable('Compose anchors, aliases or custom tags need manual editing of the selected service.')
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        def walk(value):
            if isinstance(value, yaml.MappingNode):
                keys = []
                for key, item in value.value:
                    if not isinstance(key, yaml.ScalarNode) or key.tag != 'tag:yaml.org,2002:str':
                        raise Unavailable('Compose mapping keys need manual review.')
                    if key.value in keys: raise Unavailable('Duplicate Compose keys need manual review.')
                    keys.append(key.value); walk(item)
            elif isinstance(value, yaml.SequenceNode):
                for item in value.value: walk(item)
        walk(node)
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or not isinstance(data.get('services'), dict):
            raise Unavailable('A Compose source has no ordinary services mapping.')
        if 'include' in data or any('extends' in s for s in data['services'].values() if isinstance(s, dict)):
            raise Unavailable('Compose include/extends sources need review in the authoritative deployment configuration.')
        return data, node
    except ImportError:
        raise Unavailable('Install python3-yaml to enable validated Compose previews.') from None
    except Unavailable:
        raise
    except Exception:
        raise Unavailable('Compose YAML cannot be parsed safely; edit and validate it with your deployment manager.') from None


def member(node, key):
    return next((v for k, v in node.value if k.value == key), None)


def edit(text, service, target):
    data, root = parse(text)
    value = member(member(root, 'services'), service)
    if value is None or value.id != 'mapping' or value.flow_style:
        raise Unavailable('The selected service needs an ordinary block mapping for a precise restart-only edit.')
    policy = member(value, 'restart')
    if policy is not None:
        if policy.id != 'scalar' or not re.fullmatch(r'(no|always|unless-stopped|on-failure(?::[0-9]+)?)', policy.value):
            raise Unavailable('The selected restart value is computed or ambiguous; explicitly set services.' + service + '.restart in its source.')
        return text[:policy.start_mark.index] + json.dumps(target) + text[policy.end_mark.index:]
    lines = text.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[:value.start_mark.line])
    newline = '\r\n' if '\r\n' in text else '\n'
    return text[:offset] + ' ' * value.start_mark.column + 'restart: ' + json.dumps(target) + newline + text[offset:]


def binary():
    for name in ('/usr/libexec/docker/cli-plugins/docker-compose', '/usr/lib/docker/cli-plugins/docker-compose'):
        path = Path(name)
        try:
            if path.resolve() != path: continue
            info = path.stat()
            if info.st_uid == 0 and not info.st_mode & 0o022 and stat.S_ISREG(info.st_mode): return name
        except OSError: pass
    raise Unavailable('A trusted system Docker Compose plugin is unavailable. Validate the selected service with your deployment manager.')


def run(context, files, *, hash_service=False):
    args = [binary(), '--project-directory', context['directory'], '--project-name', context['project']]
    for path in files: args += ['--file', path]
    for path in context['env_files']: args += ['--env-file', path]
    args += ['config', '--hash', context['service']] if hash_service else ['config', '--format', 'json']
    account = pwd.getpwuid(context['owner'])
    env = dict(PATH='/usr/bin:/bin', HOME=account.pw_dir, LANG='C.UTF-8',
               DOCKER_HOST='unix:///var/run/docker.sock', COMPOSE_DISABLE_ENV_FILE='1')
    # No shell, inherited interpolation environment, user plugins or daemon actions.
    credentials = dict(user=context['owner'], group=account.pw_gid, extra_groups=[]) if os.geteuid() == 0 else {}
    if os.geteuid() not in (0, context['owner']): raise Unavailable('Compose project owner cannot be verified.')
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(args, cwd=context['directory'], env=env, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.DEVNULL, timeout=20, **credentials)
            if result.returncode or output.tell() > 8 * 1024 * 1024:
                raise Unavailable('Compose validation failed with the recorded files/environment. Use the original deployment command to validate its effective configuration.')
            output.seek(0); text = output.read().decode('utf-8')
            if hash_service:
                value = text.strip().split()
                if len(value) != 2 or value[0] != context['service'] or not re.fullmatch('[0-9a-f]{64}', value[1]):
                    raise Unavailable('Compose cannot provide a verifiable service configuration hash.')
                return value[1]
            return json.loads(text)
        except (subprocess.SubprocessError, UnicodeError, json.JSONDecodeError):
            raise Unavailable('Compose validation timed out or returned an unsupported result; no daemon action was requested.') from None


def context(labels):
    prefix = 'com.docker.compose.'
    directory = Path(labels.get(prefix + 'project.working_dir', ''))
    project, service = labels.get(prefix + 'project', ''), labels.get(prefix + 'service', '')
    files = labels.get(prefix + 'project.config_files', '').split(',')
    if (not directory.is_absolute() or directory.resolve() != directory or str(directory) == '/'
            or not re.fullmatch('[a-z0-9][a-z0-9_-]*', project)
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', service)
            or not 1 <= len(files) <= 8 or len(set(files)) != len(files)):
        raise Unavailable('Compose project, service and ordered source files could not be identified reliably from this container.')
    try: owner = directory.stat().st_uid
    except OSError:
        raise Unavailable('The recorded Compose directory is unavailable.',
                          [path_diagnostic(directory, None, None, 'project_directory', 'unavailable', [])]) from None
    def inside(name):
        path = Path(name)
        if not path.is_absolute(): path = directory / path
        if '..' in path.parts or not path.is_relative_to(directory):
            raise Unavailable('Compose sources outside the recorded project need manual review.')
        return str(path)
    files = [inside(name) for name in files if name]
    if not files: raise Unavailable('Compose source file list is missing.')
    env_files = labels.get(prefix + 'project.environment_file', '').split(',')
    env_files = [inside(name) for name in env_files if name]
    if not env_files and (directory / '.env').exists(): env_files = [str(directory / '.env')]
    check_paths([(p, 'compose_file') for p in files] + [(p, 'environment_file') for p in env_files], owner, directory)
    sources = [read_file(path, owner, project=directory) for path in files]
    dependencies = set(env_files)
    documents = []
    for source in sources:
        data, _ = parse(source['text']); documents.append(data)
        for spec in data['services'].values():
            if not isinstance(spec, dict): raise Unavailable('Compose service mapping needs manual review.')
            values = spec.get('env_file', [])
            if isinstance(values, (str, dict)): values = [values]
            for item in values:
                value = item.get('path') if isinstance(item, dict) else item
                if not isinstance(value, str) or '$' in value: raise Unavailable('Computed Compose env-file paths need manual review.')
                # Relative paths resolve from the base file, not later overrides.
                dependencies.add(inside(str(Path(files[0]).parent / value) if not Path(value).is_absolute() else value))
    check_paths([(p, 'environment_file') for p in sorted(dependencies)], owner, directory)
    auxiliary = [read_file(path, owner, 'environment_file', directory) for path in sorted(dependencies)]
    if any(re.search(r'^\s*(?:export\s+)?COMPOSE_[A-Z_]+\s*=', item['text'], re.M) for item in auxiliary if item['path'] in env_files):
        raise Unavailable('Compose control variables in the environment files need manual review with the original deployment command.')
    absent = [str(directory / '.env')] if not env_files and not (directory / '.env').exists() else []
    return dict(directory=str(directory), project=project, service=service, files=files,
                env_files=env_files, owner=owner, sources=sources, auxiliary=auxiliary, documents=documents, absent=absent)


def fingerprints(ctx):
    return {v['path']: v['sha256'] for v in ctx['sources'] + ctx['auxiliary']}


def unchanged(ctx):
    if any(Path(path).exists() or Path(path).is_symlink() for path in ctx.get('absent', [])):
        raise Unavailable('A Compose environment file appeared after preview; review setup again.')
    for old in ctx['sources'] + ctx['auxiliary']:
        now = read_file(old['path'], ctx['owner'])
        if any(now[k] != old[k] for k in ('sha256', 'dev', 'inode', 'mode', 'uid', 'gid')):
            raise Unavailable('Compose inputs changed after preview; review a new preview before applying.')


def preview(labels, receipt=None):
    ctx = context(labels); model = run(ctx, ctx['files'])
    selected = model.get('services', {}).get(ctx['service'])
    if not isinstance(selected, dict): raise Unavailable('Selected service is absent from effective Compose configuration.')
    if (selected.get('deploy') or {}).get('restart_policy'):
        raise Unavailable('Set services.' + ctx['service'] + '.restart to "no" and remove the conflicting deploy.restart_policy in the authoritative configuration, then review again.')
    current_hash = run(ctx, ctx['files'], hash_service=True)
    known = labels.get('com.docker.compose.config-hash')
    accepted = receipt and receipt.get('phase') == 'verified' and receipt.get('compose_hash') == current_hash
    if current_hash != known and not accepted:
        raise Unavailable('Effective Compose configuration does not reproduce this container’s recorded configuration hash. Confirm the original files, overrides and interpolation environment with its deployment manager.')
    index = max((i for i, data in enumerate(ctx['documents']) if ctx['service'] in data['services']), default=-1)
    if index < 0: raise Unavailable('Selected service has no editable source mapping.')
    target = ctx['sources'][index]
    old_policy = selected.get('restart', 'no')
    proposed = target['text'] if old_policy == 'no' else edit(target['text'], ctx['service'], 'no')
    # Validate using a temporary replacement at the same path depth. Never emit model/variables.
    effective = copy.deepcopy(model); effective['services'][ctx['service']]['restart'] = 'no'
    if proposed != target['text']:
        fd, temporary = tempfile.mkstemp(prefix='.usw-compose-preview-', suffix='.yaml', dir=Path(target['path']).parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                if os.geteuid() == 0: os.fchown(handle.fileno(), ctx['owner'], target['gid'])
                handle.write(proposed)
            paths = list(ctx['files']); paths[index] = temporary
            rendered = run(ctx, paths)
            if rendered != effective: raise Unavailable('Preview changes more than the selected restart policy; use your deployment manager.')
        finally: os.unlink(temporary)
    else:
        effective = model
    unchanged(ctx)
    _, source_node = parse(target['text'])
    restart_node = member(member(member(source_node, 'services'), ctx['service']), 'restart')
    source_before = target['text'][restart_node.start_mark.index:restart_node.end_mark.index] if restart_node else None
    return dict(context=ctx, index=index, text=proposed, before_digest=digest(model), after_digest=digest(effective),
                old_policy=old_policy, service_hash=current_hash,
                public=dict(service=ctx['service'], files=ctx['files'], file=target['path'],
                            before=old_policy, after='no', source_before=source_before, source_after='"no"',
                            changes=proposed != target['text']))


def replace(original, text):
    """Replace only the pinned regular file; preserve owner/mode and fsync its directory."""
    path = Path(original['path']); parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        now = read_file(path, original['uid'])
        if any(now[k] != original[k] for k in ('sha256', 'dev', 'inode', 'uid', 'gid', 'mode')):
            raise Unavailable('Compose source changed; no overwrite was permitted.')
        if os.fstat(parent).st_ino != path.parent.stat().st_ino:
            raise Unavailable('Compose parent directory changed; no overwrite was permitted.')
        import secrets
        temporary = '.usw-compose-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'w') as handle:
            if os.geteuid() == 0: os.fchown(handle.fileno(), original['uid'], original['gid'])
            os.fchmod(handle.fileno(), original['mode']); handle.write(text); handle.flush(); os.fsync(handle.fileno())
        # Recheck the destination immediately before the atomic replacement.
        if read_file(path, original['uid']) != now: raise Unavailable('Compose source changed during replacement.')
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent); temporary = None
        os.fsync(parent)
        return read_file(path, original['uid'])
    finally:
        if temporary: os.unlink(temporary, dir_fd=parent)
        os.close(parent)
