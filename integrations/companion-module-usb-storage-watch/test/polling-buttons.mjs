// Actual Companion -> production Gunicorn HTTPS -> authenticated real broker,
// simulated storage/Docker only. Idle closure is observed, never injected here.
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
const variable=async name=>(await fetch(base+'variable/Storage_Watch/'+name+'/value')).text()
const press=async(row,column)=>assert.equal((await fetch(base+`location/1/${row}/${column}/press`,{method:'POST'})).status,200)
async function waitVar(name,value){for(let n=0;n<100;n++){if(await variable(name)===value)return;await pause(100)}throw Error(name+' expected '+value+' got '+await variable(name))}
const connections=await(await fetch(base+'connections')).json(),id=connections.find(c=>c.label==='Storage_Watch').id
const traces=[],samples=[],A='a'.repeat(64)
const sub=rpc.instances.debugLog.subscribe({instanceId:id},{onData:v=>{if(v.message.startsWith('USW request '))traces.push({...JSON.parse(v.message.slice(12)),observed_at:Date.now()})}})
const state=async()=>({fleet:await variable('fleet_fresh'),docker:await variable('docker_fresh'),drive:await variable('drive_legacy_mount'),app:await variable('app_'+A+'_state'),result:await variable('result_label'),connected:await variable('connected'),connection:await variable('connection_message')})
try{
 const initial=await fixture();assert.equal(initial.requests.length,0,'Fresh fixture required')
 await press(3,1);await waitVar('result_label','Completed');assert.equal((await fixture()).workers.length,1)
 const start=traces.length
 // Ordinary scheduled polls, followed by reads near the server's real 2 s idle deadline.
 for(let n=0;n<30;n++){await pause(n<6?5000:2000);if(n>=6)await press(0,0);else samples.push(await state());if(n>=17 && traces.slice(start).filter(v=>v.code==='ECONNRESET'&&v.reused_socket).length>=2)break}
 await pause(150);samples.push(await state())
 await pause(150)
 const polling=traces.slice(start),resets=polling.filter(v=>v.code==='ECONNRESET'&&v.reused_socket&&v.method==='GET')
 const server=await(await fetch('https://127.0.0.1:8765/fixture/transport')).json()
 writeFileSync(resolve(out,'idle-polling.json'),JSON.stringify({polling,samples,server},null,2))
 assert.ok(resets.length>0,'Actual idle-close reuse race must be exercised')
 assert.ok(server.events.some(v=>v.event==='idle-close'))
 for(const r of resets){const retry=polling.filter(v=>v.retry_of===r.request_id);assert.equal(retry.length,1);assert.equal(retry[0].attempt,2);assert.equal(retry[0].reused_socket,false);assert.equal(retry[0].tls_verified,true);assert.equal(retry[0].http_status,200);assert.ok(r.elapsed_ms+retry[0].elapsed_ms<8000)}
 assert.ok(samples.every(v=>v.fleet==='yes'&&v.docker==='yes'&&v.result==='Completed'))
 assert.equal((await fixture()).requests.length,1,'Polling never replays a command')
 console.log('PASS natural HTTPS idle-close timing: '+resets.length+' reused-socket resets; one verified fresh GET retry each; no status drop or command replay')
 // The real Broker.handle error mapping, independently from transport closure.
 await fixture({fault:'docker-503'});await press(0,0);await waitVar('docker_fresh','no')
 for(let n=0;n<4;n++){await pause(5000);const v=await state();assert.equal(v.fleet,'yes');assert.equal(v.docker,'no');assert.equal(v.drive,'mounted');assert.equal(v.app,'unknown');assert.equal(v.result,'Completed');assert.equal(v.connected,'yes');assert.match(v.connection,/Drive operation unavailable/);assert.ok(!/outcome.*unverified|uncertain|command was resent/i.test(v.connection));samples.push(v)}
 const refusals=traces.filter(v=>v.http_status===503);assert.ok(refusals.length>=3);assert.ok(refusals.every(v=>!traces.some(next=>next.retry_of===v.request_id)))
 await fixture({fault:'fleet-json',fault_active:true});await press(0,0);await waitVar('fleet_fresh','no');await waitVar('docker_fresh','yes');assert.equal(await variable('app_'+A+'_state'),'running');assert.equal(await variable('drive_legacy_mount'),'unknown')
 await fixture({fault:'all-reset',fault_active:true});await press(0,0);await waitVar('connected','no');assert.equal(await variable('result_label'),'Completed')
 await fixture({fault:'',fault_active:false});await press(0,0);await waitVar('status_fresh','yes')
 const before=await fixture();await fixture({fault:'post-reset',fault_active:false});await press(3,1);await waitVar('result_label','Unknown');await waitVar('status_fresh','yes')
 const after=await fixture();assert.equal(after.requests.length,before.requests.length+1);assert.equal(after.workers.length,before.workers.length+1);assert.equal(await variable('connected'),'yes')
 const posts=traces.filter(v=>v.method==='POST'&&v.operation==='sleep');assert.equal(posts.length,2);assert.ok(posts.every(v=>v.attempt===1&&!v.retry_of))
 assert.equal(posts.at(-1).code,'ECONNRESET');await press(0,0);await pause(300);assert.equal(await variable('result_label'),'Unknown')
 const serialized=JSON.stringify(traces);for(const secret of ['usw7_','usw_session','management_token','X-CSRF'])assert.ok(!serialized.includes(secret))
 writeFileSync(resolve(out,'polling-validation.json'),JSON.stringify({traces,samples,workers:after.workers,requests:after.requests},null,2))
 console.log('PASS actual Companion: independent freshness, repeated broker 503, JSON/stale/offline recovery, retained results and lost POST reply without replay')
}finally{sub.unsubscribe();ws.close()}
