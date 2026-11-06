// SPDX-License-Identifier: MIT
import { randomInt } from 'node:crypto'
import { ApiError } from './client.js'
import { buttonName, pages, reviewPages, hddState, recoveryLabel, resultLabel } from './buttons.js'
import { pinnedPrefix, driveStatus, appStatus, outcome, outcomeLabel } from './status.js'
export const DRIVE_ACTIONS = ['sleep', 'mount', 'unmount', 'start-monitoring', 'stop-monitoring']
export const APP_ACTIONS = ['start', 'stop', 'restart']
export const ACTIVE = new Set(['stopping', 'waiting_stop', 'waiting', 'waiting_return', 'waiting_manual', 'running', 'verify', 'verifying', 'applications', 'return_failed', 'confirming'])
const FAILED = new Set(['return_failed', 'failed', 'partial', 'waiting_stop'])
const yesno = value => typeof value === 'boolean' ? (value ? 'enabled' : 'off') : 'unknown'
export function normalize(fleet, apps) {
  if (!Array.isArray(fleet.drives) || !Array.isArray(apps.containers)) throw new ApiError('Incomplete inventory; status is unknown.', 'offline')
  const drives = fleet.drives.filter(v => v.configured && v.profile_id).map(v => ({
    ...v, id: v.profile_id, known: !v.stale && !v.busy && !v.error,
  }))
  const containers = apps.containers.map(v => {
    const saved = !apps.applications?.error && apps.applications?.settings?.find(s => s.id === v.id)
    return { ...v, known: apps.inventory_ok === true && !apps.error, startup: yesno(saved?.boot?.enabled), recovery: yesno(saved?.recovery?.enabled) }
  })
  return { drives, apps: containers, revision: apps.applications?.revision ?? null }
}
export class Controller {
  constructor(client, changed = () => {}, now = () => performance.now()) {
    this.client = client; this.changed = changed; this.now = now; this.state = { drives: [], apps: [], revision: null }
    this.observations = {fleet:{valid:false,at:0,message:'Fleet status not read yet.'},docker:{valid:false,at:0,message:'Docker status not read yet.'}}; this.reachVerified = false; this.lastReach = 0; this.connectionMessage = 'Connecting…'; this.pending = null; this.busy = false; this.message = 'Connecting…'; this.kind = 'offline'; this.disposed = false
    this.resultState = 'idle'; this.noticeTarget = null; this.operation = null; this.resultPage = 0
  }
  emit() { if (!this.disposed) this.changed(this) }
  dispose() { this.disposed = true; for (const o of Object.values(this.observations)) o.valid=false; this.reachVerified = false; this.pending = null; this.client.close() }
  fail(error) { this.message = this.client.scrub ? this.client.scrub(error.message) : error.message; this.resultState = error.kind === 'duplicate' && this.busy ? 'running' : error.kind === 'refused' ? 'refused' : ['offline','unavailable'].includes(error.kind) ? 'uncertain' : 'error'; this.resultPage = 0; this.emit() }
  invalidate(message, kind = 'offline', reachable = false) {
    for (const o of Object.values(this.observations)) Object.assign(o,{valid:false,message})
    this.pending=null;this.kind=kind;this.connectionMessage=message
    this.reachVerified=reachable;if(reachable)this.lastReach=this.now();this.emit()
  }
  reachable() { return this.reachVerified && this.now() - this.lastReach < 15000 }
  fresh(kind) {
    const key=kind==='drive'?'fleet':kind==='app'?'docker':kind
    if(!key)return this.fresh('fleet') && this.fresh('docker')
    const o=this.observations[key];return !!o?.valid && this.now()-o.at<15000
  }
  connectionSummary() {
    this.connectionMessage=Object.entries(this.observations).filter(([key])=>!this.fresh(key)).map(([key,o])=>o.message||key+' status unavailable.').join('; ') || 'Status verified.'
  }
  tick() {
    let changed=false
    if(this.reachVerified && !this.reachable()){this.reachVerified=false;changed=true}
    for(const [key,o] of Object.entries(this.observations))if(o.valid && !this.fresh(key)){
      o.valid=false;o.message=key+' status is stale.';this.pending=null;changed=true
    }
    if(changed){this.connectionSummary();this.emit()}
    if(this.pending && this.pending.expires<=this.now()){this.pending=null;this.fail({message:'Review expired. Review the action again.'})}
  }
  async refresh() {
    if(this.refreshing)return this.refreshing
    this.refreshing=(async()=>{
      const endpoints=['fleet-status','docker-overview'], keys=['fleet','docker']
      const reads=await Promise.allSettled(endpoints.map(async(endpoint,i)=>{
        const o=this.observations[keys[i]]
        try {
          const data=await this.client.request(endpoint)
          if(this.disposed)return
          if(!Array.isArray(data?.[i?'containers':'drives']))throw new ApiError(`GET /api/${endpoint}: incomplete inventory; status is unknown.`,'offline')
          const normalized=i?normalize({drives:[]},data):normalize(data,{containers:[]})
          if(i){this.state.apps=normalized.apps;this.state.revision=normalized.revision}else this.state.drives=normalized.drives
          Object.assign(o,{valid:true,at:this.now(),message:''});this.reachVerified=true;this.lastReach=this.now()
          this.connectionSummary();this.emit()
        } catch(error) {
          if(!this.disposed){Object.assign(o,{valid:false,message:error.message});this.pending=null;this.connectionSummary();this.emit()}
          throw error
        }
      }))
      if(this.disposed)return
      const failed=reads.find(r=>r.status==='rejected')
      if(failed){
        if(reads.every(r=>r.status==='rejected')){
          this.reachVerified=false
          try {const session=await this.client.request('session');if(this.disposed)return
            this.reachVerified=typeof session?.username==='string' && typeof session?.csrf==='string'
            if(this.reachVerified)this.lastReach=this.now()
          }catch{}
        }
        this.kind=failed.reason.kind;this.connectionSummary();this.emit();throw failed.reason
      }
      this.kind='ok';this.connectionSummary()
      if(this.pending && (this.pending.session!==this.client.session || this.pending.fingerprint!==this.fingerprint(this.pending.kind,this.pending.id))){
        this.pending=null;this.fail({message:'Identity, state or saved settings changed. Review again.'})
      }
      this.emit()
    })().finally(()=>{this.refreshing=null})
    return this.refreshing
  }
  async refreshAfterOperation() {
    // An older poll is not the new read required after an uncertain command.
    if (this.refreshing) await this.refreshing.catch(()=>{})
    if (!this.disposed) await this.refresh().catch(()=>{})
  }
  fingerprint(kind, id) {
    const row = this.state[kind === 'drive' ? 'drives' : 'apps'].find(v => v.id === id)
    if (!row) return ''
    return JSON.stringify([kind, id, row.name, row.uuid, row.mountpoint, row.connected, row.mount_state, row.monitoring, row.state, row.discovered, row.control_block, row.known, row.progress?.phase, row.progress?.incident, this.state.revision])
  }
  target(kind, id, action) {
    if (!this.fresh()) throw new ApiError('Drive or app status unavailable or stale. Refresh before operating a target.', 'offline')
    if (!(kind === 'drive' ? DRIVE_ACTIONS : kind === 'app' ? APP_ACTIONS : []).includes(action)) throw new ApiError('Unsupported action.', 'refused')
    const row = this.state[kind === 'drive' ? 'drives' : 'apps'].find(v => v.id === id)
    if (!row?.known) throw new ApiError('Selected identity is unavailable. Refresh; identities are never reassigned by name.', 'refused')
    if (kind === 'app') {
      if (!/^[0-9a-f]{64}$/.test(row.id) || row.discovered === false || ['unknown','missing','paused','dead','restarting'].includes(row.state)) throw new ApiError('Selected container identity/state cannot be controlled.', 'refused')
      if (row.control_block) throw new ApiError(row.control_block, 'refused')
      if (action === 'start' ? row.state !== 'stopped' : row.state !== 'running') throw new ApiError('This action is not applicable to the current app state.', 'refused')
    } else {
      if (!row.uuid) throw new ApiError('Selected filesystem identity is unknown.', 'refused')
      if (ACTIVE.has(row.progress?.code)) throw new ApiError('Drive recovery is active. Wait for its outcome; no command was queued.', 'refused')
      if (['mount','unmount'].includes(action) && (row.connected !== true || row.mount_state === 'error' || row.mount_state === 'conflict')) throw new ApiError('Storage identity is unavailable or conflicted. Review the drive in Storage Watch.', 'refused')
      if (action === 'unmount' && row.mount_state !== 'mounted') throw new ApiError('The selected filesystem is not verified mounted.', 'refused')
      if (action === 'mount' && row.mount_state === 'mounted') throw new ApiError('The drive is already mounted.', 'refused')
      if (action === 'sleep' && (row.connected !== true || row.mount_state !== 'mounted')) throw new ApiError('Sleep requires the selected filesystem connected and verified mounted.', 'refused')
      if (action === 'sleep' && row.standby?.state === 'not-applicable') throw new ApiError('HDD standby is unsupported for non-mechanical storage.', 'refused')
    }
    return row
  }
  async review(kind, id, action) {
    if (this.busy) throw new ApiError('Another action/review is in progress. Nothing was queued.', 'refused')
    this.busy = true; this.pending = null; this.operation = {kind,id,action}; this.noticeTarget = this.operation; this.resultState = 'reviewing'; this.message = 'Preparing review…'; this.resultPage = 0; this.emit()
    try {
      await this.refresh(); const row = this.target(kind, id, action); let approval = null
      let text = `${action}: ${row.name}. Identity: ${kind === 'drive' ? row.uuid : row.id}. `
      if (action === 'unmount') {
        approval = await this.client.request(`drives/${encodeURIComponent(id)}/unmount-plan?uuid=${encodeURIComponent(row.uuid)}`)
        if (!approval.token || !Array.isArray(approval.apps) || typeof approval.message !== 'string') throw new ApiError('Safe-unmount review is incomplete.', 'refused')
        text += approval.apps.filter(v => v.running).map(v => `STOP ${v.name} (${v.id})${v.images?.length ? ' · images: ' + v.images.join(', ') : ''}`).join('; ') || 'No running dependent apps to stop.'
        text += ' ' + approval.message
      } else if (kind === 'app') text += action === 'stop' ? 'Stop this app. Later boot coordinator runs will respect the manual stop; enabled drive recovery may start it again.' : 'Existing storage, identity and recovery checks must pass. Explicit Start/Restart can release this app’s deliberate-stop hold.'
      else text += action === 'mount' ? 'Mount this configured filesystem. Deliberately stopped apps remain stopped.' : action === 'sleep' ? 'Request manual HDD standby now, without waiting for the automatic idle timer. Busy users and writes are still checked. Monitoring is unchanged.' : 'Change monitoring only. This does not explicitly start apps.'
      this.pending = { kind, id, action, name: row.name, uuid: row.uuid, approval, text,
        fingerprint: this.fingerprint(kind, id), session: this.client.session, expires: this.now() + 120000, code: String(randomInt(100000, 1000000)) }
      Object.assign(this.pending,{pages:reviewPages(this.pending),page:0,entered:''})
      this.message = 'Review ready. Read all Review pages, enter the code on the keypad, then press Confirm. No operation has run.'; this.resultState = 'review'; this.emit(); return this.pending
    } catch (error) { error=new ApiError('No command sent. '+error.message,'refused');this.fail(error);throw error }
    finally { this.busy = false; this.operation = null; this.emit() }
  }
  cancel() { if (this.busy) throw new ApiError('An operation is already running; its outcome must be observed.', 'refused'); this.pending = null; this.message = 'Review cancelled. No operation sent.'; this.resultState = 'idle'; this.resultPage = 0; this.emit() }
  reviewNext(delta=1) { this.tick(); if(!this.pending)throw new ApiError('No current review. Select an action first.'); this.pending.page = Math.max(0,Math.min(this.pending.page+delta,this.pending.pages.length-1)); this.emit() }
  resultNext() { this.resultPage = (this.resultPage+1)%pages(this.message,resultLabel(this.resultState)).length; this.emit() }
  digit(value) {
    this.tick(); const p = this.pending
    if(this.busy || !p || p.page !== p.pages.length-1)throw new ApiError('Read all Review pages before entering the code.')
    if(value==='back')p.entered=p.entered.slice(0,-1)
    else if(/^[0-9]$/.test(value) && p.entered.length<6)p.entered+=value
    else throw new ApiError('Enter six digits only; use Back to correct the code.')
    this.emit()
  }
  confirmEntered() { const p=this.pending; if(!p || p.page!==p.pages.length-1)throw new ApiError('Read all Review pages first.'); return this.confirm(p.entered) }
  async execute(kind, id, action, uuid) {
    if (this.busy) throw new ApiError('Another operation is working. This press was refused; nothing was queued.', 'duplicate')
    this.pending = null; this.busy = true; this.operation = {kind,id,action}; this.noticeTarget = this.operation
    this.resultState = 'running'; this.resultPage = 0; this.message = 'Working: checking the selected target and its safeguards…'; this.emit()
    let dispatched=false
    try {
      await this.refresh()
      const row = this.target(kind,id,action)
      if (kind === 'drive' && (!uuid || uuid !== row.uuid)) throw new ApiError('The preset filesystem identity changed. Select the drive again; nothing was operated.', 'refused')
      const plan = {kind,id,action,name:row.name,uuid:row.uuid,session:this.client.session,fingerprint:this.fingerprint(kind,id)}
      if (action === 'unmount') {
        plan.approval = await this.client.request(`drives/${encodeURIComponent(id)}/unmount-plan?uuid=${encodeURIComponent(uuid)}`)
        if (!plan.approval.token || !Array.isArray(plan.approval.apps) || typeof plan.approval.message !== 'string') throw new ApiError('Safe-unmount dependency check is incomplete. Nothing was unmounted.', 'refused')
        // The button press authorizes this operation. Keep the server's session-bound,
        // one-use snapshot and locked readback; no code/keypad interaction is involved.
        await this.refresh(); this.target(kind,id,action)
        if (plan.session !== this.client.session || plan.fingerprint !== this.fingerprint(kind,id)) throw new ApiError('Target, state or settings changed during the safety check. Nothing was sent; inspect status before pressing again.', 'refused')
      }
      this.message = 'Working: '+action+' — '+row.name+'. Waiting for the verified result…'; this.emit()
      dispatched=true; const result = await this.dispatch(plan)
      this.message = result.message; this.resultState = 'success'; return result
    } catch (error) { if(!dispatched)error=new ApiError('No command sent. '+error.message,'refused');this.fail(error);throw error }
    finally { this.busy = false; this.operation = null; this.emit(); await this.refreshAfterOperation() }
  }
  async dispatch(plan) {
    let result
    if (plan.kind === 'app') result = await this.client.request('docker-container-action', { id:plan.id, name:plan.name, action:plan.action, confirm:true }, 420000)
    else if (plan.action.endsWith('monitoring')) result = await this.client.request(`drives/${encodeURIComponent(plan.id)}/monitor`, { enabled:plan.action === 'start-monitoring' }, 70000)
    else result = await this.client.request(`drives/${encodeURIComponent(plan.id)}/disk-operation`, { uuid:plan.uuid, action:plan.action,
      ...(plan.approval ? { token:plan.approval.token, confirm:true } : {}) }, 420000)
    if (!result || typeof result.message !== 'string' || result.ok === false || (!plan.action.endsWith('monitoring') && result.ok !== true))
      throw new ApiError(result?.message || 'Incomplete command result. Outcome is uncertain; inspect the dashboard before trying again.',
        ['busy','refused','unsupported','unavailable'].includes(result?.result) ? 'refused' : result?.result === 'uncertain' || result?.uncertain === true || result?.ok !== false ? 'offline' : 'failed')
    return result
  }
  async confirm(code) {
    if (this.busy) throw new ApiError('Another operation is in progress. Nothing was queued.', 'refused')
    const plan = this.pending
    // Literal text only. No variable/expression expansion or auto-confirm option.
    if (!plan || !/^\d{6}$/.test(String(code)) || code !== plan.code || plan.expires <= this.now()) throw new ApiError('Enter the current review code explicitly. Review again if it expired.', 'refused')
    this.pending = null; this.busy = true; this.operation = plan; this.noticeTarget = plan; this.resultState = 'running'; this.resultPage = 0; this.message = 'Applying reviewed action…'; this.emit()
    let dispatched=false
    try {
      await this.refresh(); this.target(plan.kind, plan.id, plan.action)
      if (plan.session !== this.client.session || plan.fingerprint !== this.fingerprint(plan.kind, plan.id)) throw new ApiError('The reviewed identity/state/settings changed. Nothing was sent; review again.', 'refused')
      dispatched=true; const result = await this.dispatch(plan)
      this.message = result.message; this.resultState = 'success'; return result
    } catch (error) { if(!dispatched)error=new ApiError('No command sent. '+error.message,'refused');this.fail(error);throw error }
    finally { this.busy = false; this.operation = null; this.emit(); await this.refreshAfterOperation() }
  }
}
export function values(controller) {
  const fresh = controller.fresh(); const out = { connected: controller.reachable() ? 'yes' : 'no', status_fresh:fresh ? 'yes':'no', fleet_fresh:controller.fresh('fleet')?'yes':'no', docker_fresh:controller.fresh('docker')?'yes':'no', fleet_status_message:controller.observations.fleet.message, docker_status_message:controller.observations.docker.message, connection_message:controller.connectionMessage, last_result: controller.message,
    review_text: controller.pending?.text || '', review_code: controller.pending?.code || '', review_pending: controller.pending ? 'yes' : 'no', operation_running: controller.busy ? 'yes' : 'no' }
  const p=controller.pending, label=resultLabel(controller.resultState), resultPages=pages(controller.message,label), resultIndex=Math.min(controller.resultPage,resultPages.length-1)
  Object.assign(out,{result_state:controller.resultState,review_button:p?`${p.page+1}/${p.pages.length}\n${p.pages[p.page]}`:'No pending\nreview',
    confirm_button:p?`Confirm\n${p.entered.padEnd(6,'_')}\n${Math.max(0,Math.ceil((p.expires-controller.now())/1000))}s left`:'Confirm\nNo review',
    result_label:label, result_button:`${resultIndex+1}/${resultPages.length}\n${resultPages[resultIndex]}`,connection_button:fresh?'USW\nOnline':controller.reachable()?'USW\nOnline\nStatus stale':'USW\nOFFLINE'})
  for (const d of controller.state.drives) {
    const p = 'drive_' + d.id.replaceAll('-', '_') + '_', known = controller.fresh('fleet') && d.known
    Object.assign(out, { [p+'name']:d.name, [p+'uuid']:d.uuid || '', [p+'availability']:known ? d.connected === true ? 'connected' : d.connected === false ? 'disconnected' : 'unknown' : 'unknown',
      [p+'mount']:known ? d.mount_state : 'unknown', [p+'monitoring']:known ? d.monitoring : 'unknown', [p+'recovery']:known ? d.progress?.code || 'unknown' : 'unknown',
      [p+'detail']:known ? d.progress?.detail || '' : 'Status unavailable', [p+'remaining_seconds']:known && ACTIVE.has(d.progress?.code) ? d.progress?.drive_return?.remaining_seconds ?? '' : '',
      [p+'failure']:known ? FAILED.has(d.progress?.code) ? 'yes' : 'no' : 'unknown' })
    Object.assign(out,{[p+'hdd']:hddState(d,known),[p+'hdd_detail']:known?d.standby?.message||'Power state unknown':'Status unavailable',
      [p+'button_name']:buttonName(d.name)+'\n'+String(d.uuid||d.id).slice(0,6),
      [p+'mount_label']:!known?'Unknown':d.connected!==true?'Unavailable':({mounted:'Mounted',unmounted:'Unmounted',error:'Mount ERROR',conflict:'CONFLICT',unavailable:'Unavailable'}[d.mount_state]||'Unknown'),
      [p+'monitor_label']:known?({active:'Monitor ON',inactive:'Monitor OFF',failed:'Monitor FAILED'}[d.monitoring]||'Monitor ?'):'Monitor ?',
      [p+'recovery_label']:recoveryLabel(d,known)})
    const current=driveStatus(d,known), pinned=pinnedPrefix('drive',d)
    for(const [key,value] of Object.entries(current))out[pinned+key]=value
    out[pinned+'outcome_label']=outcomeLabel(outcome(controller,'drive',d.id))
    out[p+'power_state']=current.power_state;out[p+'activity']=current.activity;out[p+'power_label']=current.power_label
    const selected=controller.noticeTarget?.kind==='drive' && controller.noticeTarget?.id===d.id
    out[p+'operation_label']=selected?label:out[p+'mount_label'];out[p+'last_result']=selected?controller.message:''
  }
  for (const a of controller.state.apps) {
    const p = 'app_' + a.id.replaceAll(/[^a-zA-Z0-9_]/g, '_') + '_', known = controller.fresh('docker') && a.known
    Object.assign(out, { [p+'name']:a.name, [p+'id']:a.id, [p+'state']:known ? a.state : 'unknown', [p+'health']:known ? a.health || 'no healthcheck' : 'unknown',
      [p+'startup']:controller.fresh('docker') ? a.startup : 'unknown', [p+'recovery']:controller.fresh('docker') ? a.recovery : 'unknown', [p+'blocked']:known ? a.control_block ? 'yes' : 'no' : 'unknown', [p+'reason']:known ? a.control_block || '' : 'Status unavailable' })
    out[p+'state_label']=appStatus(a,known).label;out[p+'outcome_label']=outcomeLabel(outcome(controller,'app',a.id))
    out[p+'button_name']=buttonName(a.name)+'\n'+a.id.slice(0,6)
    const selected=controller.noticeTarget?.kind==='app' && controller.noticeTarget?.id===a.id
    out[p+'operation_label']=selected?label:out[p+'state'];out[p+'last_result']=selected?controller.message:''
  }
  return out
}
