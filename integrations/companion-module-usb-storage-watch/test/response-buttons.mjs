// Actual Companion + authenticated broker/worker fixture. Never use a live host.
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
import {resolve} from 'node:path'
import {mkdirSync,writeFileSync} from 'node:fs'
import assert from 'node:assert/strict'
const require=createRequire(resolve(process.env.COMPANION_CORE,'package.json'))
const {createTRPCClient,createWSClient,wsLink}=await import(pathToFileURL(require.resolve('@trpc/client')))
const ws=createWSClient({url:'ws://127.0.0.1:18000/trpc',WebSocket:globalThis.WebSocket}),rpc=createTRPCClient({links:[wsLink({client:ws})]})
const base='http://127.0.0.1:18000/api/',out=process.env.COMPANION_OUTPUT;mkdirSync(out,{recursive:true})
const pause=ms=>new Promise(r=>setTimeout(r,ms))
const fixture=async(data)=>{const r=await fetch('https://127.0.0.1:8765/fixture',data?{method:'POST',headers:{'Content-Type':'application/json','Origin':'https://127.0.0.1:8765','X-USW-Request':'1'},body:JSON.stringify(data)}:undefined);assert.equal(r.status,200);const v=await r.json();assert.equal(v.marker,'usw-direct-real-broker-fixture');return v}
const variable=async name=>{const r=await fetch(base+'variable/Storage_Watch/'+name+'/value');assert.equal(r.status,200,name);return r.text()}
const connections=await(await fetch(base+'connections')).json(),id=connections.find(c=>c.label==='Storage_Watch').id


const traces=[],checks=[]
const sub=rpc.instances.debugLog.subscribe({instanceId:id},{onData:v=>{if(v.message.startsWith('USW request '))traces.push(JSON.parse(v.message.slice(12)))},onError:console.error})
async function waitFor(name,value){for(let n=0;n<100;n++){if(await variable(name)===value)return;if(name==='status_fresh'&&value==='yes'&&n%10===0)await fetch(base+'location/1/0/0/press',{method:'POST'});await pause(150)}throw Error(name+' expected '+value+' got '+await variable(name))}
try{
 await fixture()
 for(const [presetId,column] of [['status',0],['operate_sleep_legacy',5]])assert.ok(await rpc.controls.importPreset.mutate({connectionId:id,presetId,location:{pageNumber:1,row:0,column},variableValues:null,mode:'copy'}))
 await pause(300)
 for(const fault of ['fleet-reset','fleet-json','fleet-timeout','all-reset','post-reset']){
  await fixture({fault:'',fault_active:false,delay:0,sleep_mode:'sleep-success'})
  await fetch(base+'location/1/0/0/press',{method:'POST'});await waitFor('status_fresh','yes')
  await fixture({fault,fault_active:false});const before=await fixture(),traceStart=traces.length
  assert.equal((await fetch(base+'location/1/0/5/press',{method:'POST'})).status,200)
  await pause(fault==='fleet-timeout'?9300:1200)
  const after=await fixture(),state={label:await variable('result_label'),message:await variable('last_result'),connected:await variable('connected'),fresh:await variable('status_fresh'),connection:await variable('connection_message')}
  assert.equal(after.requests.length,before.requests.length+1,fault+' one command');assert.equal(after.workers.length,before.workers.length+1);assert.equal(after.drive.standby.sleeping,true)
  assert.equal(state.label,fault==='post-reset'?'Unknown':'Completed',fault);assert.equal(state.connected,fault==='all-reset'?'no':'yes',fault);assert.equal(state.fresh,fault==='post-reset'?'yes':'no',fault)
  const calls=traces.slice(traceStart);assert.ok(calls.some(v=>v.method==='POST'))
  assert.ok(calls.some(v=>v.code===(fault==='fleet-json'?'INVALID_JSON':fault==='fleet-timeout'?'USW_TIMEOUT':'ECONNRESET')),fault+' distinct diagnostic')
  checks.push({fault,state,calls})
 }
 await fixture({fault:'',fault_active:false});await fetch(base+'location/1/0/0/press',{method:'POST'});await waitFor('status_fresh','yes');assert.equal(await variable('result_label'),'Unknown')
 const log=JSON.stringify(checks);for(const secret of ['usw7_','usw_session','management_token','X-CSRF'])assert.ok(!log.includes(secret))
 writeFileSync(resolve(out,'response-correction.json'),JSON.stringify(checks,null,2));console.log('PASS actual Companion HTTPS: five response/status faults; verified outcomes retained, Unknown retained for lost command reply, reachability requires successful reads; no replay')
}finally{sub.unsubscribe();ws.close()}
