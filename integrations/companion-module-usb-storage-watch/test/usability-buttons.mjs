// Actual packaged Companion, HTTPS and guarded broker. Synthetic fixture ONLY.
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
import {resolve} from 'node:path'
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'
import assert from 'node:assert/strict'
const require=createRequire(resolve(process.env.COMPANION_CORE,'package.json'))
const {createTRPCClient,createWSClient,wsLink}=await import(pathToFileURL(require.resolve('@trpc/client')))
const ws=createWSClient({url:'ws://127.0.0.1:18000/trpc',WebSocket:globalThis.WebSocket}),rpc=createTRPCClient({links:[wsLink({client:ws})]})
const base='http://127.0.0.1:18000/api/',out=process.env.COMPANION_OUTPUT;mkdirSync(out,{recursive:true})
const pause=ms=>new Promise(r=>setTimeout(r,ms)),value=v=>v?.value??v
const fixture=async(data)=>{const r=await fetch('https://127.0.0.1:8765/fixture',data?{method:'POST',headers:{'Content-Type':'application/json','Origin':'https://127.0.0.1:8765','X-USW-Request':'1'},body:JSON.stringify(data)}:undefined);assert.equal(r.status,200);const v=await r.json();assert.equal(v.marker,'usw-direct-real-broker-fixture');return v}
const variable=async name=>(await fetch(base+'variable/Storage_Watch/'+name+'/value')).text()
const press=async l=>{assert.equal((await fetch(base+`location/${l.pageNumber}/${l.row}/${l.column}/press`,{method:'POST'})).status,200)}
const refresh=()=>press({pageNumber:1,row:0,column:0})
async function waitVar(name,expected){for(let i=0;i<100;i++){if(await variable(name)===expected)return;await pause(100)}throw Error(name+': '+await variable(name)+' != '+expected)}
async function config(controlId){return new Promise((res,rej)=>{const s=rpc.controls.watchControl.subscribe({controlId},{onData:v=>{if(v.type==='init'){s.unsubscribe();res(v.config)}},onError:rej})})}
async function snapshot(location,name,color){await pause(300);const image=await new Promise((res,rej)=>{const s=rpc.preview.graphics.location.subscribe({location,size:{width:72,height:72}},{onData:v=>{s.unsubscribe();res(v.image)},onError:rej})});const file=resolve(out,name+'.png');writeFileSync(file,Buffer.from(image.split(',')[1],'base64'))
 if(color!==undefined)execFileSync('python3',['-c','from PIL import Image;import sys;im=Image.open(sys.argv[1]).convert("RGB");assert im.size==(72,72);assert sum(min(p)>170 for p in list(im.convert("RGB").get_flattened_data()))>25,"No readable text rendered";c=int(sys.argv[2]);assert im.getpixel((1,1))==((c>>16)&255,(c>>8)&255,c&255),(im.getpixel((1,1)),hex(c))',file,String(color)])
}
const A='a'.repeat(64),U='11111111-1111-4111-8111-111111111111',P='drive_legacy_fs_'+U.replaceAll('-','_')+'_'
const connections=await(await fetch(base+'connections')).json(),id=connections.find(c=>c.label==='Storage_Watch').id
// Companion regenerates internal action-entity IDs on reload; command target options must stay identical.
function persistent(c){const v=structuredClone(c);for(const step of Object.values(v.steps))for(const actions of Object.values(step.action_sets))for(const action of actions)delete action.id;return v}
const saved=resolve(out,'customized-controls.json'),records=[]
try{
 await fixture()
 if(process.env.USW_RELOAD_CHECK==='1'){
  for(const entry of JSON.parse(readFileSync(saved,'utf8'))){const actual=await config(entry.id);assert.deepEqual(persistent(actual),persistent(entry.config),'customizations and targets persist after Companion restart');await snapshot(entry.location,'reload-'+entry.name)}
  await waitVar(P+'power_label','In use\nI/O observed');await snapshot(JSON.parse(readFileSync(saved))[0].location,'reload-colour',0x225577)
  console.log('PASS actual Companion reload: custom names, per-state colours, variables and exact targets retained');
 }else{
  await rpc.userConfig.setConfigKey.mutate({key:'gridSize',value:{minColumn:0,maxColumn:7,minRow:0,maxRow:5}})
  const presets=['layout_power_legacy','layout_operate_sleep_legacy','layout_app_'+A,'layout_operate_stop_'+A,'layout_mount_legacy','layout_monitor_legacy','layout_recovery_legacy']
  for(const [n,presetId] of presets.entries()){
   const location={pageNumber:1,row:3,column:n},controlId=await rpc.controls.importPreset.mutate({connectionId:id,presetId,location,variableValues:null,mode:'copy'});assert.ok(controlId)
   const c=await config(controlId);assert.equal(c.type,'button-layered');const name=c.style.layers.find(e=>e.name==='Custom name');assert.ok(name)
   const display=n===0?'Toshiba USB':n===1?'Toshiba Photo Archive USB':n===2?'Photos':n===3?'Family Photo Library Server':value(name.text)
   await rpc.controls.styles.updateOption.mutate({controlId,elementId:name.id,key:'text',value:{isExpression:false,value:display}})
   const changed=await config(controlId);assert.deepEqual(c.steps,changed.steps,'renaming cannot change command target')
   assert.equal(value(changed.style.layers.find(e=>e.name==='Custom name').text),display)
   for(const feedback of changed.feedbacks){assert.ok(feedback.definitionId.startsWith('state_'))}
   records.push({id:controlId,location,name:presetId,original:c})
  }
  const power=records[0],sleep=records[1],app=records[2],stop=records[3]
  // Edit two state colours independently using the same Companion style API as the editor.
  for(const [record,condition,color] of [[power,'idle',0x173957],[power,'in_use',0x225577],[app,'running',0x174d38]]){
   const c=await config(record.id),f=c.feedbacks.find(f=>value(f.options.state)===condition),override=f.styleOverrides[0]
   assert.ok(await rpc.controls.entities.replaceStyleOverride.mutate({controlId:record.id,entityLocation:'feedbacks',entityId:f.id,override:{...override,override:{isExpression:false,value:color}}}))
  }
  for(const [state,label,color] of [['idle','Idle\nPower ?',0x173957],['active','In use\nI/O observed',0x225577],['standby','Asleep',0x463b79],['unknown','Unknown',0x454545]]){
   await fixture({drive_patch:{standby:{state,sleeping:state==='standby',applicable:true}}});await refresh();await waitVar(P+'power_label',label);await snapshot(power.location,'power-'+state,color);await snapshot(sleep.location,'long-name-'+state)
  }
  await fixture({drive_patch:{connected:false,standby:{state:'standby',sleeping:true}}});await refresh();await waitVar(P+'power_label','Unavailable\nPower ?');await snapshot(power.location,'drive-unavailable',0x9d2222)
  await fixture({drive_patch:{},delay:1,sleep_mode:'sleep-success'});await refresh();await waitVar('status_fresh','yes')
  const before=await fixture();await press(sleep.location);await waitVar('result_label','Working');await snapshot(sleep.location,'working',0x805600);await waitVar('result_label','Completed');await pause(300)
  const after=await fixture();assert.equal(after.requests.length,before.requests.length+1);assert.equal(after.requests.at(-1).data.uuid,U);assert.equal(after.workers.length,before.workers.length+1);assert.equal(after.workers.at(-1).action,'sleep');await snapshot(sleep.location,'completed')
  // Subsequent I/O invalidates power evidence, without erasing the confirmed result.
  await fixture({drive_patch:{standby:{state:'active',sleeping:false}},delay:0});await refresh();await waitVar(P+'power_label','In use\nI/O observed');assert.equal(await variable(P+'outcome_label'),'Completed');await snapshot(power.location,'io-after-sleep',0x225577)
  await fixture({fault:'all-reset',fault_active:true});await refresh();await waitVar('connected','no');assert.equal(await variable(P+'outcome_label'),'Completed');await snapshot(power.location,'offline-grey',0x454545);await snapshot(sleep.location,'offline-completed')
  await fixture({fault:'fleet-json',fault_active:true});await refresh();await waitVar('connected','yes');await waitVar('status_fresh','no');assert.equal(await variable(P+'outcome_label'),'Completed');await snapshot(power.location,'stale-grey',0x454545)
  await fixture({fault:'',fault_active:false});await refresh();await waitVar('status_fresh','yes');await snapshot(power.location,'recovered-colour',0x225577)
  await snapshot(app.location,'app-custom-running',0x174d38)
  const beforeStop=await fixture();await press(stop.location);await waitVar('app_'+A+'_state','stopped');await waitVar('result_label','Completed');const afterStop=await fixture();assert.equal(afterStop.requests.length,beforeStop.requests.length+1);assert.equal(afterStop.requests.at(-1).data.id,A);await snapshot(app.location,'app-stopped',0x172f49);await snapshot(stop.location,'long-app-stopped')
  await fixture({app_patch:{[A]:{state:'running'}}});await refresh();await waitVar('app_'+A+'_state','running');await snapshot(app.location,'app-state-update',0x174d38)
  for(const record of records){record.config=await config(record.id);assert.deepEqual(record.config.steps,record.original.steps);delete record.original}
  writeFileSync(saved,JSON.stringify(records,null,2));console.log('PASS actual Companion: separate text edits, editable per-state colours, 72x72 renders, pinned one-press workers, state/stale/offline updates and preserved command result')
 }
}finally{ws.close()}
