"""Optional root-only fixture: kernel UID/GID access, no host account changes."""
import json,os,unittest
from pathlib import Path
import test_beta5_access as fixture

class KernelAccess(unittest.TestCase):
    def test_shared_group_keeps_child_data_write_and_loses_project_entry_write(self):
        if os.geteuid()!=0:self.skipTest('Root needed only to drop a child process to disposable numeric credentials.')
        f=fixture.Access();f.setUp();self.addCleanup(f.doCleanups)
        f.root.chmod(0o755);f.gid=60042;f.reader.pw_uid=60043
        f.account.pw_gid=f.gid;f.reader.pw_gid=f.gid
        for path in (f.project,f.source,f.environment,f.media,f.data):os.chown(path,-1,f.gid)
        f.media.chmod(0o775);f.data.chmod(0o664)
        f.rehash();f.writable();before=f.children()
        def probe():
            readfd,writefd=os.pipe();pid=os.fork()
            if pid==0:
                os.close(readfd)
                try:
                    os.setgroups([60042]);os.setgid(60042);os.setuid(60043)
                    result={}
                    for label,parent in [('project',f.project),('data',f.media)]:
                        one=parent/'access-probe';two=parent/'access-probe-renamed'
                        try:
                            one.write_text('disposable');one.rename(two);two.unlink();result[label]=True
                        except PermissionError:result[label]=False
                    result['read']=f.data.read_bytes()==b'Preserve media contents'
                    with f.data.open('r+b') as stream:stream.write(b'Preserve media contents')
                    result['write_existing']=True
                    os.write(writefd,json.dumps(result).encode());os._exit(0)
                except BaseException:os._exit(2)
            os.close(writefd);data=os.read(readfd,4096);os.close(readfd);_,status=os.waitpid(pid,0)
            self.assertEqual(status,0);return json.loads(data)
        self.assertEqual(probe(),dict(project=True,data=True,read=True,write_existing=True))
        review=f.reviewed_access();self.assertEqual(review['paths'][0]['affected_users'],['plex'])
        self.assertTrue(f.permission_apply(review)['ok'])
        self.assertEqual(probe(),dict(project=False,data=True,read=True,write_existing=True))
        self.assertEqual(f.children(),before);self.assertEqual(f.docker.updates,[])
        self.assertTrue(f.commit(f.review(f.intent()))['ok'])
        print('PASS real kernel fixture: separate UID/group can still read/write/rename child data, cannot create project entries after reviewed changes; Compose/app save passed.')

if __name__=='__main__':unittest.main()
