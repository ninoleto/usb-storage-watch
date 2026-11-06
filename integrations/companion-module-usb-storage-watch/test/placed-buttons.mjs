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
const fixture=async(data)=>{const r=await fetch('http://127.0.0.1:8765/fixture',data?{method:'POST',headers:{'Content-Type':'application/json','Origin':'http://127.0.0.1:8765','X-USW-Request':'1'},body:JSON.stringify(data)}:undefined);assert.equal(r.status,200);const v=await r.json();assert.equal(v.marker,'usw-direct-real-broker-fixture');return v}
const variable=async name=>{const r=await fetch(base+'variable/Storage_Watch/'+name+'/value');assert.equal(r.status,200,name);return r.text()}
const connections=await(await fetch(base+'connections')).json(),id=connections.find(c=>c.label==='Storage_Watch').id
const slots=new Map();let next=0
async function place(preset){const index=next++,location={pageNumber:1,row:Math.floor(index/8),column:index%8};slots.set(preset,location);assert.ok(await rpc.controls.importPreset.mutate({connectionId:id,presetId:preset,location,variableValues:null,mode:'copy'}))}
async function press(preset){const l=slots.get(preset);const r=await fetch(base+`location/${l.pageNumber}/${l.row}/${l.column}/press`,{method:'POST'});assert.equal(r.status,200);await pause(90)}
async function waitVar(name,value){for(let i=0;i<100;i++){if(await variable(name)===value)return;await pause(150)}throw Error(name+' expected '+value+' got '+await variable(name)+'; '+await variable('last_result'))}
async function screenshot(preset,name){await pause(180);const location=slots.get(preset);const image=await new Promise((res,rej)=>{let s=rpc.preview.graphics.location.subscribe({location,size:{width:72,height:72}},{onData:v=>{s.unsubscribe();res(v.image)},onError:rej})});assert.ok(image.startsWith('data:image/png;base64,'));writeFileSync(resolve(out,name+'.png'),Buffer.from(image.split(',')[1],'base64'))}
const A='a'.repeat(64),B='b'.repeat(64),C='c'.repeat(64),checks=[]
const presets=['status','drive_legacy','monitor_legacy','recovery_legacy','hdd_legacy','operate_sleep_legacy','operate_mount_legacy','operate_unmount_legacy','operate_start-monitoring_legacy','operate_stop-monitoring_legacy','app_'+A,'operate_start_'+A,'operate_stop_'+A,'operate_restart_'+A,'result']
async function operate(preset,expected='Completed'){
 const before=await fixture();await press(preset);await waitVar('result_label',expected);assert.equal(await variable('review_pending'),'no')
 const after=await fixture();assert.equal(after.requests.length,before.requests.length+1,preset+' exactly one broker command');checks.push({preset,result:expected,reason:await variable('last_result'),workers:after.workers.slice(before.workers.length)});return after
}
try{
 const first=await fixture();assert.equal(first.drive.uuid,'11111111-1111-4111-8111-111111111111');assert.equal(first.requests.length,0,'Fresh fixture required')
 assert.equal(connections.find(c=>c.id===id).status.level,'ok')
 await rpc.userConfig.setConfigKey.mutate({key:'gridSize',value:{minColumn:0,maxColumn:7,minRow:0,maxRow:3}})
 for(const p of presets)await place(p)
 await press('status');await waitVar('drive_legacy_hdd','awake');await screenshot('drive_legacy','mounted');await screenshot('app_'+A,'app-running');await screenshot('operate_sleep_legacy','sleep-button')
 // Single press reaches the actual _manual standby worker. No review/code action.
 await fixture({delay:1});await press('operate_sleep_legacy');await waitVar('result_label','Working');await screenshot('operate_sleep_legacy','working-button');await screenshot('result','working-result')
 await waitVar('result_label','Completed');let f=await fixture();assert.equal(f.requests.length,1);assert.deepEqual(f.workers.map(w=>w.action),['sleep']);assert.match(f.sleep_events,/users\nsync\nusers\n-y\n-C/);checks.push({preset:'operate_sleep_legacy',result:'Completed',workers:f.workers})
 await waitVar('drive_legacy_hdd','asleep');await screenshot('hdd_legacy','hdd-asleep');await screenshot('operate_sleep_legacy','completed-button');await screenshot('result','completed-result')
 await fixture({delay:0,sleep_mode:'sleep-busy'});f=await operate('operate_sleep_legacy','Refused');assert.match(await variable('last_result'),/writer PID 123/);assert.equal(f.sleep_events.match(/\n-y\n/g).length,1);await screenshot('operate_sleep_legacy','refused-button');await screenshot('result','refused-result')
 let detail='';for(let n=0;n<8;n++){detail+=await variable('result_button');await press('result')};assert.match(detail,/123/)
 await operate('operate_stop_'+A);await waitVar('app_'+A+'_state','stopped');await screenshot('app_'+A,'app-stopped')
 await operate('operate_start_'+A);await waitVar('app_'+A+'_state','running');await operate('operate_restart_'+A)
 await operate('operate_stop-monitoring_legacy');await waitVar('drive_legacy_monitor_label','Monitor OFF');await screenshot('monitor_legacy','monitor-off')
 await operate('operate_start-monitoring_legacy');await waitVar('drive_legacy_monitor_label','Monitor ON');await screenshot('monitor_legacy','monitor-on')
 const workersBefore=(await fixture()).workers.length;await fixture({fail_stop:true});f=await operate('operate_unmount_legacy','Refused');assert.equal(f.workers.length,workersBefore);assert.equal(f.drive.mount_state,'mounted');assert.match(await variable('last_result'),/stop|stopp/i)
 await fixture({fail_stop:false});f=await operate('operate_unmount_legacy');assert.equal(f.workers.at(-1).action,'unmount');assert.equal(f.drive.mount_state,'unmounted');assert.equal(f.apps[A].running,false);assert.equal(f.apps[C].running,false);assert.equal(f.apps[B].running,true);assert.match(f.unmount_events,/unmount:image[\s\S]*unmount:disk/);assert.equal(f.receipt.phase,'complete');await screenshot('drive_legacy','unmounted')
 f=await operate('operate_mount_legacy');assert.equal(f.workers.at(-1).action,'mount');assert.match(f.mount_events,/mount:disk\nmount:image\nverify:storage/);assert.equal(f.drive.mount_state,'mounted');assert.equal(f.apps[A].running,false);assert.equal(f.apps[C].running,false)
 await operate('operate_start_'+A);f=await fixture();assert.equal(f.apps[A].running,true);assert.equal(f.apps[C].running,false)
 // Race: status allows it, incident begins only inside the mutating broker request.
 const dockerBefore=f.docker_calls.length;await fixture({race:true});f=await operate('operate_stop_'+A,'Refused');assert.equal(f.docker_calls.length,dockerBefore);assert.equal(f.apps[A].running,true);assert.match(await variable('last_result'),/Recovery in progress/);await screenshot('result','recovery-refusal');await fixture({race:false})
 assert.equal(await variable('review_pending'),'no');assert.equal(f.apps[B].running,true)
 writeFileSync(resolve(out,'summary.json'),JSON.stringify({placed:presets.length,checks,requests:f.requests,workers:f.workers,unmount_events:f.unmount_events,mount_events:f.mount_events,sleep_events:f.sleep_events,docker_calls:f.docker_calls},null,2))
 console.log('PASS actual packaged presets in Companion: '+presets.length+' placed buttons, '+checks.length+' single-press commands, real authenticated broker/worker IPC, simulated storage/Docker only')
}catch(e){writeFileSync(resolve(out,'failure.json'),JSON.stringify({message:e.message,result:await variable('last_result'),fixture:await fixture()},null,2));throw e}finally{ws.close()}
