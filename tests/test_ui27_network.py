# SPDX-License-Identifier: MIT
"""Address changes are simulated; certificates use real OpenSSL in temporary files."""
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gui_fixture import load, Machine
from test_ui12_network import Context, Timer, net, common
import test_ui13_network as certificates

addresses = load('network_addresses')
follow = load('network_follow')


def row(address='192.168.50.2', interface='physical-test', automatic=True, metric=100):
    return dict(address=address, interface=interface, automatic=automatic, advanced=not automatic,
                default_route=True, metric=metric)


class Discovery(unittest.TestCase):
    def test_readiness_refuses_nonlocal_target_and_unrelated_http_listener(self):
        fixture=Machine();self.addCleanup(fixture.close);b=fixture.b
        with patch.object(b.common,'module',return_value=SimpleNamespace(discover=lambda *_:[])),patch.object(b.socket,'create_connection') as connect:
            with self.assertRaisesRegex(ValueError,'not assigned locally'):
                b.lan_ready(dict(address='192.168.50.2',hostname='192.168.50.2',port=8765,scheme='http'))
            connect.assert_not_called()
        for marker,success in [('',False),('X-USW-Listener: http://127.0.0.1:8765\r\n',True)]:
            connection=Mock();connection.makefile.return_value=io.BytesIO(('HTTP/1.1 200 OK\r\n'+marker+'Content-Length: 0\r\n\r\n').encode())
            with patch.object(b.socket,'create_connection') as connect:
                connect.return_value.__enter__.return_value=connection
                value=dict(address='127.0.0.1',hostname='localhost',port=8765,scheme='http')
                if success:b.lan_ready(value)
                else:
                    with self.assertRaisesRegex(ValueError,'expected Storage Watch'):b.lan_ready(value)

    def test_physical_identity_routes_and_stable_selection_without_name_assumptions(self):
        with tempfile.TemporaryDirectory() as root:
            sysfs=Path(root)
            for name in ('connection-z','connection-a','ens-without-carrier'):
                (sysfs/name/'device').mkdir(parents=True)
            links=[]
            for name,ip,kind,state in [('connection-z','10.0.0.2','', 'UP'),('connection-a','10.0.0.3','', 'UP'),
                ('virtual-any-name','172.18.0.1','bridge','UP'),('vpn-any-name','100.64.0.2','wireguard','UNKNOWN'),
                ('ens-without-carrier','10.0.0.4','','DOWN')]:
                links.append(dict(ifname=name,flags=['UP'],operstate=state,linkinfo=dict(info_kind=kind),
                    addr_info=[dict(local=ip,scope='global')]))
            routes=[dict(dev='connection-z',metric=600),dict(dev='connection-a',metric=100),dict(dev='vpn-any-name',metric=1)]
            def command(args,timeout):return json.dumps(routes if 'route' in args else links)
            found=addresses.discover(command,sysfs)
            cfg=dict(lan=True,address_mode='automatic',address='192.168.50.2')
            self.assertEqual(addresses.choose(cfg,found)['interface'],'connection-a')
            self.assertEqual(addresses.choose(cfg,list(reversed(found)))['interface'],'connection-a')
            self.assertFalse(next(v for v in found if v['interface']=='ens-without-carrier')['automatic'])
            self.assertTrue(all(v['advanced'] for v in found if v['interface'] in ('virtual-any-name','vpn-any-name')))
            for v in found:
                self.assertEqual(addresses.choose(dict(cfg,address_mode='manual',address=v['address']),found),v if v['available'] else None)
            routes[0]['metric']=100
            self.assertEqual(addresses.choose(cfg,addresses.discover(command,sysfs))['interface'],'connection-a')
            routes.clear()
            self.assertEqual(addresses.choose(cfg,addresses.discover(command,sysfs))['interface'],'connection-a')

    def test_no_virtual_fallback_or_unsuitable_addresses(self):
        cfg=dict(lan=True,address_mode='automatic',address='10.0.0.2')
        self.assertIsNone(addresses.choose(cfg,[row(automatic=False)]))
        self.assertIsNone(addresses.choose(dict(cfg,lan=False),[row()]))
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);(path/'test'/'device').mkdir(parents=True)
            link=dict(ifname='test',flags=['UP'],operstate='UP',addr_info=[
                dict(local='10.0.0.2',scope='global',deprecated=True),dict(local='10.0.0.3',scope='global',flags=['tentative']),
                dict(local='10.0.0.4',scope='global',preferred_life_time=0),dict(local='127.0.0.1',scope='host'),
                dict(local='8.8.8.8',scope='global')])
            self.assertEqual(addresses.discover(lambda args,t:json.dumps([] if 'route' in args else [link]),path),[])


