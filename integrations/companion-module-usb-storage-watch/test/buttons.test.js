import test from 'node:test'
import assert from 'node:assert/strict'
import { Controller, values } from '../src/controller.js'
import {presetsFor,controlFeedback} from '../src/buttons.js'
const A='a'.repeat(64),D='drive-a'
function fixture(){
 const drive={configured:true,profile_id:D,uuid:'11111111-1111-4111-8111-111111111111',name:'External Toshiba Long Name',connected:true,mount_state:'mounted',monitoring:'active',standby:{state:'idle',applicable:true},progress:{code:'healthy',phase:'done'}}
 const app={id:A,name:'my-application',state:'running',discovered:true}
 let now=1000;const writes=[]
 const client={session:1,close(){},scrub:v=>v,request:async(path,data)=>{if(data){writes.push({path,data});return {ok:true,message:'Verified outcome'}}if(path==='fleet-status')return {drives:[structuredClone(drive)]};if(path==='docker-overview')return {inventory_ok:true,containers:[structuredClone(app)],applications:{revision:'1',settings:[]}};return {token:'backend-review',apps:[{id:A,name:'my-application',running:true,images:['files']}],message:'Apps stay stopped.'}}}
 const c=new Controller(client,()=>{},()=>now);return {c,drive,app,writes,advance:ms=>now+=ms}
}
test('each pinned target has complete action/status presets and actual newline/label variables',async()=>{
 const f=fixture();await f.c.refresh();const {presets}=presetsFor(f.c,'Renamed_USW')
 for(const verb of ['sleep','mount','unmount','start-monitoring','stop-monitoring'])assert.deepEqual(presets['operate_'+verb+'_'+D].steps[0].down[0],{actionId:'drive_'+verb.replaceAll('-','_'),options:{drive:JSON.stringify([D,f.drive.uuid])}})
 for(const verb of ['start','stop','restart'])assert.equal(presets['operate_'+verb+'_'+A].steps[0].down[0].options.app,A)
 assert.match(presets['drive_'+D].style.text,/\$\(Renamed_USW:/);assert.ok(presets['drive_'+D].style.text.includes('\n'));assert.ok(!presets['drive_'+D].style.text.includes('\\n'))
 assert.equal(presets.confirm_keypad,undefined);assert.equal(presets.digit_5,undefined)
})
test('button keypad requires reading pages and literal digits, expires and cannot replay',async()=>{
 const f=fixture(),p=await f.c.review('drive',D,'unmount');assert.throws(()=>f.c.digit('1'),/Read all/)
 assert.ok(p.pages.every(page=>page.split('\n').length<=4))
 assert.ok(p.pages.slice(0,-1).every(page=>page.split('\n').every(line=>line.length<=11)))
 while(p.page<p.pages.length-1)f.c.reviewNext();assert.match(values(f.c).review_button,new RegExp(p.code))
 assert.throws(()=>f.c.digit('$(USW:review_code)'),/six digits/)
 for(const digit of p.code)f.c.digit(digit)
 assert.match(values(f.c).confirm_button,new RegExp(p.code));await f.c.confirmEntered();assert.equal(f.writes.length,1);assert.equal(f.writes[0].data.token,'backend-review')
 assert.throws(()=>f.c.confirmEntered());assert.equal(f.writes.length,1)
 const p2=await f.c.review('drive',D,'unmount');while(p2.page<p2.pages.length-1)f.c.reviewNext();f.c.digit('2');f.c.digit('back');assert.equal(p2.entered,'');f.advance(120001);assert.throws(()=>f.c.digit('1'));assert.equal(f.c.pending,null)
})
test('manual sleep dispatches sleep directly after confirmation, with no idle-setting or monitoring write',async()=>{
 const f=fixture(),p=await f.c.review('drive',D,'sleep');assert.match(p.text,/without waiting/);await f.c.confirm(p.code)
 assert.deepEqual(f.writes,[{path:'drives/drive-a/disk-operation',data:{uuid:f.drive.uuid,action:'sleep'}}]);assert.equal(f.c.resultState,'success')
})
test('HDD evidence is conservative; changing status drives feedback; pending/error never means success',async()=>{
 const f=fixture();await f.c.refresh();assert.equal(values(f.c).drive_drive_a_hdd,'unknown')
 f.drive.standby={state:'active'};await f.c.refresh();assert.equal(values(f.c).drive_drive_a_hdd,'awake')
 f.drive.standby={state:'standby',sleeping:true};await f.c.refresh();assert.equal(values(f.c).drive_drive_a_hdd,'asleep');assert.equal(controlFeedback(f.c,'drive',D,'hdd').bgcolor,0x463b79)
 await f.c.review('app',A,'stop');assert.equal(controlFeedback(f.c,'app',A,'state').bgcolor,0x805600);f.c.cancel()
 f.c.fail({message:'Busy: process holds the drive'});assert.equal(controlFeedback(f.c,'app',A,'state').bgcolor,0x9d2222);assert.match(values(f.c).result_button,/Failed/);f.c.resultNext();assert.match(values(f.c).last_result,/process/)
 f.drive.connected=false;await f.c.refresh();assert.equal(values(f.c).drive_drive_a_hdd,'unknown');assert.equal(values(f.c).drive_drive_a_mount_label,'Unavailable')
 f.c.invalidate('Lost connection');assert.equal(values(f.c)['app_'+A+'_state'],'unknown');assert.equal(values(f.c).drive_drive_a_monitor_label,'Monitor ?')
})
test('sleep refuses recovery locks, absent storage and unsupported media before write',async()=>{
 for(const patch of [{connected:false},{standby:{state:'not-applicable'}},{progress:{code:'running'}}]){const f=fixture();Object.assign(f.drive,patch);await assert.rejects(f.c.review('drive',D,'sleep'));assert.equal(f.writes.length,0)}
})
