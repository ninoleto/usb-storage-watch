// SPDX-License-Identifier: MIT
import { InstanceBase, InstanceStatus } from '@companion-module/base'
import { Client } from './client.js'
import { Controller, values, DRIVE_ACTIONS, APP_ACTIONS } from './controller.js'
import { ACTION_LABELS, controlFeedback, pages } from './buttons.js'
import { presetsFor, booleanFeedbacks } from './layouts.js'
export const UpgradeScripts = []
const dropdown = (id, label, choices) => ({ id, type: 'dropdown', label, default: '', choices: [{ id:'', label:'Select explicitly' }, ...choices], allowCustom: true, disableAutoExpression: true })
export default class StorageWatch extends InstanceBase {
  async init(config, _first, secrets) { await this.configUpdated(config, secrets) }
  async destroy() { clearTimeout(this.pollTimer); clearInterval(this.freshTimer); this.controller?.dispose(); this.controller = null }
  getConfigFields() {
    return [
      { type:'static-text', id:'help', label:'Storage Watch UI36+', value:'Operating presets execute with ONE press through the authenticated API and backend safeguards. Safe unmount stops dependent apps. Read the Result button for Working, Completed or a refusal/failure explanation.', width:12 },
      { type:'textinput', id:'url', label:'Server URL', default:'http://127.0.0.1:8765', width:12 },
      { type:'secret-text', id:'token', label:'Dashboard management token', width:12 },
      { type:'textinput', id:'ca', label:'Trusted public CA certificate (PEM, optional)', multiline:true, width:12, default:'', description:'Paste only the verified public CA certificate from Storage Watch. HTTPS certificate/hostname validation is always enabled.' },
    ]
  }
  async configUpdated(config, secrets) {
    await this.destroy()
    this.setVariableValues(Object.fromEntries((this.variableKeys || []).map(key => [key, 'unknown'])))
    this.checkFeedbacks('connection','drive','app','review','control','result','state_power','state_mount','state_monitor','state_recovery','state_app','state_outcome')
    this.signature = null; this.variableKeys = []; this.delay = 5000
    try {
      const controller = new Controller(new Client(config, secrets?.token, entry => this.log(entry.result === 'response' ? entry.method === 'POST' && entry.operation !== 'login' ? 'info' : 'debug' : 'warn', 'USW request '+JSON.stringify(entry))), () => this.publish())
      this.controller = controller; this.publish()
      const poll = async () => {
        try { await controller.refresh(); this.delay = 5000 } catch { this.delay = controller.reachable() ? 5000 : Math.min(this.delay * 2, 60000) }
        if (this.controller === controller) this.pollTimer = setTimeout(poll, this.delay)
      }
      this.freshTimer = setInterval(() => controller.tick(), 1000)
      await poll()
    } catch (error) { this.setVariableValues({ connected:'no', connection_button:'USW\nOFFLINE', last_result:error.message, result_state:'error', result_button:'ERROR\n'+pages(error.message)[0], review_pending:'no', review_text:'', review_code:'', review_button:'No pending\nreview', confirm_button:'Confirm\nNo review' }); this.updateStatus(InstanceStatus.BadConfig, error.message) }
  }
  run(callback, operation = true) {
    // Companion's action RPC has a five-second deadline. Acknowledging dispatch
    // is not completion: the controller owns Working/result state and rejects
    // competing presses while the bounded request remains in progress.
    void this.action(callback, operation)
  }
  async action(callback, operation = true) {
    const controller = this.controller
    if (!controller) return
    try { await callback(controller) } catch (error) {
      if (this.controller !== controller) return
      if (operation) controller.fail(error); this.publish(); this.log('warn', operation ? controller.message : controller.connectionMessage)
    }
  }
  publish() {
    const c = this.controller; if (!c) return
    const data = values(c), keys = Object.keys(data)
    const signature = JSON.stringify([c.state.drives.map(v => [v.id,v.name,v.uuid]),c.state.apps.map(v => [v.id,v.name]),keys])
    if (signature !== this.signature) {
      const removed = Object.fromEntries((this.variableKeys || []).filter(v => !keys.includes(v)).map(v => [v,'unknown']))
      this.setVariableValues(removed); this.variableKeys = keys; this.signature = signature
      this.setVariableDefinitions(Object.fromEntries(keys.map(key => [key, { name: this.describe(key, c) }])))
      this.definitions(c)
    }
    this.setVariableValues(data); this.checkFeedbacks('connection','drive','app','review','control','result','state_power','state_mount','state_monitor','state_recovery','state_app','state_outcome')
    this.updateStatus(c.fresh() ? InstanceStatus.Ok : c.reachable() ? InstanceStatus.UnknownWarning : c.kind === 'auth' ? InstanceStatus.AuthenticationFailure : InstanceStatus.ConnectionFailure, c.fresh() ? undefined : c.connectionMessage)
  }
  describe(key, c) {
    for (const d of c.state.drives) { const p='drive_'+d.id.replaceAll('-','_')+'_'; if (key.startsWith(p)) return `${d.name} (${d.uuid || d.id}) — ${key.slice(p.length).replaceAll('_',' ')}` }
    for (const a of c.state.apps) { const p='app_'+a.id.replaceAll(/[^a-zA-Z0-9_]/g,'_')+'_'; if (key.startsWith(p)) return `${a.name} (${a.id.slice(0,12)}) — ${key.slice(p.length).replaceAll('_',' ')}` }
    return key.replaceAll('_',' ')
  }
  definitions(c) {
    const drives = c.state.drives.map(v => ({id:v.id,label:`${v.name} · ${v.uuid || 'UUID unknown'} · ${v.mountpoint || ''}`}))
    const apps = c.state.apps.map(v => ({id:v.id,label:`${v.name} · ${v.id}`}))
    const direct = {}
    const pinnedDrives=c.state.drives.map(v=>({id:JSON.stringify([v.id,v.uuid]),label:`${v.name} · ${v.uuid || 'UUID unknown'} · ${v.mountpoint || ''}`}))
    for(const action of DRIVE_ACTIONS)direct['drive_'+action.replaceAll('-','_')]={
      name:ACTION_LABELS[action]+' — execute now',description:'One press executes. The profile and filesystem UUID are pinned; backend safety checks remain enforced.',options:[dropdown('drive','Drive / pinned filesystem',pinnedDrives)],
      callback:e=>this.run(c=>{let target;try{target=JSON.parse(e.options.drive)}catch{throw new Error('Select a drive and filesystem identity.')}
        if(!Array.isArray(target)||target.length!==2||target.some(v=>typeof v!=='string'||!v))throw new Error('Select a drive and filesystem identity.')
        return c.execute('drive',target[0],action,target[1])})}
    for(const action of APP_ACTIONS)direct['app_'+action]={name:ACTION_LABELS[action]+' — execute now',description:'One press executes for the selected exact container ID.',options:[dropdown('app','App — exact container ID',apps)],callback:e=>this.run(c=>c.execute('app',e.options.app,action))}
    this.setActionDefinitions({
      ...direct,
      review_drive: { name:'Review drive action (does not execute)', options:[dropdown('drive','Drive',drives),dropdown('action','Action',DRIVE_ACTIONS.map(id => ({id,label:ACTION_LABELS[id]})))], callback: e => this.run(c => c.review('drive',e.options.drive,e.options.action)) },
      review_app: { name:'Review app action (does not execute)', options:[dropdown('app','App — exact container ID',apps),dropdown('action','Action',APP_ACTIONS.map(id => ({id,label:id+' app'})))], callback:e => this.run(c => c.review('app',e.options.app,e.options.action)) },
      confirm: { name:'Confirm reviewed action — enter current code', description:'Read review_text and enter review_code manually. Code expires in two minutes, is single-use, and never accepts expressions or variables.', options:[{id:'code',type:'textinput',label:'Literal six-digit code from the current review',default:'',regex:'/^[0-9]{6}$/',disableAutoExpression:true}], callback:e => this.run(c => c.confirm(e.options.code)) },
      review_next: { name:'Next review page', options:[], callback:() => this.run(c => c.reviewNext()) },
      review_back: { name:'Previous review page', options:[], callback:() => this.run(c => c.reviewNext(-1)) },
      result_next: { name:'Next result/refusal page', options:[], callback:() => this.run(c => c.resultNext()) },
      digit: { name:'Enter review-code digit', options:[dropdown('value','Digit',[...Array.from({length:10},(_,i)=>({id:String(i),label:String(i)})),{id:'back',label:'Backspace'}])], callback:e => this.run(c => c.digit(e.options.value)) },
      confirm_keypad: { name:'Confirm code entered on buttons', options:[], callback:() => this.run(c => c.confirmEntered()) },
      cancel: { name:'Cancel pending review', options:[], callback:() => this.run(c => c.cancel()) },
      refresh: { name:'Refresh read-only status', options:[], callback:() => this.run(c => c.refresh(), false) },
    })
    const condition = (id,label,choices) => dropdown(id,label,choices.map(id => ({id,label:id})))
    this.setFeedbackDefinitions({
      ...booleanFeedbacks(c,dropdown),
      result: { type:'advanced', affectedProperties:['bgcolor','color'], name:'Operation result — observed outcome only', options:[], callback:() => ({color:0xffffff,bgcolor:c.disposed?0x454545:['error','refused','uncertain'].includes(c.resultState)?0x9d2222:c.resultState==='success'?0x145b3a:['review','reviewing','running'].includes(c.resultState)?0x805600:0x172f49}) },
      control: { type:'advanced', affectedProperties:['bgcolor','color'], name:'Legacy fixed colours — use editable state feedbacks for new buttons', options:[dropdown('kind','Target type',[{id:'drive',label:'Drive'},{id:'app',label:'App'}]),{id:'id',type:'textinput',label:'Pinned identity',default:'',disableAutoExpression:true},dropdown('metric','State',['mount','monitor','recovery','hdd','state'].map(id=>({id,label:id})))], callback:e => controlFeedback(c,e.options.kind,e.options.id,e.options.metric) },
      connection: { type:'boolean', name:'Server status is fresh', defaultStyle:{bgcolor:0x145b3a,color:0xffffff}, options:[], callback:() => c.fresh() },
      review: { type:'boolean', name:'Review awaits explicit confirmation', defaultStyle:{bgcolor:0x805600,color:0xffffff}, options:[], callback:() => !!c.pending && c.pending.expires>c.now() },
      drive: { type:'boolean', name:'Drive observed state', defaultStyle:{bgcolor:0x805600,color:0xffffff}, options:[dropdown('drive','Drive',drives),condition('field','Field',['availability','mount','monitoring','recovery','failure','hdd']),{id:'value',type:'textinput',label:'Expected value (for example connected, mounted, active, return_failed, yes)',default:'connected',disableAutoExpression:true}], callback:e => values(c)['drive_'+String(e.options.drive).replaceAll('-','_')+'_'+e.options.field] === e.options.value },
      app: { type:'boolean', name:'App observed state or saved setting', defaultStyle:{bgcolor:0x145b3a,color:0xffffff}, options:[dropdown('app','App',apps),condition('field','Field',['state','health','startup','recovery','blocked']),{id:'value',type:'textinput',label:'Expected value (running, healthy, enabled, off, yes or unknown)',default:'running',disableAutoExpression:true}], callback:e => values(c)['app_'+String(e.options.app).replaceAll(/[^a-zA-Z0-9_]/g,'_')+'_'+e.options.field] === e.options.value },
    })
    const {structure,presets}=presetsFor(c,this.label)
    this.setPresetDefinitions(structure,presets)
  }
}
