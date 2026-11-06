import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import {Controller,values} from '../src/controller.js'
import {Client,ApiError} from '../src/client.js'
const A='a'.repeat(64),U='11111111-1111-4111-8111-111111111111'
function setup(){
 const calls=[],client={session:1,close(){},request:async(path,data)=>{calls.push({path,data});if(data)return {ok:true,message:'HDD standby confirmed.'};if(path==='session')return {username:'fixture',csrf:'private'};return path==='fleet-status'?{drives:[{configured:true,profile_id:'disk',uuid:U,name:'Disk',connected:true,mount_state:'mounted',progress:{code:'healthy'}}]}:{inventory_ok:true,containers:[{id:A,name:'App',state:'running',discovered:true}]}}}
 return {client,calls,c:new Controller(client)}
}
test('confirmed command outcome survives subsequent status socket/parse/timeout errors; successful sibling proves reachability',async()=>{
 for(const endpoint of ['fleet-status','docker-overview'])for(const cause of ['ECONNRESET','INVALID_JSON','USW_TIMEOUT']){
  const f=setup(),request=f.client.request;let sent=false
  f.client.request=async(path,data)=>{if(data){sent=true;return request(path,data)}if(sent&&path===endpoint)throw new ApiError('GET /api/'+endpoint+': '+cause,'offline');return request(path,data)}
  await f.c.execute('drive','disk','sleep',U)
  const v=values(f.c);assert.equal(v.result_label,'Completed');assert.equal(v.last_result,'HDD standby confirmed.');assert.equal(v.connected,'yes');assert.equal(v.status_fresh,'no');assert.match(v.connection_message,new RegExp(cause));assert.equal(v.drive_disk_mount,endpoint==='docker-overview'?'mounted':'unknown');assert.equal(v['app_'+A+'_state'],endpoint==='fleet-status'?'running':'unknown');assert.equal(f.calls.filter(v=>v.data).length,1)
 }
})
test('both inventory reads fail: authenticated session proves only server reachability, never storage readiness',async()=>{
 const f=setup(),request=f.client.request;await f.c.refresh()
 f.client.request=async(path,data)=>{if(path!=='session')throw new ApiError('Busy inventory','unavailable');return request(path,data)}
 await assert.rejects(f.c.refresh());assert.equal(values(f.c).connected,'yes');assert.equal(values(f.c).status_fresh,'no');assert.equal(values(f.c).drive_disk_mount,'unknown')
 f.client.request=async()=>{throw new ApiError('Socket lost','offline')};await assert.rejects(f.c.refresh());assert.equal(values(f.c).connected,'no')
})
test('lost command response remains Unknown after successful reads and is never resent',async()=>{
 const f=setup(),request=f.client.request
 f.client.request=async(path,data)=>{const v=await request(path,data);if(data)throw new ApiError('POST /api/drives/disk/disk-operation: ECONNRESET','offline');return v}
 await assert.rejects(f.c.execute('drive','disk','sleep',U));assert.equal(values(f.c).result_label,'Unknown');assert.equal(values(f.c).connected,'yes');assert.equal(values(f.c).status_fresh,'yes');assert.equal(f.calls.filter(v=>v.data).length,1)
})
test('poll failure during a working command never replaces Working, and a fresh read follows the older poll',async()=>{
 const f=setup(),request=f.client.request;let release,started;const waiting=new Promise(r=>release=r),sent=new Promise(r=>started=r)
 f.client.request=async(path,data)=>{if(data){started();await waiting}return request(path,data)}
 const command=f.c.execute('drive','disk','sleep',U);await sent
 const broken=f.client.request;f.client.request=async(path,data)=>{if(!data)throw new ApiError('GET unavailable','offline');return broken(path,data)}
 await assert.rejects(f.c.refresh());assert.equal(values(f.c).result_label,'Working')
 f.client.request=broken;release();await command;assert.equal(values(f.c).result_label,'Completed');assert.equal(values(f.c).connected,'yes');assert.equal(f.calls.filter(v=>v.data).length,1)
})
test('a refresh already pending at completion is followed by a new read, without repeating the command',async()=>{
 const f=setup(),request=f.client.request;let complete,started,readDone,readStarted
 const commandGate=new Promise(r=>complete=r),commandSent=new Promise(r=>started=r),readGate=new Promise(r=>readDone=r),pollStarted=new Promise(r=>readStarted=r);let blockRead=false
 f.client.request=async(path,data)=>{if(data){started();await commandGate}else if(blockRead){readStarted();await readGate}return request(path,data)}
 const command=f.c.execute('drive','disk','sleep',U);await commandSent;blockRead=true;const poll=f.c.refresh();await pollStarted;complete();await new Promise(r=>setImmediate(r));blockRead=false;readDone();await poll;await command
 assert.equal(f.calls.filter(v=>v.path==='fleet-status').length,3);assert.equal(f.calls.filter(v=>v.data).length,1)
})
test('bounded request diagnostics distinguish status, parse, socket and timeout failures without credentials or replay',async()=>{
 const token='usw_'+'s'.repeat(43),seen=[],diagnostics=[]
 const server=http.createServer((req,res)=>{req.resume();req.on('end',()=>{
  seen.push(req.url);res.setHeader('Content-Type','application/json')
  if(req.url==='/api/login'){res.setHeader('Set-Cookie','usw_session=private-cookie');return res.end('{"csrf":"private-csrf"}')}
  if(req.url==='/api/busy'){res.statusCode=503;return res.end('{"error":"Backend busy"}')}
  if(req.url==='/api/null')return res.end('null')
  if(req.url==='/api/bad-json')return res.end('not json')
  if(req.url==='/api/socket')return req.socket.destroy()
  if(req.url==='/api/timeout')return
  res.end('{"ok":true,"message":"Verified"}')
 })})
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const c=new Client({url:`http://127.0.0.1:${server.address().port}`},token,v=>diagnostics.push(v))
 try{
  for(const [path,code,status,kind] of [['busy','HTTP_ERROR',503,'unavailable'],['bad-json','INVALID_JSON',200,'offline'],['null','INVALID_RESPONSE',200,'offline'],['socket','ECONNRESET',null,'offline'],['timeout','USW_TIMEOUT',null,'offline']]){
   await assert.rejects(c.request(path,{action:'sleep'},50),e=>{assert.equal(e.kind,kind);assert.equal(e.request.code,code);assert.equal(e.request.http_status,status);assert.equal(e.request.endpoint,'/api/'+path);assert.match(e.message,new RegExp('POST /api/'+path));return true})
  }
  assert.equal(seen.length,6);assert.equal(diagnostics.length,6);assert.ok(diagnostics.every(v=>v.elapsed_ms>=0))
  const log=JSON.stringify(diagnostics);for(const secret of [token,'private-cookie','private-csrf','management_token','Cookie'])assert.ok(!log.includes(secret))
 }finally{c.close();server.closeAllConnections();await new Promise(r=>server.close(r))}
})
test('reachability expires without new successful reads, independently of a completed operation',async()=>{
 const f=setup();let now=1000;f.c.now=()=>now;await f.c.execute('drive','disk','sleep',U);now+=15001;f.c.tick();assert.equal(values(f.c).connected,'no');assert.equal(values(f.c).result_label,'Completed')
})
