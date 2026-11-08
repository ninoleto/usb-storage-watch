"""Isolated mounted-standby and Linux accounting fixtures; no hardware commands."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from test_ui8_sleep import ManualStandby,w
io=w.standby.io

class Mounted(ManualStandby):
    def test_automatic_uses_same_post_flush_quiet_guard(self):
        self.users.side_effect=AssertionError('idle handle scan')
        self.activity.side_effect=lambda _:([int(min(self.now,2))],0)
        w.standby.sleep(self.ctx)
        self.assertEqual(self.now,5)
        self.assertEqual(self.calls[0][0],'/usr/bin/sync')

    def test_changed_loop_topology_refuses(self):
        self.topology.side_effect=[self.topology.return_value,{}]
        with self.assertRaisesRegex(w.Unsafe,'mounts changed'):self.sleep_now()
        self.power.assert_not_called()

    def test_pending_io_never_sent_and_background_message_does_not_blame_apps(self):
        self.activity.return_value=([0]*14,1)
        with self.assertRaisesRegex(w.Unsafe,'did not settle') as e:self.sleep_now()
        self.assertNotIn('Close applications',str(e.exception))
        self.assertIn('Source not attributed',str(e.exception))
        self.power.assert_not_called()

    def test_read_write_discard_flush_all_prevent_quiet(self):
        for index in (0,2,4,6,8,12):
            self.now=0
            self.activity.side_effect=lambda _,i=index:([int(self.now) if n==i else 0 for n in range(14)],0)
            with self.assertRaisesRegex(w.Unsafe,'did not settle'):self.sleep_now()
        self.power.assert_not_called()

    def test_power_verification_unavailable_is_unverified_not_unsupported(self):
        self.power.side_effect=['sent',w.Unsafe('unsupported')]
        with self.assertRaises(w.Unsafe) as e:self.sleep_now()
        self.assertEqual(e.exception.standby_result,'unverified')
        self.assertIn('command sent',str(e.exception))

    def test_idle_real_open_file_is_not_a_standby_blocker(self):
        with tempfile.TemporaryFile() as idle:
            idle.write(b'fixture');idle.flush()
            self.users.side_effect=AssertionError('Idle fd must not be examined')
            self.sleep_now()
            self.assertFalse(idle.closed)
        self.users.assert_not_called()

    def test_dependent_image_pending_requests_refuse_even_if_physical_is_quiet(self):
        with patch.object(io,'loop_activity',return_value=[('7:3',[0],1)]):
            with self.assertRaisesRegex(w.Unsafe,'did not settle'):self.sleep_now()
        self.power.assert_not_called()

    def test_swap_refusal_does_not_flush_or_sleep(self):
        with patch.object(io,'swap_guard',side_effect=w.Unsafe('Active swap')):
            with self.assertRaisesRegex(w.Unsafe,'Active swap'):self.sleep_now()
        self.ctx.command.assert_not_called();self.power.assert_not_called()

class Accounting(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root/'dev').write_text('8:16')
        self.binding={'sys':str(self.root),'devs':['8:16','8:17']}
        self.topo=dict(devices=['8:16','8:17','7:3'],loops={'7:3':('8:17',)},targets=['/disk','/image'])
    def metric(self,values,t=1):return dict(key=(10,'start','/cgroup',1,1),values=values,at=t)
    def test_partition_disk_and_loop_are_not_added_together(self):
        a=self.metric({'8:16':(0,0),'8:17':(0,0),'7:3':(0,0)})
        b=self.metric({'8:16':(100,200),'8:17':(100,200),'7:3':(100,200)},3)
        self.assertEqual(io.container_rates(a,b,self.binding,self.topo),([50,100],2,'physical'))
        del a['values']['8:16'];del b['values']['8:16']
        self.assertEqual(io.container_rates(a,b,self.binding,self.topo)[0],[50,100])
        del a['values']['8:17'];del b['values']['8:17']
        self.assertEqual(io.container_rates(a,b,self.binding,self.topo)[2],'loop (logical)')
    def test_missing_reset_and_changed_metrics_not_zero(self):
        for metric in (None,self.metric({'8:16':(0,0)},3),dict(self.metric({},3),key='new')):
            a=dict(containers={'id':dict(id='id',name='reader',access_configured=True,metric=self.metric({'8:16':(10,20)}))},available=True)
            b=dict(containers={'id':dict(a['containers']['id'],metric=metric)},available=True)
            r=io.report(a,b,self.binding,self.topo,[0]*14,[0]*14,2)['containers'][0]
            self.assertEqual(r['state'],'measurement unavailable');self.assertIsNone(r['read_bytes_per_second'])
    def test_all_active_idle_unknown_and_unattributed_are_reported(self):
        a={'containers':{},'available':True};b={'containers':{},'available':True}
        for i in range(5):
            base=dict(id=str(i),name='app'+str(i),access_configured=i!=0)
            a['containers'][str(i)]=dict(base,metric=None if i==4 else self.metric({'8:16':(0,0)}))
            b['containers'][str(i)]=dict(base,metric=None if i==4 else self.metric({'8:16':(10,20) if i<3 else (0,0)},3))
        after=[0]*14;after[6]=100
        r=io.report(a,b,self.binding,self.topo,[0]*14,after,2)
        self.assertEqual(len(r['containers']),5)
        self.assertEqual([c['state'] for c in r['containers']],['observed activity']*3+['access configured; no activity observed','measurement unavailable'])
        self.assertGreater(r['unattributed_write_bytes_per_second'],0)
    def test_real_cgroup_format_and_process_identity(self):
        proc=self.root/'proc';group=self.root/'cgroup';(proc/'42').mkdir(parents=True);(group/'app').mkdir(parents=True)
        (proc/'42/stat').write_text('42 (test app) '+' '.join(['S']+['0']*18+['123']))
        (proc/'42/cgroup').write_text('0::/app\n');(group/'app/io.stat').write_text('8:16 rbytes=1024 wbytes=2048 rios=1 wios=2\n')
        with patch.object(io,'PROC',proc),patch.object(io,'CGROUP',group):
            m=io.metric(42);self.assertEqual(m['values']['8:16'],(1024,2048))
            (group/'app/io.stat').unlink()
            with self.assertRaises(FileNotFoundError):io.metric(42)
    def test_loop_mounted_elsewhere_flushed_before_parent_without_media_access(self):
        block=self.root/'block';loop=block/'loop3/loop';loop.mkdir(parents=True)
        for name,value in [('backing_file','/disk/library.img'),('offset','0'),('sizelimit','0')]: (loop/name).write_text(value)
        (loop.parent/'dev').write_text('7:3')
        rows=[dict(id='1',dev='8:17',root='/',target='/disk',fs='ext4',vfs={'rw'},super={'rw'}),dict(id='2',dev='7:3',root='/',target='/short',fs='ext4',vfs={'rw'},super={'rw'})]
        ctx=SimpleNamespace(read_rows=lambda:rows,covers=w.covers,unescape_mount=w.unescape_mount)
        with patch.object(io,'BLOCK',block):
            top=io.topology(ctx,self.binding)
            self.assertEqual(top['targets'],['/short','/disk'])
            (loop/'offset').write_text('512');self.assertNotEqual(top,io.topology(ctx,self.binding))
    def test_capture_checks_pinned_docker_ids_and_never_requests_a_write(self):
        ids=['a'*64,'b'*64,'c'*64]
        def request(method,path,**kw):
            self.assertEqual(method,'GET')
            if path.endswith('json?all=0'):
                return [dict(Id=cid,Names=['/app'+str(i)],Mounts=[dict(Source='/disk/data')]) for i,cid in enumerate(ids)]
            cid=path.split('/')[2]
            return dict(Id=cid,State=dict(Running=True,Pid=ids.index(cid)+1))
        docker=SimpleNamespace(request=request)
        ctx=SimpleNamespace(apps=SimpleNamespace(Docker=lambda:docker,AppError=RuntimeError),covers=w.covers)
        def metrics(pid):
            if pid==3:raise PermissionError('private detail')
            return dict(self.metric({'8:16':(100,200)}),key=(pid,'start','/group'+str(pid),1,pid))
        with patch.object(io,'metric',side_effect=metrics):
            r=io.capture(ctx,self.topo)
        self.assertTrue(r['available']);self.assertEqual(len(r['containers']),3)
        self.assertIsNone(r['containers'][ids[2]]['metric'])
        self.assertTrue(r['containers'][ids[0]]['access_configured'])
        self.assertNotIn('private detail',str(r))
        with patch.object(io,'metric',return_value=self.metric({})):
            r=io.capture(ctx,self.topo)
        self.assertTrue(all(c['metric'] is None for c in r['containers'].values()))

    def test_subsequent_io_invalidates_confirmed_sleep_without_any_power_query(self):
        import json
        fields=[0]*17;(self.root/'stat').write_text(' '.join(map(str,fields)))
        (self.root/'standby.json').write_text(json.dumps(dict(binding=self.binding,counters=[0]*14,sleeping=True,time='fixture')))
        ctx=SimpleNamespace(STATE_DIR=self.root,clock_now=lambda:10,Unsafe=w.Unsafe)
        with patch.object(w.standby,'identity',return_value=self.binding),patch.object(w.standby,'storage_kind',return_value='mechanical'),patch.object(w.standby,'power_command') as power:
            self.assertTrue(w.standby.status(ctx)['sleeping'])
            fields[0]=1;fields[2]=8;(self.root/'stat').write_text(' '.join(map(str,fields)))
            self.assertEqual(w.standby.status(ctx)['state'],'active')
            self.assertFalse(w.standby.status(ctx)['sleeping']);power.assert_not_called()

    def test_active_swap_block_refuses_without_examining_idle_handles(self):
        (self.root/'swaps').write_text('Filename Type Size Used Priority\n/dev/fixture partition 1024 0 -2\n')
        ctx=SimpleNamespace(unescape_mount=w.unescape_mount,device_number=lambda _: '8:17',Unsafe=w.Unsafe)
        with patch.object(io,'PROC',self.root):
            with self.assertRaisesRegex(w.Unsafe,'Active swap'):io.swap_guard(ctx,self.topo)

    def test_missing_full_physical_counters_refuse_instead_of_assuming_no_flushes(self):
        (self.root/'stat').write_text('0 '*11)
        with self.assertRaisesRegex(ValueError,'counters are unavailable'):w.standby.activity(self.binding)

    def test_standby_does_not_modify_strict_unmount_users(self):
        ctx=SimpleNamespace(read_rows=lambda:[dict(target='/disk')],MOUNT='/disk',DISK_UUID='id',device_number=lambda _: '8:17',mounted_checks=Mock(),standby=SimpleNamespace(identity=lambda _:self.binding,users=Mock(side_effect=w.Unsafe('idle open handle'))),command=Mock())
        with self.assertRaisesRegex(w.Unsafe,'idle open handle'):w.controls.unmount(ctx)
        ctx.command.assert_not_called()

if __name__=='__main__':unittest.main()
