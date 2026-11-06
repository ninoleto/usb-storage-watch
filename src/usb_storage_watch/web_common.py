# SPDX-License-Identifier: MIT
"""Bounded Unix RPC. This module has no recovery or SMTP credentials."""
import importlib.util
import json
import ipaddress
import re
from pathlib import Path
import socket

SOCKET = '/run/usb-storage-watch-web/control.sock'
WEB_DIR = Path('/etc/usb-storage-watch-web')
WEB_CONFIG = WEB_DIR / 'config.json'
DEFAULT = {'lan': False, 'address': '127.0.0.1', 'hostname': 'localhost', 'port': 8765}
MAX_MESSAGE = 128 * 1024


def private_network_address(address):
    try:ip=ipaddress.IPv4Address(address)
    except (ValueError,TypeError):return False
    return any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10'))


def network_config(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT)-{'scheme','http_port','https_port','address_mode'} or not set(DEFAULT)<=set(value):raise ValueError('Invalid network settings.')
    value=dict(value);value.setdefault('scheme','https' if value['lan'] else 'http')
    value.setdefault('address_mode','manual')
    if value['address_mode'] not in ('manual','automatic'):raise ValueError('Choose Automatic or Manual address selection.')
    if type(value['lan']) is not bool or value['scheme'] not in ('http','https'):raise ValueError('Choose HTTP or HTTPS.')
    if type(value['port']) is not int or not 1<=value['port']<=65535:raise ValueError('Invalid listener port.')
    if not isinstance(value['hostname'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}',value['hostname']):raise ValueError('Invalid listener hostname.')
    if value['lan'] and not private_network_address(value['address']) and not (value['address_mode']=='automatic' and value['address']=='127.0.0.1'):raise ValueError('LAN access requires an assigned private IPv4 address.')
    value.setdefault('http_port',value['port'] if value['scheme']=='http' else 8765)
    value.setdefault('https_port',value['port'] if value['scheme']=='https' else 8766)
    for key in ('http_port','https_port'):
        if type(value[key]) is not int or not 1024<=value[key]<=65535:raise ValueError('Ports must be between 1024 and 65535.')
    return value


def module(name, profile=None):
    spec = importlib.util.spec_from_file_location('usw_' + name, Path(__file__).with_name(name + '.py'))
    value = importlib.util.module_from_spec(spec)
    if profile is not None:value.PROFILE = dict(profile)
    spec.loader.exec_module(value)
    return value


def receive(stream):
    data = stream.readline(MAX_MESSAGE + 1)
    if len(data) > MAX_MESSAGE or not data.endswith(b'\n'):
        raise ValueError('Request or response exceeds the size limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def rpc(value):
    data = json.dumps(value).encode() + b'\n'
    if len(data) > MAX_MESSAGE:
        raise ValueError('Request too large')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(SOCKET)
        client.sendall(data)
        client.settimeout(420 if value.get('write') else 25)
        with client.makefile('rb') as stream:
            return receive(stream)
