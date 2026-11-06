import test from 'node:test'
import assert from 'node:assert/strict'
import { Controller, values } from '../src/controller.js'
import { ApiError, serverURL } from '../src/client.js'
const A='a'.repeat(64), B='b'.repeat(64)
function fixture() {
  const d={configured:true,profile_id:'drive-a',uuid:'11111111-1111-4111-8111-111111111111',name:'External disk',mountpoint:'/mnt/data',connected:true,mount_state:'mounted',monitoring:'active',progress:{phase:'done',code:'healthy'}}
  const inventory={inventory_ok:true,containers:[{id:A,name:'same-name',state:'running',discovered:true,control_block:''},{id:B,name:'same-name',state:'missing',discovered:false}],applications:{revision:'r1',settings:[{id:A,boot:{enabled:true,drives:[{id:'drive-a',images:[]}]},recovery:{enabled:false}}]}}
  const client={session:1,calls:[],request:async function(path,data) { this.calls.push({path,data}); if(path==='fleet-status') return {drives:[structuredClone(d)]}; if(path==='docker-overview') return structuredClone(inventory); if(path.includes('unmount-plan')) return {token:'one-use',apps:[{id:A,name:'same-name',running:true,images:['optional-image']},{id:B,name:'folder-app',running:false,images:[]}],message:'Apps stay stopped. Monitoring stops.'}; return {ok:true,message:'Verified'} },close(){}}
  let now=100000;const c=new Controller(client,()=>{},()=>now)
  return {c,client,d,inventory,advance:ms=>{now+=ms}}
}
test('same names preserve full identities and missing/partial settings are unknown',async()=>{
 const {c}=fixture();await c.refresh();const v=values(c);assert.equal(c.state.apps.length,2);assert.equal(v['app_'+A+'_startup'],'enabled');assert.equal(v['app_'+A+'_recovery'],'off');assert.equal(v['app_'+B+'_startup'],'unknown');await assert.rejects(c.review('app',B,'start'),/identity/)
})
test('fresh state expires and clears review/healthy feedback; no guessing after Docker failure',async()=>{
 const f=fixture();await f.c.review('app',A,'stop');f.advance(15001);f.c.tick();assert.equal(f.c.pending,null);assert.equal(values(f.c)['app_'+A+'_state'],'unknown');f.inventory.inventory_ok=false;await f.c.refresh();assert.equal(values(f.c)['app_'+A+'_state'],'unknown');await assert.rejects(f.c.review('app',A,'stop'),/unavailable/)
})
test('countdown is backend value; historical timeout is not a new failure after return',async()=>{
 const f=fixture();f.d.progress={code:'waiting_return',phase:'wait1',drive_return:{remaining_seconds:42}};await f.c.refresh();assert.equal(values(f.c).drive_drive_a_remaining_seconds,42);f.d.progress={code:'return_failed',phase:'return_failed',drive_return:{remaining_seconds:0,expired:true}};await f.c.refresh();assert.equal(values(f.c).drive_drive_a_failure,'yes');await assert.rejects(f.c.review('drive','drive-a','unmount'),/recovery is active/);f.d.progress.code='recovered';f.d.progress.phase='done';await f.c.refresh();assert.equal(values(f.c).drive_drive_a_failure,'no')
})
test('unmount review identifies running apps and images; explicit literal code, backend token and one-use confirmation',async()=>{
 const f=fixture();const p=await f.c.review('drive','drive-a','unmount');assert.match(p.text,/same-name/);assert.match(p.text,/optional-image/);assert.equal(f.client.calls.filter(v=>v.data).length,0);await assert.rejects(f.c.confirm('$(usw:review_code)'),/code/);await f.c.confirm(p.code);const sent=f.client.calls.filter(v=>v.data);assert.equal(sent.length,1);assert.deepEqual(sent[0].data,{uuid:f.d.uuid,action:'unmount',token:'one-use',confirm:true});await assert.rejects(f.c.confirm(p.code),/code/);assert.equal(f.client.calls.filter(v=>v.data).length,1)
})
test('stale review, changed identity/revision, session loss and recovery locks refuse without side effects',async()=>{
 for(const change of [f=>f.inventory.containers[0].control_block='Recovery in progress. Controls are temporarily unavailable.',f=>f.inventory.containers[0].id='c'.repeat(64),f=>f.inventory.applications.revision='r2',f=>f.client.session++]) {
  const f=fixture(),p=await f.c.review('app',A,'stop');change(f);await assert.rejects(f.c.confirm(p.code));assert.equal(f.client.calls.filter(v=>v.data).length,0)
 }
})
test('review expiry and cancellation never execute',async()=>{
 const f=fixture();let p=await f.c.review('app',A,'stop');f.advance(120001);await assert.rejects(f.c.confirm(p.code));p=await f.c.review('app',A,'stop');f.c.cancel();await assert.rejects(f.c.confirm(p.code));assert.equal(f.client.calls.filter(v=>v.data).length,0)
})
test('all guarded actions use only existing endpoints; ordinary folders need no images',async()=>{
 for(const action of ['start-monitoring','stop-monitoring','mount','start','stop','restart']) {
  const f=fixture(),kind=action.includes('monitoring')||action==='mount'?'drive':'app';if(action==='mount')f.d.mount_state='unmounted';if(action==='start')f.inventory.containers[0].state='stopped'
  const p=await f.c.review(kind,kind==='drive'?'drive-a':A,action);await f.c.confirm(p.code);const sent=f.client.calls.filter(v=>v.data);assert.equal(sent.length,1);assert.match(sent[0].path,/\/monitor$|\/disk-operation$|^docker-container-action$/)
 }
})
test('server refusal/uncertain timeout is never automatically retried',async()=>{
 for(const reason of ['refused','offline','auth']) {
  const f=fixture(),original=f.client.request;f.client.request=async function(path,data){if(data){this.calls.push({path,data});throw new ApiError('Synthetic stop failed',reason)}return original.call(this,path,data)}
  const p=await f.c.review('app',A,'stop');await assert.rejects(f.c.confirm(p.code));await f.c.refresh();assert.equal(f.client.calls.filter(v=>v.data).length,1);assert.equal(f.c.pending,null)
 }
})
test('concurrent confirmations/reviews are rejected, never queued',async()=>{
 const f=fixture(),original=f.client.request;let release;const wait=new Promise(r=>release=r);f.client.request=async function(path,data){if(data)await wait;return original.call(this,path,data)}
 const p=await f.c.review('app',A,'stop');const ongoing=f.c.confirm(p.code);await assert.rejects(f.c.confirm(p.code),/progress/);await assert.rejects(f.c.review('app',A,'stop'),/progress/);release();await ongoing;assert.equal(f.client.calls.filter(v=>v.data).length,1)
})
test('HTTP credentials restricted to localhost; URLs cannot smuggle credentials or redirects',()=>{
 assert.equal(serverURL('http://127.0.0.1:8765').hostname,'127.0.0.1');assert.equal(serverURL('https://storage.example.test:8766').protocol,'https:')
 for(const s of ['http://192.0.2.1:8765','https://user:pass@example.test','https://example.test/?token=secret','file:///tmp/token'])assert.throws(()=>serverURL(s))
})
