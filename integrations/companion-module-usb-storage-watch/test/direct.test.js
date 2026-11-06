import test from 'node:test'
import assert from 'node:assert/strict'
import {Controller,values} from '../src/controller.js'
import {ApiError} from '../src/client.js'
import {presetsFor} from '../src/buttons.js'
const A='a'.repeat(64),U='11111111-1111-4111-8111-111111111111'
function setup(){
 const drive={configured:true,profile_id:'disk',uuid:U,name:'Disk',connected:true,mount_state:'mounted',monitoring:'active',standby:{state:'idle'},progress:{code:'healthy'}}
 const app={id:A,name:'Application',state:'running',discovered:true},calls=[]
 const client={session:1,close(){},scrub:v=>v,request:async function(path,data){calls.push({path,data});if(data)return {ok:true,message:'Verified completion'};if(path==='fleet-status')return {drives:[structuredClone(drive)]};if(path==='docker-overview')return {inventory_ok:true,containers:[structuredClone(app)],applications:{revision:'1',settings:[]}};return {token:'single-use',apps:[],message:'Dependent apps stop; storage unmounts.'}}}
 const c=new Controller(client);return {c,client,drive,app,calls,writes:()=>calls.filter(v=>v.data)}
}
test('all supplied operating presets have exactly one direct action and pinned identity; no keypad offered',async()=>{
 const f=setup();await f.c.refresh();const {structure,presets}=presetsFor(f.c,'USW');const offered=structure.flatMap(s=>s.definitions)
 assert.ok(!offered.includes('confirm_keypad'));assert.ok(!offered.includes('review'));assert.ok(!offered.some(id=>id.startsWith('digit_')))
 for(const [kind,id,verbs] of [['drive','disk',['sleep','mount','unmount','start-monitoring','stop-monitoring']],['app',A,['start','stop','restart']]])for(const verb of verbs){const p=presets['operate_'+verb+'_'+id];assert.ok(offered.includes('operate_'+verb+'_'+id));assert.equal(p.steps[0].down.length,1);assert.equal(p.steps[0].down[0].actionId,kind+'_'+verb.replaceAll('-','_'));assert.equal(p.steps[0].down[0].options[kind],kind==='drive'?JSON.stringify([id,U]):A)}
 assert.deepEqual(Object.keys(presets).sort(),offered.toSorted()) // No hidden review/keypad presets.
})
test('one execute calls each endpoint without review/keypad, and only verified reply is Completed',async()=>{
 for(const verb of ['sleep','mount','unmount','start-monitoring','stop-monitoring','start','stop','restart']){
  const f=setup(),kind=['start','stop','restart'].includes(verb)?'app':'drive';if(verb==='mount')f.drive.mount_state='unmounted';if(verb==='start')f.app.state='stopped'
  f.c.review=()=>assert.fail('No user review workflow');f.c.confirm=()=>assert.fail('No code workflow')
  await f.c.execute(kind,kind==='drive'?'disk':A,verb,kind==='drive'?U:undefined)
  assert.equal(f.writes().length,1);assert.equal(f.c.pending,null);assert.equal(values(f.c).result_label,'Completed')
  if(verb==='unmount'){assert.equal(f.writes()[0].data.token,'single-use');assert.equal(f.writes()[0].data.confirm,true)}
 }
})
test('wrong UUID, missing app and recovery lock refuse before any write',async()=>{
 for(const scenario of ['uuid','missing','lock']){const f=setup();if(scenario==='missing')f.app.id='b'.repeat(64);if(scenario==='lock')f.app.control_block='Recovery in progress';await assert.rejects(f.c.execute(scenario==='uuid'?'drive':'app',scenario==='uuid'?'disk':A,scenario==='uuid'?'sleep':'stop',scenario==='uuid'?'different':undefined));assert.equal(f.writes().length,0);assert.equal(values(f.c).result_label,'Refused')}
})
test('safe unmount rechecks session and selections after obtaining token; never auto-reviews a changed plan',async()=>{
 for(const change of [f=>f.client.session++,f=>f.drive.uuid='other',f=>f.app.control_block='Recovery']){
  const f=setup(),request=f.client.request;f.client.request=async function(path,data){const v=await request(path,data);if(path.includes('unmount-plan'))change(f);if(path==='docker-overview'&&f.app.control_block)v.applications.revision='2';return v}
  await assert.rejects(f.c.execute('drive','disk','unmount',U));assert.equal(f.writes().length,0);assert.equal(f.calls.filter(v=>v.path.includes('unmount-plan')).length,1)
 }
})
test('Working stays pending until response; duplicate press never queues another command',async()=>{
 const f=setup(),request=f.client.request;let release;const blocked=new Promise(r=>release=r);f.client.request=async(path,data)=>{if(data)await blocked;return request(path,data)}
 const ongoing=f.c.execute('drive','disk','sleep',U);assert.equal(values(f.c).result_label,'Working');await assert.rejects(f.c.execute('drive','disk','sleep',U),/nothing was queued/);assert.equal(values(f.c).result_label,'Working');release();await ongoing;assert.equal(f.writes().length,1)
})
test('busy refusal, worker failure and transport loss never report Completed or retry',async()=>{
 for(const mode of ['busy','failed','offline']){const f=setup(),request=f.client.request;f.client.request=async(path,data)=>{const result=await request(path,data);if(data){if(mode==='offline')throw new ApiError('Transport lost','offline');return {ok:false,result:mode,message:'Writer prevents standby'}}return result};await assert.rejects(f.c.execute('drive','disk','sleep',U));assert.equal(values(f.c).result_label,mode==='busy'?'Refused':mode==='failed'?'Failed':'Unknown');assert.equal(f.c.pending,null);await f.c.refresh();assert.equal(f.writes().length,1)}
})
