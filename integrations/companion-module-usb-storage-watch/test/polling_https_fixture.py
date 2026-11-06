# SPDX-License-Identifier: MIT
"""Read-only timing evidence from real Gunicorn idle expiry; simulated OS only."""
import sys,time
from pathlib import Path
from types import SimpleNamespace
import companion_https_fixture as fixture
from flask import jsonify,request
sys.path.insert(0,str(Path(fixture.h.f.m.web.__file__).with_name('_vendor')))
from gunicorn.workers.gthread import TConn
trace=[]
original_close=TConn.close

def close(self,*args,**kwargs):
    trace.append(dict(event='idle-close' if self.timeout and time.monotonic()>=self.timeout else 'close',at=time.monotonic(),peer=self.client[1],deadline=self.timeout))
    return original_close(self,*args,**kwargs)
TConn.close=close
@fixture.app.before_request
def record_request():
    if request.path.startswith('/api/'):
        trace.append(dict(event='request',endpoint=request.path,at=time.monotonic(),peer=request.environ.get('REMOTE_PORT')))
    if request.path=='/api/docker-overview' and fixture.h.controls['fault']=='docker-503':
        # Exercise the actual outer Broker.handle OSError mapping. This is NOT
        # claimed to identify the swallowed historical exception.
        def unavailable(_):
            fixture.h.f.m.broker.sessions.check(request.cookies.get('usw_session'),request.headers.get('X-CSRF-Token'),False)
            raise OSError('synthetic overview observation unavailable')
        response=fixture.h.b.Broker.handle(SimpleNamespace(fleet=SimpleNamespace(route=unavailable)),dict(action='docker-overview',write=False,data={}))
        return jsonify(error=response['error']),response['status']
@fixture.app.get('/fixture/transport')
def transport_trace():
    return jsonify(marker='usw-idle-close-fixture',keepalive_seconds=2,events=trace[-1000:])
if __name__=='__main__':raise SystemExit(fixture.run())
