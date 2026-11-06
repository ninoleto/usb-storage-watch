// SPDX-License-Identifier: MIT
// Presentation only: full pinned identities remain in every action and review.
export const ACTION_LABELS = {sleep:'Sleep HDD now',mount:'Mount',unmount:'Safely unmount','start-monitoring':'Monitor ON','stop-monitoring':'Monitor OFF',start:'Start app',stop:'Stop app',restart:'Restart app'}
export const resultLabel = state => ({running:'Working',success:'Completed',refused:'Refused',error:'Failed',uncertain:'Unknown',review:'Review only',reviewing:'Review only',idle:'Ready'}[state] || 'Unknown')
const BUTTON_LABELS = {sleep:'Sleep now',mount:'Mount',unmount:'Unmount','start-monitoring':'Mon ON','stop-monitoring':'Mon OFF',start:'Start',stop:'Stop',restart:'Restart'}
export const prefix = (kind,id) => kind+'_'+String(id).replaceAll(/[^a-zA-Z0-9_]/g,'_')+'_'
export function wrap(text, width = 11) {
  const words=String(text || '').replaceAll(/[_\s]+/g,' ').trim().split(' '), lines=[]
  let line=''
  for(let word of words){
    if(line && line.length+word.length+1>width){lines.push(line);line=''}
    while(word.length>width){if(line){lines.push(line);line=''}lines.push(word.slice(0,width));word=word.slice(width)}
    if(word)line+=(line?' ':'')+word
  }
  if(line)lines.push(line)
  return lines
}
export function buttonName(name) {const lines=wrap(name,11);return lines.slice(0,2).join('\n')+(lines.length>2?'…':'')}
export function pages(text, heading='') {
  const lines=wrap(text),out=[]
  const count=heading?3:4
  for(let i=0;i<lines.length;i+=count)out.push((heading?heading+'\n':'')+lines.slice(i,i+count).join('\n'))
  return out.length?out:[heading || 'No details']
}
export function reviewPages(plan) {
  const target=(plan.uuid || plan.id).slice(0,8)
  const out=pages(`${ACTION_LABELS[plan.action]}: ${plan.name} [${target}]`,'Target')
  if(plan.action==='unmount'){
    for(const app of plan.approval.apps.filter(a=>a.running)){
      out.push(...pages(`${app.name} [${app.id.slice(0,8)}]`,'STOP app'))
      if(app.images?.length)out.push(...pages(app.images.join(', '),'Uses images'))
    }
    if(!plan.approval.apps.some(a=>a.running))out.push(...pages('No running dependent apps to stop.'))
    out.push(...pages(plan.approval.message))
  }else if(plan.action==='sleep')out.push(...pages('Standby now. Busy users and writes may refuse sleep. Monitoring unchanged. No idle-timer wait.'))
  else if(plan.action==='mount')out.push(...pages('Mount drive. Deliberately stopped apps stay stopped.'))
  else if(plan.kind==='app')out.push(...pages(plan.action==='stop'?'Stop this app. Enabled drive recovery may start it later.':'Ready storage is required. This releases the manual-stop hold.'))
  else out.push(...pages('Monitoring only. Does not explicitly start apps.'))
  out.push('Enter code\n'+plan.code+'\non keypad,\nthen Confirm')
  return out
}
export function hddState(d,known) {
  if(!known || !d.connected)return 'unknown'
  if(d.standby?.state==='not-applicable')return 'unsupported'
  if(d.standby?.state==='standby' && d.standby?.sleeping===true)return 'asleep'
  if(d.standby?.state==='active')return 'awake'
  return 'unknown' // Idle alone is not a measured spindle state.
}
export function recoveryLabel(d,known) {
  if(!known)return 'Unknown'
  const code=d.progress?.code
  return ({healthy:'Ready',disabled:'Off',recovered:'Recovered',waiting:'Waiting',waiting_return:'Wait for drive',return_failed:'NO RETURN',failed:'FAILED',partial:'PARTIAL',running:'Recovering',verify:'Verifying',verifying:'Verifying',applications:'Starting apps',waiting_stop:'Stop blocked',stopping:'Stopping apps'})[code] || (code ? wrap(code,13).slice(0,2).join('\n'):'Unknown')
}
export function controlFeedback(c,kind,id,metric) {
  const row=c.state[kind==='drive'?'drives':'apps'].find(v=>v.id===id)
  if(c.noticeTarget?.kind===kind && c.noticeTarget?.id===id && ['error','refused','uncertain'].includes(c.resultState))return {bgcolor:0x9d2222,color:0xffffff}
  if(c.operation?.kind===kind && c.operation?.id===id || c.pending?.kind===kind && c.pending?.id===id)return {bgcolor:0x805600,color:0xffffff}
  if(!c.fresh(kind) || !row?.known || row.discovered===false)return {bgcolor:0x454545,color:0xffffff}
  if(kind==='app')return {bgcolor:row.control_block?0x805600:row.state==='running'?0x145b3a:0x172f49,color:0xffffff}
  if(row.connected!==true)return {bgcolor:0x9d2222,color:0xffffff}
  if(metric==='hdd')return {bgcolor:hddState(row,true)==='asleep'?0x463b79:0x172f49,color:0xffffff}
  if(metric==='monitor')return {bgcolor:row.monitoring==='active'?0x145b3a:0x172f49,color:0xffffff}
  if(['failed','partial','return_failed','waiting_stop'].includes(row.progress?.code))return {bgcolor:0x9d2222,color:0xffffff}
  return {bgcolor:row.mount_state==='mounted'?0x145b3a:0x172f49,color:0xffffff}
}
export function presetsFor(c,label) {
  const variable = key => `$(${label}:${key})`
  const action = (actionId,options={}) => ({actionId,options})
  const feedback = (kind,id,metric) => [{feedbackId:'control',options:{kind,id,metric}}]
  const button = (name,text,actions=[],feedbacks=[]) => ({type:'simple',name,style:{text,size:11,color:0xffffff,bgcolor:0x172f49,show_topbar:false},steps:[{down:actions,up:[]}],feedbacks})
  const presets = {
    status:button('Connection status',variable('connection_button'),[action('refresh')],[{feedbackId:'connection',options:{},style:{bgcolor:0x145b3a}}]),
    result:button('Result or refusal — press for next page',variable('result_button'),[action('result_next')],[{feedbackId:'result',options:{}}]),
  }
  // Only direct operating presets are supplied. Legacy copied review actions
  // remain compatible in main.js; they are never converted into writes.
  const structure=[{id:'status_results',name:'Connection and operation results',definitions:['status','result']}]
  for(const d of c.state.drives){
    const p=prefix('drive',d.id),ids=[]
    const add=(id,name,text,actions,metric)=>{ids.push(id);presets[id]=button(name,text,actions,feedback('drive',d.id,metric))}
    add('drive_'+d.id,d.name+' — mount',variable(p+'button_name')+'\n'+variable(p+'mount_label'),[], 'mount')
    for(const [metric,key] of [['monitor','monitor_label'],['recovery','recovery_label'],['hdd','hdd']]) add(metric+'_'+d.id,d.name+' — '+metric,variable(p+'button_name')+'\n'+(metric==='hdd'?'HDD\n':'')+variable(p+key),[],metric)
    for(const [verb,metric,state] of [['sleep','hdd','hdd'],['mount','mount','mount_label'],['unmount','mount','mount_label'],['start-monitoring','monitor','monitor_label'],['stop-monitoring','monitor','monitor_label']]) {
      const id='operate_'+verb+'_'+d.id
      add(id,ACTION_LABELS[verb]+' — '+d.name,variable(p+'button_name')+'\n'+BUTTON_LABELS[verb]+'\n'+variable(p+'operation_label'),[action('drive_'+verb.replaceAll('-','_'),{drive:JSON.stringify([d.id,d.uuid])})],metric)
      presets[id].notes='ONE PRESS operates profile '+d.id+'; pinned filesystem UUID '+d.uuid+'. Safe unmount stops explicitly dependent apps and leaves them stopped. Sleep calls manual standby with busy/write checks. Read Result for the verified outcome or refusal.'
    }
    structure.push({id:'drive_'+d.id,name:d.name+' · '+(d.uuid||d.id),definitions:ids})
  }
  for(const a of c.state.apps){
    const p=prefix('app',a.id),ids=['app_'+a.id]
    presets[ids[0]]=button(a.name+' — status',variable(p+'button_name')+'\n'+variable(p+'state'),[],feedback('app',a.id,'state'))
    for(const verb of ['start','stop','restart']){
      const id='operate_'+verb+'_'+a.id;ids.push(id)
      presets[id]=button(ACTION_LABELS[verb]+' — '+a.name,variable(p+'button_name')+'\n'+BUTTON_LABELS[verb]+'\n'+variable(p+'operation_label'),[action('app_'+verb,{app:a.id})],feedback('app',a.id,'state'))
      presets[id].notes='ONE PRESS operates exact container ID '+a.id+'. Recovery locks and required storage checks remain enforced. Read Result for the outcome.'
    }
    structure.push({id:'app_'+a.id,name:a.name+' · '+a.id.slice(0,12),definitions:ids})
  }
  return {structure,presets}
}
