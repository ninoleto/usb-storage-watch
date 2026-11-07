# Guided Docker setup and permissions

Computer startup and drive recovery remain independent. Select the actual app,
choose its drives and optional images, then use **Review changes**. Switches edit
a draft. **Not configured** stays visible for settings that have never been saved;
existing saved choices remain authoritative. Green bordered **Startup enabled**
and **Recovery enabled** badges reflect saved settings, including collapsed cards.
Unknown reads never become enabled badges. Running/stopped status is separate.

## When Compose permissions prevent setup

The review identifies each known rejected path as a Compose file, environment
file, project directory or parent directory. The problem may be an ancestor of
the project, not the project itself. **Technical details** shows the exact owner,
UID, group/GID, Unix mode, relevant primary/supplementary group members and ACL
availability. No configuration contents, environment values or credentials are
returned. Unavailable metadata stays unknown.

A group writable file is allowed by existing validation only when all known group
members are the project owner or root. A shared group needs review even when its
name happens to match the owner's login. This rule is not weakened.

For an eligible file, select **Review file permission change**. The confirmation
shows one exact path, old/new permissions and the accounts whose write permission
will be removed. For example, `0664 → 0644` removes group write; `0660 → 0640`
preserves group read and does not add access for others. The owner/root retain
access. Decline if another account legitimately needs to generate or edit this
configuration; coordinate that workflow with its owner instead.

Nothing changes until **Confirm**. The backend checks the pinned container,
saved selections, recovery/app locks, path components, file identity/mode and group
membership again. It records the original mode privately, opens the exact file
without following symlinks, removes only group/other write bits and verifies the
result. It never uses recursive chmod, chown, a caller-supplied mode or a free-form
path. A used/stale confirmation cannot be replayed.

The normal Compose/source validation runs again, including ordered overrides and
the recorded configuration hash. The app review is then refreshed, with the draft
retained. Permission success does **not** save startup/recovery, change Docker's
restart policy, restart a container, or claim all setup is complete. Other input
files may still need their own review. Use **Save settings** only after the normal
review succeeds. That existing save backs up and edits only the selected service's
restart policy, verifies Docker's live policy and preserves other settings.

## Supported and refused adjustments

The offered adjustment is limited to an ordinary single-link Compose/environment
file identified from the selected container's deployment, owned by the verified
project owner, at most 1 MiB, under safe parent directories. There must be no access
ACL, special mode bits or unresolved group membership. A file inside a known bind
mount used by the selected app is not offered for adjustment. These checks do not
claim discovery of every possible native-service consumer.

**Directory permissions are diagnosed but never changed by this workflow.** Group
write on a directory affects creating, deleting and renaming other entries and
can be part of legitimate media/application sharing. The review names the exact
directory and group members; its owner must decide how to protect the deployment
source while preserving those users. No parent folder, media directory or child
file is changed implicitly. A file behind an unsafe parent cannot be repaired
through this workflow until that parent has been reviewed separately.

Symlinks, hard links, ownership mismatches, access ACLs, unavailable metadata and
broker read denials need owner/administrator review. No guessed chmod is offered.
Unsupported Compose syntax, ambiguous inputs/hash mismatches and externally managed
deployments remain blocked by the existing validator. Portainer/Swarm/Kubernetes
ownership is explained; technical commands/instructions are expandable. No
`compose up`, recreation or deployment-manager bypass is introduced.

## Partial failure and rollback

A permission change and app settings save are separate confirmed steps. If source
validation still fails after the mode was verified, the UI reports the successful
permission change and the remaining setup problem. If an app save partly succeeds,
only verified saved stages become enabled; unsaved stages stay unconfigured/off.
No request is automatically replayed after an uncertain response.

Permission records are private under `docker-setup/<container-id>/permissions-*.json`
in Storage Watch's state directory. They store identity and the original mode, not
file contents. A failed permission readback restores only the exact pinned file's
mode when that rollback is verifiable; uncertain outcomes require review. Normal
Compose-policy source backups remain separate.

Downgrading the package does not undo an explicitly confirmed permission change.
An administrator can use the private record to review a mode restoration only for
the same file identity and intended sharing. Do not restore permissions recursively
or overwrite later app configuration/incident state. All release tests use private
fixtures; target-host setup acceptance remains an operator task.
