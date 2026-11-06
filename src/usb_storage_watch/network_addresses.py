# SPDX-License-Identifier: MIT
"""Local Linux address/route discovery. No probes, DHCP or network-manager changes."""
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess


def private(address):
    try: value = ipaddress.IPv4Address(address)
    except (ValueError, TypeError): return False
    return any(value in ipaddress.ip_network(net) for net in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10'))


def discover(command=None, sysfs=Path('/sys/class/net')):
    executable = shutil.which('ip', path='/usr/sbin:/usr/bin:/sbin:/bin')
    if not executable: raise ValueError('Local address discovery requires iproute2.')
    if command is None:
        def command(args, timeout=5):
            return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout
    links = json.loads(command([executable, '-j', '-d', '-4', 'addr', 'show'], 5))
    routes = json.loads(command([executable, '-j', '-4', 'route', 'show', 'default'], 5))
    metrics = {}
    for route in routes:
        if route.get('type', 'unicast') != 'unicast' or 'linkdown' in route.get('flags', []): continue
        for hop in route.get('nexthops', [route]):
            name = hop.get('dev'); metric = int(route.get('metric', 0))
            if name: metrics[name] = min(metrics.get(name, metric), metric)
    result = []
    for link in links:
        name = link.get('ifname', '')
        if not name or '/' in name or name in ('.', '..') or 'UP' not in link.get('flags', []): continue
        kind = link.get('linkinfo', {}).get('info_kind', '')
        physical = (sysfs / name / 'device').exists() and not kind and not link.get('master')
        usable = link.get('operstate') == 'UP' or 'LOWER_UP' in link.get('flags', [])
        for entry in link.get('addr_info', []):
            address = entry.get('local')
            flags = entry.get('flags', [])
            if (entry.get('scope') != 'global' or not private(address)
                    or any(entry.get(f) or f in flags for f in ('tentative', 'dadfailed', 'deprecated'))
                    or entry.get('preferred_life_time') == 0 or entry.get('valid_life_time') == 0): continue
            result.append(dict(address=address, interface=name, advanced=not physical,
                automatic=bool(physical and usable), available=bool(usable or not physical),
                kind=kind or ('physical' if physical else 'virtual'),
                default_route=name in metrics, metric=metrics.get(name)))
    return sorted(result, key=rank)


def rank(item):
    return (not item.get('automatic'), not item.get('default_route'),
            item.get('metric') if item.get('metric') is not None else 2**32,
            item.get('interface', ''), int(ipaddress.IPv4Address(item['address'])))


def choose(config, addresses):
    if not config['lan']: return None
    if config.get('address_mode', 'manual') == 'automatic':
        return next(iter(sorted((v for v in addresses if v.get('automatic')), key=rank)), None)
    return next((v for v in addresses if v['address'] == config['address'] and v.get('available', True)), None)
