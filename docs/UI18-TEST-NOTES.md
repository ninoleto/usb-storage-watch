> Historical evidence. For current behavior and limits, see [current validation](VALIDATION-CURRENT.md).

# UI18 — Manual Docker container controls

Version: `2.0.0~ui18`. Test release. Adds the manual container controls that
were agreed for the next build but omitted from UI17. All UI17 fixes remain.

## Use a container now

Open Docker & Applications and expand a container card.

- A stopped container has Start.
- A running container has Stop and Restart. Review the confirmation before
  executing either command.
- Progress and results appear below the controls, including errors and
  unconfirmed results. The status badge updates from Docker's reported state.
- Manual controls work with drive monitoring on or off. They also work without
  automatic restart selections or a detected storage relationship.

These controls start, stop or restart only the named, verified container.
They do not restart the Docker daemon, edit Compose, move files, or change
monitoring or automatic restart settings. A manual Start does not mount a
drive or image. The storage advisory explains when missing storage may keep
an application from working even though its container is running.

Paused, dead, restarting, missing or unavailable containers are described
explicitly. The app does not silently unpause, recreate or remove containers.

## Confirmed results and interrupted requests

The backend checks the full container ID and name immediately before the
operation and serializes it with automatic recovery for the same container.
Commands have bounded timeouts. A lost or unclear response is not permission
to repeat a restart. Read-only state refresh may still show the current state.
Running/stopped status does not claim that uploads or application files work.

Unsaved drive/image restart choices and card collapse state are retained when
the runtime status changes. Manual commands do not save or discard those choices.

## Agreed changes included in this release

| Item | Included behavior |
| --- | --- |
| Manual Docker controls | Start, Stop, Restart inside each container card |
| Feedback near the action | Pending, success and error text below controls |
| Virtual-image operation failures | Shared configuration lock; manual mount independent of automatic recovery |
| Image creation confirmation | Closes after completion; partial and uncertain outcomes explained without duplicate creation |
| Image removal position | Separated on the right, matching drive cards |
| Docker storage explanation | Names disk/image and explains disk recovery → image mount → container restart |
| User-selected recovery choices | Storage detection advises; it does not impose a mandatory image gate |
| Monitoring independence | Docker settings and manual controls remain usable with monitoring off |

## Installation and verification

The release ZIP includes INSTALL-FIRST.txt, package checksums and exact executed
checks in TEST-RESULTS.txt. The package upgrade retains existing configuration.
There is no need to recreate Erugo or any existing virtual image.

Tests use synthetic Docker/device responses and private installation roots.
The build process does not install this update or operate the user's physical
drives and containers on Ubuntu or Zorin. Hardware acceptance remains separate.