class Watching(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.c=Context(Path(temp.name));self.rows=[row()];self.active=True;self.now=0;self.failure=False
        config=dict(self.c.initial,address_mode='automatic')
        self.c.atomic(self.c.web_dir/'config.json',json.dumps(config))
        self.c.addresses=lambda:copy.deepcopy(self.rows)
        self.c.selection=lambda cfg,rows=None:addresses.choose(cfg,self.rows if rows is None else rows)
        self.c.service=lambda:dict(ActiveState='active' if self.active else 'inactive',MainPID='12' if self.active else '0')
        self.c.command=self.command
        self.c.follow_material=lambda previous,address:(dict(previous,address=address,hostname=address),
            {'config.json':json.dumps(dict(previous,address=address,hostname=address))})
        self.m=net.Manager(self.c,timer=Timer)
        self.f=follow.Supervisor(self.m,clock=lambda:self.now);self.m.follower=self.f

    def command(self,args,timeout):
        self.c.calls.append(args)
        if net.LAN not in args:return ''
        if self.failure and args[1] in ('restart','start'):raise ValueError('Synthetic listener failure')
        if args[1] in ('start','restart'):self.active=True
        if args[1] in ('stop','disable'):self.active=False
        return ''

    def status(self):return self.f.public(self.c.config(),self.rows)

    def test_change_verified_before_url_and_unchanged_address_does_not_restart(self):
        self.assertIsNone(self.status()['url']);self.f.tick();self.assertIn('192.168.50.2',self.status()['url'])
        self.rows=[row('192.168.50.3')];self.assertIsNone(self.status()['url'])
        self.f.tick();self.assertEqual(self.c.config()['address'],'192.168.50.3')
        self.assertIn('192.168.50.3',self.status()['url']);self.assertEqual(self.m.status()['phase'],'complete')
        count=self.c.calls.count(['/usr/bin/systemctl','restart',net.LAN]);self.f.tick();self.f.tick()
        self.assertEqual(self.c.calls.count(['/usr/bin/systemctl','restart',net.LAN]),count)
        self.assertFalse(any(net.LOCAL in v for v in self.c.calls))

    def test_disconnect_waits_without_start_loops_and_reconnect_or_reboot_recovers(self):
        self.rows=[];self.f.tick();self.assertFalse(self.active);self.assertEqual(self.status()['message'],'Waiting for a network address')
        count=len(self.c.calls)
        for _ in range(4):self.f.tick()
        self.assertEqual(len(self.c.calls),count)
        self.rows=[row('192.168.50.4')];self.f.tick();self.assertTrue(self.active);self.assertTrue(self.status()['url'])
        restarted=follow.Supervisor(self.m,clock=lambda:self.now);self.m.follower=restarted
        self.assertIsNone(restarted.public(self.c.config(),self.rows)['url']);restarted.tick()
        self.assertTrue(restarted.public(self.c.config(),self.rows)['url'])

    def test_manual_address_is_preserved_and_unavailable_url_hidden(self):
        cfg=dict(self.c.config(),address_mode='manual');self.c.atomic(self.c.web_dir/'config.json',json.dumps(cfg))
        self.rows=[row('192.168.50.5')];self.f.tick()
        self.assertEqual(self.c.config(),cfg);self.assertFalse(self.active)
        self.assertEqual(self.status()['phase'],'unavailable');self.assertIsNone(self.status()['url'])
        self.rows=[row()];self.f.tick();self.assertTrue(self.status()['url'])

    def test_disabled_means_no_listener_even_if_discovery_fails(self):
        cfg=dict(self.c.config(),lan=False);self.c.atomic(self.c.web_dir/'config.json',json.dumps(cfg))
        self.c.addresses=Mock(side_effect=ValueError('No discovery'))
        self.f.tick();self.f.tick();self.assertFalse(self.active);self.c.addresses.assert_not_called()
        self.assertEqual(self.status()['phase'],'disabled');self.assertIsNone(self.status()['url'])

    def test_failed_start_is_bounded_and_rollback_keeps_previous_config(self):
        original=self.c.config();self.rows=[row('192.168.50.6')];self.failure=True
        self.f.tick();self.assertEqual(self.c.config(),original);self.assertFalse(self.active)
        count=len(self.c.calls);self.f.tick();self.assertEqual(len(self.c.calls),count)
        self.failure=False;self.now+=61;self.f.tick();self.assertTrue(self.status()['url'])

    def test_pending_transaction_blocks_follow_and_invalidates_old_endpoint(self):
        self.f.tick();self.m.write(dict(operation='test',phase='pending'));self.rows=[row('192.168.50.7')]
        count=len(self.c.calls);self.f.tick();self.assertEqual(len(self.c.calls),count);self.assertIsNone(self.status()['url'])
        self.assertEqual(self.c.config()['address'],'192.168.50.2')

    def test_ready_failure_never_advertises_and_does_not_restart_localhost(self):
        self.c.ready=Mock(side_effect=ValueError('Synthetic wrong server'))
        self.f.tick();self.assertIsNone(self.status()['url']);self.assertFalse(self.active)
        self.assertFalse(any(net.LOCAL in v for v in self.c.calls))

    def test_offline_automatic_intent_requires_local_confirmation(self):
        self.rows=[]
        result=self.m.stage(dict(address_mode='automatic',address='127.0.0.1'))
        self.m.job.run();result=self.m.status();self.assertEqual(result['phase'],'pending')
        self.assertEqual(result['url'],'http://127.0.0.1:8765')
        with self.assertRaises(ValueError):self.m.confirm(result['operation'],'https://192.168.50.2:8766')
        self.m.confirm(result['operation'],result['url']);self.m.job.run()
        self.assertEqual(self.m.status()['phase'],'complete');self.assertFalse(self.active)


class HTTPS(unittest.TestCase):
    setUp = certificates.CertificateRenewal.setUp
    services = certificates.CertificateRenewal.services

    def automatic(self):
        self.cfg['address_mode']='automatic';self.c.atomic(self.c.web_dir/'config.json',json.dumps(self.cfg))
        self.c.command=self.services;self.c.service=lambda:dict(ActiveState='active',MainPID='12')
        self.rows=[row('192.168.50.3')];self.c.addresses=lambda:self.rows
        return self.m.follower

    def test_address_change_uses_same_ca_new_valid_leaf(self):
        f=self.automatic();before=self.c.certificate_info()['fingerprint'];f.tick()
        self.assertEqual(self.m.status()['phase'],'complete',self.m.status())
        self.assertEqual(self.c.config()['address'],'192.168.50.3');self.assertEqual(self.c.config()['scheme'],'https')
        self.assertTrue(self.c.certificate_covers('192.168.50.3'));self.assertFalse(self.c.certificate_covers('192.168.50.2'))
        self.assertEqual(self.c.certificate_info()['fingerprint'],before)
        self.assertEqual((self.c.web_dir/'local-network-ca.pem').read_text(),self.original['local-network-ca.pem'])
        self.assertNotIn(['/usr/bin/systemctl','restart',net.LOCAL],self.service_calls)

    def test_foreign_trust_blocks_follow_and_requires_explicit_replacement(self):
        f=self.automatic();foreign=self.c.web_dir/'local-network-ca.pem';foreign.write_text('EXTERNALLY MANAGED CA')
        self.assertFalse(self.c.certificate_covers('192.168.50.2'))  # SAN alone cannot certify the configured trust.
        f.tick();self.assertIsNone(f.public(self.c.config(),self.rows)['url'])
        self.assertEqual(self.c.config()['address'],'192.168.50.2');self.assertEqual(foreign.read_text(),'EXTERNALLY MANAGED CA')
        self.assertIn('trusted signing key',f.live['message'])
        data=dict(lan=True,address='192.168.50.3',address_mode='automatic',scheme='https',http_port=8765,https_port=8766)
        with patch.object(self.c.b.auth,'management_configured',return_value=True),patch.object(net.socket,'socket'):
            with self.assertRaisesRegex(ValueError,'explicitly approve'):self.c.material(data)
            value,files=self.c.material(dict(data,replace_trust=True))
            staged=self.m.stage(dict(data,replace_trust=True));self.assertTrue(staged['trust_changed'])
        self.assertEqual(value['scheme'],'https');self.assertIn('certificate.pem',files)
        self.assertEqual(foreign.read_text(),'EXTERNALLY MANAGED CA')  # Stage is not an application.


if __name__=='__main__':unittest.main()
