# SPDX-License-Identifier: MIT
"""Persisted outage budget. Read-only projections never grant more time."""
import copy
import datetime
import math
import time

MESSAGE = 'Drive has not returned. Dependent apps remain stopped.'


def epoch(value):
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None: raise ValueError('Outage time has no timezone')
    return parsed.timestamp()


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Invalid drive-return deadline')
    for key in ('limit', 'remaining', 'mono', 'wall', 'deadline'):
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ValueError('Invalid drive-return clock')
    if not 60 <= value['limit'] <= 86400 or value['remaining'] > value['limit']:
        raise ValueError('Invalid drive-return budget')
    if not isinstance(value.get('boot'), str) or not value['boot']:
        raise ValueError('Invalid drive-return boot')
    if value.get('reported_at') is not None: epoch(value['reported_at'])


def advance(incident, minutes, now, boot, wall=None):
    """Update a private state copy, including migration from pre-deadline state.

    Same boot uses elapsed boot time even if wall time moves backwards. Forward
    wall jumps may expire early. Across boots a backwards clock expires rather
    than silently extending the budget. Saved remaining time never increases.
    """
    wall = time.time() if wall is None else wall
    value = incident.get('return_deadline')
    if value is None:
        limit = minutes * 60
        try: confirmed = epoch(incident['confirmed_at'])
        except (ValueError, TypeError, KeyError): confirmed = wall - limit
        # A future/invalid old confirmation cannot justify a new full window.
        remaining = max(0, min(limit, confirmed + limit - wall)) if confirmed <= wall else 0
        value = dict(version=1, limit=limit, remaining=remaining, mono=now,
                     boot=boot, wall=wall, deadline=max(0, confirmed + limit))
        incident['return_deadline'] = value
    else:
        validate(value)
        elapsed_wall = wall - value['wall']
        if value['boot'] == boot and now >= value['mono']:
            elapsed = max(now - value['mono'], elapsed_wall, 0)
        else:
            elapsed = elapsed_wall if elapsed_wall >= 0 else value['remaining']
        value['remaining'] = max(0, min(value['remaining'] - elapsed, value['deadline'] - wall))
        value.update(mono=now, boot=boot, wall=max(wall, value['wall']))
    return value


def status(incident, now, boot, wall=None):
    if 'return_deadline' not in incident: return None
    value = advance(copy.deepcopy(incident), 5, now, boot, wall)
    return dict(remaining_seconds=math.ceil(value['remaining']),
                expired=bool(value.get('reported_at')), reported_at=value.get('reported_at'),
                notification=value.get('notification'), event_id=value.get('event_id'))


def message(incident, now, boot):
    value = status(incident, now, boot)
    if not value: return ''
    if value['expired']: return failure_message(incident)
    seconds = value['remaining_seconds']
    return f'Drive return timeout: {seconds // 60}:{seconds % 60:02d} remaining.'


def failure_message(incident):
    stop = incident.get('stop')
    if stop and (stop.get('result') or {}).get('all_stopped') is not True:
        return 'Drive has not returned. Dependent apps could not all be confirmed stopped.'
    return MESSAGE
