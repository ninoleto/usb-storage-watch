// SPDX-License-Identifier: MIT
// New IDs make this an opt-in layout upgrade: existing copies/links stay intact.
import { presetsFor as legacyPresets, buttonName, ACTION_LABELS } from './buttons.js'
import { COLORS, STATUS, pinnedPrefix, observedState } from './status.js'
export function booleanFeedbacks(c, dropdown) {
 const drives=c.state.drives.map(d=>({id:JSON.stringify([d.id,d.uuid]),label:`${d.name} · ${d.uuid} · ${d.mountpoint||''}`}))
 const apps=c.state.apps.map(a=>({id:a.id,label:`${a.name} · ${a.id}`}))
 const result={}
 for(const [metric,definition] of Object.entries(STATUS)) {
  const kind=metric==='app'?'app':'drive'
  result['state_'+metric]={type:'boolean',name:definition.name,description:'Choose a condition; edit its style override independently. Display text does not select the target.',defaultStyle:{bgcolor:COLORS.unknown,color:0xffffff},
   options:metric==='outcome'?[dropdown('kind','Target type',[{id:'drive',label:'Drive'},{id:'app',label:'App'}]),{id:'id',type:'textinput',label:'Exact profile or container ID',default:'',disableAutoExpression:true}]:[dropdown('target',kind==='drive'?'Drive / pinned filesystem':'App / exact container ID',kind==='drive'?drives:apps)],
   callback:e=>{
    let id=e.options.target,uuid
    if(kind==='drive' && metric!=='outcome'){try{[id,uuid]=JSON.parse(id)}catch{return false}}
    const current=observedState(c,metric==='outcome'?e.options.kind:kind,metric==='outcome'?e.options.id:id,uuid,metric)
    return current===e.options.state
   }}
  result['state_'+metric].options.push(dropdown('state','Condition',Object.entries(definition.states).map(([id,[label]])=>({id,label}))))
 }
 return result
}
export function presetsFor(c,label) {
 // Retain original definitions for previously linked presets, but list new layouts only.
 const {presets}=legacyPresets(c,label),structure=[]
 const variable=key=>({isExpression:true,value:`$(${label}:${key})`})
 const action=(actionId,options={})=>({actionId,options})
 const text=(id,name,value,y,height,fontsize=13)=>({type:'text',id,name,text:value,x:4,y:y*100,width:92,height:height*100,fontsize:100,fontsizeAllowShrink:true,color:0xffffff,halign:'center',valign:'center'})
 function feedbacks(kind,row,metric,operation) {
  const options=metric==='outcome'?{}:{target:kind==='drive'?JSON.stringify([row.id,row.uuid]):row.id}
  const states=Object.entries(STATUS[metric].states).map(([state,[name,color]])=>({feedbackId:'state_'+metric,options:{...options,state},headline:name,styleOverrides:[{elementId:'background',elementProperty:'color',override:COLORS[color]}]}))
  if(operation)for(const [state,[name,color]] of Object.entries(STATUS.outcome.states)) {
   if(state==='idle')continue
   states.push({feedbackId:'state_outcome',options:{kind,id:row.id,state},headline:name,styleOverrides:[{elementId:'outcome-background',elementProperty:'color',override:COLORS[color]},...(state==='running'?[{elementId:'background',elementProperty:'color',override:COLORS.working}]:[])]})
  }
  return states
 }
 function targetButton(kind,row,metric,verb) {
  const p=pinnedPrefix(kind,row),isAction=!!verb
  const live=metric==='app'?'state_label':metric+'_label'
  const elements=[{type:'box',id:'background',name:'Live state background',color:COLORS.unknown},text('custom-name','Custom name',buttonName(row.name),.02,.34,14),text('live-status','Live status',variable(p+live),isAction?.37:.49,isAction?.25:.40,13)]
  if(isAction)elements.push(text('action','Action',({sleep:'Sleep now',mount:'Mount',unmount:'Safe unmount','start-monitoring':'Mon ON','stop-monitoring':'Mon OFF',start:'Start',stop:'Stop',restart:'Restart'})[verb],.63,.17,12),{type:'box',id:'outcome-background',name:'Command outcome background',x:0,y:82,width:100,height:18,color:COLORS.idle},text('command-outcome','Command outcome',variable(p+'outcome_label'),.82,.17,10))
  return {type:'layered',name:row.name+' — '+(verb?ACTION_LABELS[verb]:STATUS[metric].name),canvas:{decoration:'none',showStatusIcons:'none'},elements,
   steps:[{down:isAction?[action(kind==='drive'?'drive_'+verb.replaceAll('-','_'):'app_'+verb,kind==='drive'?{drive:JSON.stringify([row.id,row.uuid])}:{app:row.id})]:[],up:[]}],feedbacks:feedbacks(kind,row,metric,isAction),
   notes:`Edit Custom name, Live status and Action separately under Style. Colours are editable boolean feedback overrides. Display text never changes the command target. ${kind==='drive'?'Profile '+row.id+'; filesystem UUID '+row.uuid:'Exact container ID '+row.id}. ${isAction?'ONE PRESS executes through existing backend safeguards. Safe unmount stops dependent apps. Command outcome is separate from current state.':''}`}
 }
 // Keep connection/result presets unchanged; they do not contain target names.
 structure.push({id:'status_results',name:'Connection and operation results',definitions:['status','result']})
 for(const d of c.state.drives) {
  const ids=[]
  for(const metric of ['mount','power','monitor','recovery']){const id='layout_'+metric+'_'+d.id;ids.push(id);presets[id]=targetButton('drive',d,metric)}
  for(const [verb,metric] of [['sleep','power'],['mount','mount'],['unmount','mount'],['start-monitoring','monitor'],['stop-monitoring','monitor']]){const id='layout_operate_'+verb+'_'+d.id;ids.push(id);presets[id]=targetButton('drive',d,metric,verb)}
  structure.push({id:'layout_drive_'+d.id,name:d.name+' · '+d.uuid,definitions:ids})
 }
 for(const a of c.state.apps){
  const id='layout_app_'+a.id,ids=[id];presets[id]=targetButton('app',a,'app')
  for(const verb of ['start','stop','restart']){const id='layout_operate_'+verb+'_'+a.id;ids.push(id);presets[id]=targetButton('app',a,'app',verb)}
  structure.push({id:'layout_app_'+a.id,name:a.name+' · '+a.id,definitions:ids})
 }
 return {presets,structure}
}
