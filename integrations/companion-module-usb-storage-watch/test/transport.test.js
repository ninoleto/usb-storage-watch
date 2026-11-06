import test from 'node:test'
import assert from 'node:assert/strict'
import {Client,ApiError} from '../src/client.js'
import {Controller,values} from '../src/controller.js'
const token='usw_'+'s'.repeat(43),A='a'.repeat(64),U='11111111-1111-4111-8111-111111111111'
const reset=(overrides={})=>Object.assign(new ApiError('Status connection failed.','offline'),{request:{request_id:11,code:'ECONNRESET',reused_socket:true,tls_verified:true,http_status:null,...overrides}})
test('one allowlisted status retry uses a fresh connection and only the remaining deadline',async()=>{
 for(const endpoint of ['fleet-status','docker-overview','session']){
  const c=new Client({url:'https://localhost:8766'},token);c.cookie='session';const calls=[]
  c.raw=async(...args)=>{calls.push(args);if(calls.length===1){await new Promise(r=>setTimeout(r,20));throw reset()}return {status:'read'}}
  assert.deepEqual(await c.request(endpoint,undefined,100),{status:'read'});assert.equal(calls.length,2);assert.equal(calls[1][0],endpoint);assert.equal(calls[1][1],undefined);assert.ok(calls[1][2]<90 && calls[1][2]>0);assert.deepEqual(calls[1][3],{fresh:true,retryOf:11});c.close()
 }
})
test('status retry cannot exceed two attempts, cannot renew an expired deadline and cannot replay other requests',async()=>{
 for(const [endpoint,data,error,limit] of [
  ['docker-overview',undefined,reset(),2],['fleet-status',undefined,reset({reused_socket:false}),1],
  ['fleet-status',undefined,reset({tls_verified:false}),1],['fleet-status',undefined,reset({http_status:200}),1],
  ['fleet-status',undefined,reset({code:'USW_TIMEOUT'}),1],['fleet-status',undefined,reset({code:'HTTP_ERROR',http_status:503}),1],
  ['fleet-status',undefined,reset({code:'AUTHENTICATION',http_status:401}),1],['drives/disk/unmount-plan',undefined,reset(),1],
  ['fleet-status?test=1',undefined,reset(),1],['docker-container-action',{action:'stop'},reset(),1],['drives/disk/disk-operation',{action:'unmount'},reset(),1],['login',{management_token:token},reset(),1]]){
  const c=new Client({url:'https://localhost:8766'},token);c.cookie='session';let count=0;c.raw=async()=>{count++;throw error}
  await assert.rejects(c.request(endpoint,data,100));assert.equal(count,limit,endpoint);c.close()
 }
 const c=new Client({url:'https://localhost:8766'},token);c.cookie='session';let count=0
 c.raw=async()=>{count++;await new Promise(r=>setTimeout(r,20));throw reset()};await assert.rejects(c.request('session',undefined,5));assert.equal(count,1);c.close()
})
function fixture(){
 let now=1000,failure='';const writes=[]
 const client={session:1,close(){},request:async(path,data)=>{
  if(data){writes.push({path,data});return {ok:true,message:'Verified complete'}}
  if(path===failure)throw new ApiError('GET /api/'+path+': observation unavailable','unavailable')
  if(path==='session')return {username:'fixture',csrf:'synthetic'}
  if(path==='fleet-status')return {drives:[{profile_id:'disk',uuid:U,configured:true,connected:true,name:'Disk',mount_state:'mounted',monitoring:'active',standby:{state:'active'}}]}
  return {inventory_ok:true,containers:[{id:A,name:'App',state:'running',discovered:true}],applications:{settings:[],revision:'r'}}
 }}
 return {client,c:new Controller(client,()=>{},()=>now),writes,fail:v=>failure=v,advance:ms=>now+=ms}
}
test('fleet and Docker freshness expire independently and repeated partial polling preserves valid domain',async()=>{
 const f=fixture();await f.c.refresh();f.fail('docker-overview')
 for(let n=0;n<4;n++){f.advance(5000);await assert.rejects(f.c.refresh());const v=values(f.c);assert.equal(v.fleet_fresh,'yes');assert.equal(v.docker_fresh,'no');assert.equal(v.drive_disk_mount,'mounted');assert.equal(v['app_'+A+'_state'],'unknown')}
 assert.throws(()=>f.c.target('drive','disk','sleep'),/unavailable/);f.fail('');await f.c.refresh();assert.equal(values(f.c).status_fresh,'yes')
 f.fail('fleet-status');f.advance(5000);await assert.rejects(f.c.refresh());assert.equal(values(f.c)['app_'+A+'_state'],'running');assert.equal(values(f.c).drive_disk_mount,'unknown')
 f.advance(15001);f.c.tick();assert.equal(values(f.c).docker_fresh,'no');assert.equal(values(f.c)['app_'+A+'_state'],'unknown')
})
test('a fresh fleet response is published while the Docker read is still pending',async()=>{
 const f=fixture(),request=f.client.request;let release;const gate=new Promise(r=>release=r)
 f.client.request=async(path,data)=>{if(path==='docker-overview')await gate;return request(path,data)}
 const poll=f.c.refresh();await new Promise(r=>setImmediate(r));assert.equal(values(f.c).fleet_fresh,'yes');assert.equal(values(f.c).drive_disk_mount,'mounted');assert.equal(values(f.c).docker_fresh,'no');release();await poll
})
test('failed preflight reads refuse without an uncertain-command warning or a write',async()=>{
 const f=fixture();await f.c.refresh();f.fail('docker-overview');await assert.rejects(f.c.execute('drive','disk','sleep',U),/No command sent/);assert.equal(f.c.resultState,'refused');assert.equal(f.writes.length,0)
})

test('failed actual status GETs describe missing data, never an uncertain command',async()=>{
 const {default:http}=await import('node:http')
 let mode='json';const server=http.createServer((req,res)=>{req.resume();req.on('end',()=>{
  if(req.url==='/api/login'){res.setHeader('Set-Cookie','usw_session=synthetic');return res.end('{"csrf":"synthetic"}')}
  if(mode==='socket')return req.socket.destroy()
  if(mode==='timeout')return
  if(mode==='busy'){res.statusCode=503;return res.end('{"error":"Observation unavailable"}')}
  res.end('invalid JSON')
 })})
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const c=new Client({url:'http://127.0.0.1:'+server.address().port},token)
 try{for(mode of ['json','socket','timeout','busy'])await assert.rejects(c.request('docker-overview',undefined,50),e=>{assert.ok(!/uncertain|outcome|command.*resent|replay/i.test(e.message),e.message);return true})}
 finally{c.close();server.closeAllConnections();await new Promise(r=>server.close(r))}
})
