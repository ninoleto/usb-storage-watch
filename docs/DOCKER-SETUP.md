# Guided Docker setup and access review

Startup and recovery remain independent. Select an exact app and its required
drives/optional images, then **Review changes**. Switches edit a draft. Unsaved
settings remain **Not configured**. Green bordered **Startup enabled** and
**Recovery enabled** badges reflect saved settings, including collapsed cards.
A permission adjustment never saves these settings or restarts/recreates an app.

## Review access changes

When Compose inputs are writable by other accounts, the review identifies the
exact project directory, Compose/environment files and any unsafe ancestors.
Current/proposed numeric modes, affected accounts and group membership are shown.
Technical ownership, identity and ACL details are expandable; file contents,
environment values and credentials are never included.

**Review access changes** combines the eligible project directory and currently
identified configuration files into one plan. Confirm only the listed changes.
For example, a fixture directory `0775 → 0755` and file `0664 → 0644` lose group
write access. These are examples, not assumptions about another host. Only
necessary group/other write bits are removed; ownership, read/traverse access and
all child-file/subdirectory permissions remain unchanged. No recursive chmod/chown
or arbitrary caller-supplied path/mode is accepted. Directory setgid is preserved.

Removing directory write access prevents affected accounts from **creating,
deleting or renaming entries directly inside that directory**. Existing writable
data subdirectories retain their own access. The review lists known Docker data
subfolders separately. Native services and jobs are not fully inventoried: it does
not establish that Plex, FTP or another native consumer is unaffected. Confirm only
when the named accounts do not need those directory-entry/configuration writes.
If they do, separate deployment configuration from shared data with its owner.

The broker checks the current complete Docker mount inventory and configured USW
storage, pins all reviewed objects without following symlinks, rechecks memberships,
metadata, child-data identity and existing app/recovery locks, records original
modes privately, and changes only the approved paths. A stale confirmation cannot
be replayed. Each change is read back. Partial failure reports each path as restored,
unchanged, not attempted or uncertain; rollback never writes a replacement object.
An uncertain result requires fresh review, not an automatic retry.

Normal Compose validation and app review run again with the draft retained. Only
**Save settings** applies the existing restart-policy/startup/recovery setup.
Other source/hash/override problems may remain. Configuration files discovered
only after parsing a now-protected source can need another explicit access review.
Successful access changes do not claim those later checks passed.

## Supported limits and remaining GUI stops

An eligible directory is the recorded Compose **project directory**, owned by the
verified project owner, under safe ancestors, not the account home, a mount root,
or a configured USW storage location. Ordinary directories and setgid directories
are supported; access ACLs, sticky/setuid modes and unverifiable identities are not.
Eligible files remain ordinary single-link Compose/environment files owned by the
project owner, at most 1 MiB, without access ACLs or special bits.

The GUI does not change an unsafe ancestor outside the project. It also refuses a
project/configuration path used directly or through an ancestor as application data,
including another container's mount. A known child data source must be an existing
directory; its permissions are checked/preserved. Incomplete Docker inventory,
unknown memberships, symlinks, hard links, ownership mismatch or unsafe source
syntax remain specific refusals. No broad media-content scan or native-service
permission inference is performed. Supported inputs still require normal Compose
hash consistency and ordered-override validation.

## Deployment ownership

Portainer's `io.portainer.server` and `io.portainer.agent` image labels describe the
product. They do not establish who deployed it. A Compose-deployed Portainer server
or agent can therefore use the same verified Compose setup flow. Portainer documents
`io.portainer.accesscontrol.*` labels for resources deployed outside Portainer;
those labels alone also do not establish deployment ownership.

Explicit Portainer stack/edge management markers retain the external-manager
refusal. Unknown Portainer namespace hints remain **Unverified external management**;
standard manager-private Compose locations also remain unverified and blocked.
These heuristics do not query Portainer's control database/API or prove the absence
of an external controller. Compose source must still be locally identified and
verified; confirmed Swarm/Kubernetes/Portainer management is never bypassed.

Source references inspected for this correction:
[Portainer server Dockerfile](https://github.com/portainer/portainer/blob/develop/build/linux/Dockerfile),
[agent Dockerfile](https://github.com/portainer/agent/blob/develop/build/linux/Dockerfile),
[external-resource access labels](https://docs.portainer.io/advanced/access-control),
[stack source layout](https://github.com/portainer/portainer/blob/develop/api/filesystem/filesystem.go).

## Private records and rollback

Original identity/modes and per-path outcomes are recorded under
`docker-setup/<container-id>/permissions-*.json` in private state. Configuration
contents are not stored in permission records. Existing Compose source/policy
backups remain separate. Downgrading the package does not undo confirmed access
changes. Review an original-mode restoration only for the same file/directory and
intended sharing; never restore permissions recursively or overwrite newer incident
state. All new acceptance tests use isolated fixtures, not production applications.
