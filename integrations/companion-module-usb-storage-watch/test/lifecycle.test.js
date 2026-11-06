import test from 'node:test'
import assert from 'node:assert/strict'
import StorageWatch from '../src/main.js'
import { Controller, values } from '../src/controller.js'

test('a replaced connection cannot publish a late command error into the new connection', async () => {
  const instance = Object.create(StorageWatch.prototype), old = { message:'' }, replacement = { message:'New connection' }
  instance.controller = old
  let reject; const waiting = new Promise((_, r) => { reject = r })
  const action = instance.action(() => waiting)
  instance.controller = replacement; reject(new Error('Old request aborted'))
  await action; assert.equal(replacement.message, 'New connection')
})

test('Companion 2.x definitions use keyed variables and structured simple presets with the actual label', () => {
  const c = new Controller({ close() {} }), instance = Object.create(StorageWatch.prototype)
  instance.controller = c
  Object.defineProperty(instance, 'label', { value:'Custom_label' })
  instance.setVariableValues = () => {}; instance.checkFeedbacks = () => {}; instance.updateStatus = () => {}
  instance.setActionDefinitions = defs => assert.equal(defs.confirm.options[0].disableAutoExpression, true)
  instance.setFeedbackDefinitions = defs => assert.equal(defs.connection.callback(), false)
  instance.setVariableDefinitions = defs => { assert.equal(Array.isArray(defs), false); assert.equal(defs.connected.name, 'connected') }
  instance.setPresetDefinitions = (structure, defs) => {
    assert.equal(structure[0].definitions.includes('status'), true)
    assert.equal(defs.status.type, 'simple'); assert.match(defs.status.style.text, /Custom_label:connection_button/)
    assert.equal(Object.values(defs).some(p => p.steps.some(s => s.down.some(a => a.actionId === 'confirm'))), false)
  }
  instance.publish()
})

test('invalid replacement configuration clears old status, feedback and pending approval', async () => {
  const c = new Controller({ close() {} })
  for(const o of Object.values(c.observations))Object.assign(o,{valid:true,at:c.now()}); c.pending = { code:'123456', pages:['Code'], page:0, entered:'', expires:c.now()+120000 }
  c.state.apps = [{ id:'a'.repeat(64), name:'App', known:true, state:'running', startup:'enabled' }]
  const instance = Object.create(StorageWatch.prototype), written = {}, statuses = []
  instance.controller = c; instance.variableKeys = Object.keys(values(c))
  instance.setVariableValues = v => Object.assign(written, v)
  instance.checkFeedbacks = () => assert.equal(c.fresh(), false)
  instance.updateStatus = (...v) => statuses.push(v)
  await instance.configUpdated({ url:'invalid' }, { token:'' })
  assert.equal(c.pending, null); assert.equal(instance.controller, null)
  assert.equal(written['app_'+'a'.repeat(64)+'_state'], 'unknown')
  assert.equal(written.connected, 'no'); assert.equal(written.review_pending, 'no')
  assert.equal(statuses.length, 1)
})

test('manual read-only Refresh failure preserves the preceding verified command outcome',async()=>{
 const instance=Object.create(StorageWatch.prototype),c=new Controller({close(){}});instance.controller=c
 c.resultState='success';c.message='Standby confirmed.';c.connectionMessage='GET /api/fleet-status: ECONNRESET'
 instance.publish=()=>{};instance.log=()=>{}
 await instance.action(async()=>{throw new Error('Status failed')},false)
 assert.equal(c.resultState,'success');assert.equal(c.message,'Standby confirmed.')
})

test('Companion callback acknowledges promptly while the controller retains Working and rejects duplicate commands',async()=>{
 const instance=Object.create(StorageWatch.prototype),A='a'.repeat(64);let release,posted;const gate=new Promise(r=>release=r),sent=new Promise(r=>posted=r);let writes=0
 const client={session:1,close(){},request:async(path,data)=>{if(data){writes++;posted();await gate;return {ok:true,message:'Stopped and verified.'}}return path==='fleet-status'?{drives:[]}:{inventory_ok:true,containers:[{id:A,name:'App',state:'running',discovered:true}]}}}
 const c=new Controller(client);instance.controller=c;instance.publish=()=>{};instance.log=()=>{}
 assert.equal(instance.run(c=>c.execute('app',A,'stop')),undefined);assert.equal(c.busy,true);await sent
 assert.equal(instance.run(c=>c.execute('app',A,'stop')),undefined);await new Promise(r=>setImmediate(r));assert.equal(writes,1);assert.equal(c.resultState,'running')
 release();await new Promise(r=>setImmediate(r));assert.equal(c.resultState,'success');assert.equal(c.message,'Stopped and verified.');assert.equal(writes,1)
})
