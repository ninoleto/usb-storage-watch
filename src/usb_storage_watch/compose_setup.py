# SPDX-License-Identifier: MIT
"""Narrow Compose restart-field editor; paths come only from verified Docker labels.

No up/restart/build/pull commands. Complete effective models stay private.
Unsupported syntax/ownership/context is an instruction, never a guessed edit.
"""
import copy
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
    pass


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
    except KeyError:
        return False


def read_file(path, owner):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise Unavailable('Compose paths must be absolute and unambiguous.')
    # Check every component; writes also pin the parent directory descriptor.
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner):
            raise Unavailable('Compose path ownership or symlink needs manual review.')
        if not private_writes(info, owner) and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            raise Unavailable('Compose directory is writable by other users; use your deployment manager.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
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
    owner = directory.stat().st_uid
    def inside(name):
        path = Path(name)
        if not path.is_absolute(): path = directory / path
        if '..' in path.parts or not path.is_relative_to(directory):
            raise Unavailable('Compose sources outside the recorded project need manual review.')
        return str(path)
    files = [inside(name) for name in files if name]
    if not files: raise Unavailable('Compose source file list is missing.')
    sources = [read_file(path, owner) for path in files]
    env_files = labels.get(prefix + 'project.environment_file', '').split(',')
    env_files = [inside(name) for name in env_files if name]
    if not env_files and (directory / '.env').exists(): env_files = [str(directory / '.env')]
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
    auxiliary = [read_file(path, owner) for path in sorted(dependencies)]
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
