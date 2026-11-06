# SPDX-License-Identifier: MIT
"""Entirely synthetic identities. Never use this profile on physical hardware."""
def configuration(w):
    c=w.settings.default()
    c['disk'].update(uuid='11111111-1111-4111-8111-111111111111', label='Storage',fstab_options='defaults,nofail,x-systemd.device-timeout=10s')
    c['notifications']['enabled']=True
    c['recovery']['mount']=True
    c['recovery']['wait']=60
    c['dependent'].update(enabled=True,uuid='22222222-2222-4222-8222-222222222222',mountpoint='/mnt/storage/_loop/files',image='/mnt/storage/_loop/files.img',fstab_options='loop,nofail,nosuid,nodev,noexec,x-systemd.requires-mounts-for=/mnt/storage')
    pci='0000:00:1f.0'; base='/sys/devices/pci0000:00/'+pci
    c['usb']['profile']={'controller':'/sys/bus/pci/devices/'+pci,'controller_real':base,
      'controller_ids':{'vendor':'0xffff','device':'0xffff','subsystem_vendor':'0xffff','subsystem_device':'0xffff','class':'0x0c0330','revision':'0x00'},
      'root_hub':'/sys/bus/usb/devices/usb9','root_hub_ids':{'idVendor':'ffff','idProduct':'ffff','serial':pci},
      'port':'/sys/bus/usb/devices/9-0:1.0/usb9-port2','canonical':base+'/usb9/9-0:1.0/usb9-port2',
      'device':'/sys/bus/usb/devices/9-2','device_real':base+'/usb9/9-2','firmware':'/sys/devices/SIMULATED/PORT2',
      'vid':'ffff','pid':'ffff','disk_serial':'SYNTHETIC-TEST-DISK','qualified':True,
      'qualification':{'date':'2000-01-01','evidence':'Synthetic qualification for isolated unit tests only.', 'isolated_port':True,'reenable_verified':True,'expected_disk_returned':True}}
    c['usb']['enabled']=True
    c['docker'].update(enabled=True,containers=[{'name':'app_one','source':'/mnt/storage/app_one-uploads','destination':'/var/www/html/storage/app/shares','grace':30}, {'name':'app_two','source':'/mnt/storage/app_two/originals','destination':'/app_two/originals','grace':30}, {'name':'app_three','source':'/mnt/storage/app_three-uploads','destination':'/data','grace':60}])
    return c

def configure(w):
    w.configure(configuration(w))
