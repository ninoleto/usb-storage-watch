// SPDX-License-Identifier: MIT
// Passive UI36 evidence only. Never query hardware or infer power from inactivity.
import { prefix, resultLabel } from './buttons.js'
export const COLORS = {idle:0x172f49,asleep:0x463b79,in_use:0x145b3a,fault:0x9d2222,unknown:0x454545,working:0x805600}
export const STATUS = {
 power: {name:'Drive power / I/O evidence', states:{idle:['Idle — no recent I/O; power unknown','idle'],asleep:['Asleep — standby confirmed for this connection','asleep'],in_use:['In use — disk I/O observed','in_use'],unavailable:['Drive unavailable','fault'],unsupported:['Standby not applicable','unknown'],unknown:['Power / activity unknown or stale','unknown']}},
 mount: {name:'Drive mounted state',states:{mounted:['Mounted','in_use'],unmounted:['Unmounted','idle'],unavailable:['Drive unavailable','fault'],fault:['Mount error or identity conflict','fault'],unknown:['Mount state unknown or stale','unknown']}},
 monitor: {name:'Drive monitoring state',states:{active:['Monitoring on','in_use'],inactive:['Monitoring off','idle'],failed:['Monitoring failed','fault'],unknown:['Monitoring unknown or stale','unknown']}},
 recovery: {name:'Drive recovery state',states:{ready:['Ready / recovered','idle'],off:['Recovery off','idle'],working:['Recovery in progress','working'],failed:['Recovery failed / blocked','fault'],unknown:['Recovery unknown or stale','unknown']}},
 app: {name:'App running state',states:{running:['Running','in_use'],stopped:['Stopped','idle'],working:['Restarting / recovery lock','working'],fault:['Missing, dead or unhealthy','fault'],paused:['Paused','idle'],unknown:['App state unknown or stale','unknown']}},
 outcome: {name:'Target command outcome (separate from live state)',states:{idle:['No action yet','idle'],running:['Operation in progress','working'],success:['Completed — verified reply','in_use'],refused:['Refused','fault'],error:['Failed','fault'],uncertain:['Unknown command outcome','unknown'],review:['Legacy review only — not executed','working'],reviewing:['Preparing legacy review — not executed','working']}},
}
export const pinnedPrefix = (kind,row) => prefix(kind,kind==='drive'?row.id+'_fs_'+row.uuid:row.id)
export function driveStatus(d, known) {
 const result={power:'unknown',activity:'unknown',power_state:'unknown',power_label:'Unknown',mount:'unknown',mount_label:'Unknown',monitor:'unknown',monitor_label:'Monitor ?',recovery:'unknown',recovery_label:'Unknown'}
 if(!known)return result
 result.monitor=['active','inactive','failed'].includes(d.monitoring)?d.monitoring:'unknown'
 result.monitor_label={active:'Monitor ON',inactive:'Monitor OFF',failed:'Monitor failed'}[result.monitor]||'Monitor ?'
 const code=d.progress?.code
 result.recovery=['healthy','recovered'].includes(code)?'ready':code==='disabled'?'off':['failed','partial','return_failed','waiting_stop'].includes(code)?'failed':['stopping','waiting','waiting_return','waiting_manual','running','verify','verifying','applications','confirming'].includes(code)?'working':'unknown'
 result.recovery_label={ready:code==='recovered'?'Recovered':'Ready',off:'Recovery OFF',working:'Recovering',failed:code==='return_failed'?'No return':'Recovery failed'}[result.recovery]||'Unknown'
 if(d.connected===false)return {...result,power:'unavailable',power_label:'Unavailable\nPower ?',mount:'unavailable',mount_label:'Unavailable'}
 if(d.connected!==true)return result
 result.mount=['mounted','unmounted'].includes(d.mount_state)?d.mount_state:['error','conflict'].includes(d.mount_state)?'fault':'unknown'
 result.mount_label={mounted:'Mounted',unmounted:'Unmounted',fault:'Mount error'}[result.mount]||'Unknown'
 const s=d.standby
 if(s?.state==='not-applicable')Object.assign(result,{power:'unsupported',power_state:'unsupported',power_label:'Not applicable'})
 else if(s?.state==='standby' && s.sleeping===true && s.applicable!==false)Object.assign(result,{power:'asleep',power_state:'asleep',power_label:'Asleep'})
 else if(s?.state==='active')Object.assign(result,{power:'in_use',power_state:'awake',activity:'in_use',power_label:'In use\nI/O observed'})
 else if(s?.state==='idle')Object.assign(result,{power:'idle',activity:'idle',power_label:'Idle\nPower ?'})
 return result
}
export function appStatus(a,known) {
 if(!known || !a)return {state:'unknown',label:'Unknown'}
 if(a.discovered===false || ['missing','dead'].includes(a.state) || a.health==='unhealthy')return {state:'fault',label:a.health==='unhealthy'?'Unhealthy':a.state==='dead'?'Dead':'Missing'}
 const label={running:'Running',stopped:'Stopped',paused:'Paused',restarting:'Restarting'}[a.state]||'Unknown'
 if(a.control_block)return {state:'working',label:label+'\nRecovery lock'}
 return {state:['running','stopped','paused'].includes(a.state)?a.state:a.state==='restarting'?'working':'unknown',label}
}
export function outcome(c,kind,id) {return c.noticeTarget?.kind===kind && c.noticeTarget.id===id?c.resultState:'idle'}
export const outcomeLabel = state => state==='idle'?'No action':resultLabel(state)
export function observedState(c,kind,id,uuid,metric) {
 if(metric==='outcome')return outcome(c,kind,id)
 const row=c.state[kind==='drive'?'drives':'apps'].find(r=>r.id===id)
 const known=c.fresh(kind) && row?.known && (kind!=='drive' || !!uuid && row.uuid===uuid)
 return kind==='drive'?driveStatus(row,known)[metric]||'unknown':appStatus(row,known).state
}
