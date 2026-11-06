# SPDX-License-Identifier: MIT
"""Two isolated drive instances; OS and hardware boundaries remain synthetic."""
from gui_fixture import Machine,UUID

SECOND='22222222-2222-4222-8222-222222222222'


class FleetMachine:
    def __init__(self):
        self.main=Machine(uuid=UUID,mountpoint='/mnt/drive-a',model='ADATA USB Flash Drive')
        self.children={};self.second=None
        b=self.main.b;c=b.s.default();c['disk'].update(uuid=UUID,label='ADATA USB Flash Drive',mountpoint=self.main.current,fstab_options='defaults,nofail,nodev,nosuid,x-systemd.device-timeout=10s')
        c['recovery']['mount']=True;b.cli.save(self.main.config,c);self.main.active=True
        self.main.fstab.write_text(self.main.original+f'UUID={UUID} /mnt/drive-a ext4 {c["disk"]["fstab_options"]} 0 0\n'+
                                  f'UUID={SECOND} /mnt/drive-b ext4 {c["disk"]["fstab_options"]} 0 0\n')
        self.main.patch(b,'disks',self.disks)
        self.main.broker.fleet.factory=self.create
        self.session=self.main.broker.sessions.login('admin','synthetic')

    def disks(self):
        return self.main.disks()+(self.second.disks() if self.second else [dict(uuid=SECOND,mountpoint='/mnt/drive-b',eligible=True,
            device='/dev/synthetic2',model='SanDisk 3.2Gen1',size=15*1024**3,filesystem='ext4',transport='usb',reason='')])

    def create(self,identifier):
        m=Machine(root=self.main.root,identifier=identifier,uuid=SECOND,mountpoint='/mnt/drive-b',model='SanDisk 3.2Gen1',dev='240:2')
        m.patch(m.b,'disks',self.disks)
        m.b.auth=self.main.b.auth;m.broker.sessions=self.main.broker.sessions
        self.second=m;self.children[identifier]=m
        return m.b,m.broker

    def request(self,action,data=None,profile='legacy',**kwargs):
        return self.main.broker.handle(dict(action=action,data=data or {},write=data is not None,drive=profile,
            token=self.session['token'],csrf=self.session['csrf'],**kwargs))

    def add(self):
        result=self.request('add-drive',dict(uuid=SECOND))
        if result['status']!=200:raise AssertionError(result)
        return result['data']['profile_id']

    def close(self):
        for m in reversed(list(self.children.values())):m.close()
        self.main.close()
