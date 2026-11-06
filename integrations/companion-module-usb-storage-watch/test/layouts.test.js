import test from 'node:test'
import assert from 'node:assert/strict'
import { Controller,values } from '../src/controller.js'
import { presetsFor,booleanFeedbacks } from '../src/layouts.js'
import { presetsFor as oldPresets } from '../src/buttons.js'
import { driveStatus,COLORS,observedState,pinnedPrefix } from '../src/status.js'
const D={id:'drive',uuid:'11111111-1111-4111-8111-111111111111',name:'A long external drive name',known:true,connected:true,mount_state:'mounted',monitoring:'active',standby:{state:'idle'},progress:{code:'healthy'}}
const A={id:'a'.repeat(64),name:'Example app',known:true,state:'running',discovered:true}
function setup(){const c=new Controller({},()=>{},()=>1000);c.state={drives:[structuredClone(D)],apps:[structuredClone(A)]};for(const o of Object.values(c.observations))Object.assign(o,{valid:true,at:1000});return c}
test('new elements separate editable text, status and actions; old definitions are preserved',()=>{
 const c=setup(),next=presetsFor(c,'USW'),old=oldPresets(c,'USW')
 for(const [id,p] of Object.entries(old.presets))assert.deepEqual(next.presets[id],p)
 const shown=next.structure.flatMap(g=>g.definitions);assert.ok(!shown.includes('operate_sleep_drive'))
 for(const id of ['layout_operate_sleep_drive','layout_operate_stop_'+A.id]){
  const p=next.presets[id],snapshot=structuredClone(p.steps)
  assert.equal(p.type,'layered');assert.deepEqual(p.elements.filter(e=>e.type==='text').map(e=>e.name),['Custom name','Live status','Action','Command outcome'])
  const name=p.elements.find(e=>e.id==='custom-name');assert.equal(typeof name.text,'string');assert.ok(!name.text.includes('111111'));name.text='Toshiba USB'
  assert.deepEqual(p.steps,snapshot);assert.equal(p.elements.find(e=>e.id==='live-status').text.isExpression,true)
  assert.ok(p.elements.filter(e=>e.type==='text').every(e=>e.fontsizeAllowShrink && e.width>80 && e.height>=10 && e.y+e.height<=100))
  assert.ok(p.feedbacks.every(f=>f.feedbackId.startsWith('state_') && f.styleOverrides.length))
 }
})
test('state feedbacks are normal booleans with editable defaults and pinned identities',()=>{
 const c=setup(),defs=booleanFeedbacks(c,(id,label,choices)=>({id,label,choices}))
 assert.ok(Object.values(defs).every(d=>d.type==='boolean' && d.defaultStyle))
 const cb=defs.state_power.callback,target=JSON.stringify([D.id,D.uuid])
 assert.equal(cb({options:{target,state:'idle'}}),true);assert.equal(cb({options:{target:JSON.stringify([D.id,'replacement']),state:'idle'}}),false)
 assert.equal(cb({options:{target:JSON.stringify([D.id,'replacement']),state:'unknown'}}),true)
 const p=presetsFor(c,'USW').presets.layout_power_drive
 for(const [state,color] of [['idle','idle'],['asleep','asleep'],['in_use','in_use'],['unknown','unknown'],['unavailable','fault']])assert.equal(p.feedbacks.find(f=>f.options.state===state).styleOverrides[0].override,COLORS[color])
 const p2=presetsFor(c,'USW').presets.layout_operate_sleep_drive
 assert.equal(p2.feedbacks.find(f=>f.options.state==='running').styleOverrides[0].override,COLORS.working)
})
test('current passive evidence separates idle/activity/power from old standby receipts',()=>{
 for(const [standby,power,activity,power_state] of [
  [{state:'idle',sleeping:true,time:'old'},'idle','idle','unknown'],
  [{state:'active',sleeping:true,time:'old'},'in_use','in_use','awake'],
  [{state:'standby',sleeping:false},'unknown','unknown','unknown'],
  [{state:'standby',sleeping:true},'asleep','unknown','asleep'],
  [{state:'awake'},'unknown','unknown','unknown'],
  [{state:'not-applicable'},'unsupported','unknown','unsupported']]){
  const state=driveStatus({...D,standby},true);assert.equal(state.power,power);assert.equal(state.activity,activity);assert.equal(state.power_state,power_state)
 }
 assert.equal(driveStatus({...D,connected:false,standby:{state:'standby',sleeping:true}},true).power_state,'unknown')
 assert.equal(driveStatus({...D,standby:{state:'standby',sleeping:true}},false).power,'unknown')
})
test('status-only variables and command outcome stay separate through stale/offline reads',()=>{
 const c=setup(),p=pinnedPrefix('drive',D);c.noticeTarget={kind:'drive',id:D.id};c.resultState='success';c.message='Standby confirmed.'
 assert.equal(values(c)[p+'power_label'],'Idle\nPower ?');assert.equal(values(c)[p+'outcome_label'],'Completed')
 c.invalidate('GET failed');assert.equal(values(c)[p+'power_label'],'Unknown');assert.equal(values(c)[p+'outcome_label'],'Completed');assert.equal(c.message,'Standby confirmed.')
 assert.equal(observedState(c,'drive',D.id,D.uuid,'power'),'unknown');assert.equal(observedState(c,'drive',D.id,D.uuid,'outcome'),'success')
})
