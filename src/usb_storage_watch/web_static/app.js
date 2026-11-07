/* USB Storage Watch 2.0 — approved UI connected to authenticated DEV9 APIs.
 * TEST-ONLY integration; actual disk operations are broker-guarded.
 */
'use strict';
const INITIAL=()=>({
  drives:[],history:[],discoveredImages:[],smtp:{host:'',port:587,security:'starttls',username:'',sender:'',recipient:''},
  lan:false,lanSecure:'https',lanDraftSecure:'https',lanAddress:'',lanFingerprint:'',certificateAvailable:false,formattingResult:null,lastRefresh:'Not refreshed',historyUpdatedAt:'Never',
  selectedPrepare:null,selectedImageDrive:null,imageTab:'configured',imageImportMode:'scan',selectedDiscovered:'',
  historyDrive:'all',advancedDrive:null,uploadName:''
});
let state=INITIAL();
const $=(sel,root=document)=>root.querySelector(sel);
const $$=(sel,root=document)=>Array.from(root.querySelectorAll(sel));
const esc = s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const attr=esc;
const find=id=>state.drives.find(d=>d.id===id);
const configured=()=>state.drives.filter(d=>d.configured);
const ago=()=>new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
const icons={
 overview:'<rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/>',
 flash:'<rect x="8" y="2.5" width="8" height="19" rx="2"/><path d="M10 2.5V1M14 2.5V1M10 18h4M10.5 7.5h3"/>',
 ssd:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M6 9h12M7 15h.01M11 15h.01"/>',
 hdd:'<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/><path d="M16 16l3 3"/>',
 unknown:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 8h10M7 13h7"/>',
 images:'<rect x="4" y="3" width="13" height="14" rx="2"/><path d="M8 7h5M8 11h4M8 20h11a2 2 0 0 0 2-2V7"/>',
 apps:'<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><path d="M15 17h6M18 14v6"/>',
 prepare:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 9h10M8 15h.01M12 15h.01"/>',
 history:'<path d="M3 12a9 9 0 1 0 2.6-6.4M3 4v5h5"/><path d="M12 7v5l3 2"/>',
 email:'<rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="M3 6l9 7 9-7"/>',
 integrations:'<path d="M8 8l-3 3a3 3 0 0 0 4 4l3-3M16 16l3-3a3 3 0 0 0-4-4l-3 3"/><path d="M9 15l6-6"/>',
 advanced:'<circle cx="12" cy="12" r="3.2"/><path d="M4.5 8.5l-1-1.5 3-3 1.5 1a8 8 0 0 1 2-1l.5-2h4l.5 2a8 8 0 0 1 2 1l1.5-1 3 3-1 1.5a8 8 0 0 1 1 2l2 .5v4l-2 .5a8 8 0 0 1-1 2l1 1.5-3 3-1.5-1a8 8 0 0 1-2 1l-.5 2h-4l-.5-2a8 8 0 0 1-2-1l-1.5 1-3-3 1-1.5a8 8 0 0 1-1-2l-2-.5v-4l2-.5a8 8 0 0 1 1-2z" transform="translate(1 -1) scale(.92)"/>',
 back:'<path d="M19 12H5M12 5l-7 7 7 7"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.5 8a7 7 0 0 1 12-1L20 12M4 12l1.5 5a7 7 0 0 0 12-1"/>',
 eject:'<path d="M4 15l8-11 8 11zM4 20h16"/>',
 folder:'<path d="M3 6h7l2 2h9v11H3z"/>',
 check:'<path d="M5 12l5 5L20 7"/>',
 warning:'<path d="M12 3l10 18H2L12 3z"/><path d="M12 9v5M12 17v.01"/>',
 lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 1 1 8 0v3"/>',
 copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3"/>',
 upload:'<path d="M12 16V3M6 9l6-6 6 6M4 17v4h16v-4"/>',
 moon:'<path d="M20.5 13.4A8.7 8.7 0 0 1 10.6 3.5 8.8 8.8 0 1 0 20.5 13.4z"/>',
 chevron:'<path d="M7 10l5 5 5-5"/>'
};
function icon(name,className='icon-inline'){return `<svg class="${className}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">${icons[name]||icons.unknown}</svg>`;}
const NAV=[['overview','Overview','overview'],['images','Virtual Disk Images','images'],['apps','Docker & Applications','apps'],['prepare','Prepare Drive','prepare'],['history','Event History','history'],['email','Email & Notifications','email'],['integrations','Integrations','integrations'],['advanced','Advanced Settings','advanced']];
// Feedback belongs to the action that started it, never to whichever page is now open.
const actionFeedback=new Map();
const recoveryFeedbackIncidents=new Map();
let confirmationSequence=0;
const immediateActions=new Set(['nav','menu','notifications','clear-notifications','close-modal','manage-drive','open-images','open-drive-history','image-tab','stepper-adjust','stepper-reset','docker-collapse','docker-image-none','docker-reload','network-step']);
const specializedActions=new Set(['applications-refresh','docker-save','timings-save','refresh-events','docker-start','docker-stop','docker-restart','app-review','app-save','app-cancel','entry-reconnect','entry-review','entry-remove','entry-apply','entry-cancel']);
function feedbackKey(action,id='',value='',scope=route()){return JSON.stringify([scope,action,id||'',value||'']);}
function feedbackMarkup(key,label=''){const r=actionFeedback.get(key),message=r?.visible===false?'':r?.message||'',name=r?.label||label;return `<span class="action-status ${r?.error?'error':''}" data-action-status="${attr(key)}" data-action-label="${attr(name)}" role="status" aria-live="polite" aria-atomic="true" aria-busy="${!!r?.busy}" ${message?'':'hidden'}><span class="action-status-label">${message&&name?esc(name)+': ':''}</span><span class="action-status-message">${esc(message)}</span></span>`;}
function B(label,action,opts={}){
 const tracked=action!=='boot-save'&&!immediateActions.has(action)&&!specializedActions.has(action);
 const scope=['confirmed-action','confirm-real-format'].includes(action)?'dialog-'+(++confirmationSequence):route();
 const key=tracked?feedbackKey(action,opts.id,opts.value,scope):'',r=actionFeedback.get(key);
 const button=`<button type="button" class="button ${opts.class||''}" data-action="${attr(action)}"${opts.id?` data-id="${attr(opts.id)}"`:''}${opts.value?` data-value="${attr(opts.value)}"`:''}${tracked?` data-feedback-key="${attr(key)}" data-feedback-label="${attr(label)}" data-base-disabled="${!!opts.disabled}" aria-busy="${!!r?.busy}"`:''}${opts.disabled||r?.busy?' disabled':''}>${opts.icon?icon(opts.icon,'button-icon'):''}${esc(label)}</button>`;
 return tracked?`<span class="action-control">${button}${feedbackMarkup(key,label)}</span>`:button;
}
function syncActionFeedback(key){
 const r=actionFeedback.get(key);if(!r)return;
 $$('[data-action-status]').filter(el=>el.dataset.actionStatus===key).forEach(el=>{const label=r.label||el.dataset.actionLabel||'';$('.action-status-label',el).textContent=r.message&&label?label+': ':'';$('.action-status-message',el).textContent=r.message;el.hidden=!r.message||r.visible===false;el.classList.toggle('error',!!r.error);el.setAttribute('aria-busy',String(!!r.busy));});
 $$('[data-feedback-key]').filter(el=>el.dataset.feedbackKey===key).forEach(el=>{el.disabled=el.dataset.baseDisabled==='true'||!!r.busy;el.setAttribute('aria-busy',String(!!r.busy));});
}
function actionNotice(context,message,error=false){
 if(context?.record&&actionFeedback.get(context.key)!==context.record)return {message:String(message),error};
 if(context){const r=actionFeedback.get(context.key);if(r){r.message=String(message);r.error=error;syncActionFeedback(context.key);}}
 toast(message,error);
 return {message:String(message),error};
}
function actionProgress(context,message){if(context){const r=actionFeedback.get(context.key);if(r&&(!context.record||r===context.record)){r.message=message;syncActionFeedback(context.key);}}}
function pendingLabel(button){
 const action=button.dataset.action||button.closest('form')?.dataset.form||'',label=button.textContent.trim();
 if(action==='image-toggle-mount')return label.startsWith('Unmount')?'Unmounting image…':'Mounting image…';
 if(action.includes('copy'))return 'Copying…';
 if(action.includes('refresh')||action==='rescan-images')return 'Refreshing…';
 if(action==='toggle-monitoring')return label.startsWith('Stop')?'Stopping monitoring…':'Starting monitoring…';
 if(action==='confirmed-action')return 'Working…';
 if(action==='docker-start')return 'Starting container…';
 if(action==='docker-stop')return 'Stopping container…';
 if(action==='docker-restart')return 'Restarting container…';
 if(action.endsWith('save'))return 'Saving…';
 return 'Working…';
}
// A button row has one current result. Retain older busy records for duplicate
// request protection, but never bring their messages back after a newer action.
function selectActionFeedback(button,key){
 const group=button.closest('.actions,.modal-actions,.head-actions,.drive-remove-action');
 if(!group)return;
 for(const control of $$('[data-feedback-key]',group)){
   const other=control.dataset.feedbackKey,record=actionFeedback.get(other);
   if(other!==key&&record){record.visible=false;syncActionFeedback(other);}
 }
}
async function runButtonAction(button,task){
 const key=button.dataset.feedbackKey;
 if(!key){try{return await task(null);}catch(e){toast(operationError(e),true);}return;}
 if(actionFeedback.get(key)?.busy)return;
 selectActionFeedback(button,key);
 const record={visible:true,message:pendingLabel(button),label:button.dataset.feedbackLabel||button.textContent.trim(),busy:true,error:false},context={key,record};actionFeedback.set(key,record);syncActionFeedback(key);
 try{
   const result=await task(context),r=actionFeedback.get(key);
   if(r===record&&result?.message){r.message=result.message;r.error=!!result.error||result.ok===false;}
   else if(r===record&&!r.error&&r.message===pendingLabel(button))r.message=$('#modal-root .modal')?'Review open. Confirm to continue.':'Completed.';
 }catch(e){actionNotice(context,operationError(e),true);}
 finally{if(actionFeedback.get(key)===record){record.busy=false;syncActionFeedback(key);}}
}
function operationError(error){
 const raw=errorMessage(error);
 if(error?.uncertain)return raw+(/[.!?]$/.test(raw)?'':'.')+' The result is not confirmed. Refresh the current state before trying again; this request was not repeated.';
 if(/Filesystem has active users/.test(raw))return 'This storage is in use, so the action was not completed. Stop the container or application using it and close files or terminal windows opened in this folder, then try again. '+raw;
 return raw;
}
function submitControl(label,kind,id='',disabled=false){const key=feedbackKey('submit-'+kind,id);const r=actionFeedback.get(key);return `<span class="action-control"><button type="submit" class="button button-primary" data-feedback-key="${attr(key)}" data-feedback-label="${attr(label)}" data-base-disabled="${disabled}" aria-busy="${!!r?.busy}" ${disabled||r?.busy?'disabled':''}>${esc(label)}</button>${feedbackMarkup(key,label)}</span>`;}

const chip=(label,kind='muted')=>`<span class="chip ${kind}">${esc(label)}</span>`;
const route=()=>decodeURIComponent(location.hash.slice(1)||'overview');
const header=(eyebrow,title,desc='',extra='')=>`<div class="page-head"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1>${desc?`<p>${esc(desc)}</p>`:''}</div>${extra?`<div class="head-actions">${extra}</div>`:''}</div>`;
const driveIcon=(drive)=>`<span class="icon-device" title="${attr(drive.kind==='flash'?'USB flash drive':drive.kind==='hdd'?'Hard disk drive':drive.kind==='ssd'?'Solid-state drive':'Storage device')}">${icon(drive.kind||'unknown','')}</span>`;
const driveName=d=>esc(d.name);
const field=(label,id,value='',type='text',hint='',other='')=>`<div class="field"><label for="${attr(id)}">${esc(label)}</label><input id="${attr(id)}" type="${attr(type)}" value="${attr(value)}" ${other}>${hint?`<small>${esc(hint)}</small>`:''}</div>`;
const notifications=[];
let notificationTimer=null;
function toast(msg,error=false){
 const text=String(msg),last=notifications[0];
 if(last&&last.message===text&&last.error===error){last.count++;last.time=ago();}
 else notifications.unshift({message:text,error,count:1,time:ago()});
 notifications.splice(100);
 const node=document.createElement('div');node.className='toast'+(error?' error':'');node.title=text;
 const preview=document.createElement('span');preview.textContent=text;node.append(preview);
 $('#toasts').replaceChildren(node);$('#notification-count').textContent=String(notifications.length);
 clearTimeout(notificationTimer);
 if(!error)notificationTimer=setTimeout(()=>node.remove(),5300);
}
function showNotifications(){
 modal(`<div class="modal-title"><h2 id="modal-title">Messages</h2></div><div class="notification-history">${notifications.map(n=>`<div class="callout ${n.error?'danger':'success'}"><div><p>${esc(n.message)}</p><small>${esc(n.time)}${n.count>1?' · repeated '+n.count+' times':''}</small></div></div>`).join('')||'<p>No messages in this browser session.</p>'}</div><div class="modal-actions">${B('Clear messages','clear-notifications',{class:'button-utility',disabled:!notifications.length})}${B('Close','close-modal',{class:'button-neutral'})}</div>`);
}
function clearNotifications(){clearTimeout(notificationTimer);notifications.length=0;$('#toasts').replaceChildren();$('#notification-count').textContent='0';showNotifications();}
function closeMenu(){const side=$('#sidebar');side.classList.remove('open');$('#mobile-backdrop').hidden=true;const btn=$('[data-action="menu"]');if(btn)btn.setAttribute('aria-expanded','false');}
let settingsSection=null;
function navigate(to,section=null){settingsSection=to==='advanced'&&['management-token-panel','network-panel'].includes(section)?section:null;closeMenu();if(route()!==to){location.hash=to}else{render();loadForRoute();}}
function focusSettingsSection(){
 if(route()!=='advanced'||!settingsSection)return;
 const heading=document.querySelector('#'+settingsSection+' h2');settingsSection=null;
 if(heading){heading.focus({preventScroll:true});heading.scrollIntoView({block:'start',behavior:'instant'});}
}
let modalPending=false;
function modal(html,variant=''){closeTouchSelect();modalPending=false;const root=$('#modal-root');root.innerHTML=`<div class="modal-overlay"><div class="modal ${variant}" role="dialog" aria-modal="true" aria-labelledby="modal-title">${html}</div></div>`;enhanceSelects(root);const focus=$('input:not([type=hidden]),button',root);focus?.focus();}
function closeModal(){ closeTouchSelect();modalPending=false;$('#modal-root').innerHTML=''; }
function modalWorking(message='Request submitted. Waiting for the host to verify the result…'){
 if(modalPending)return false;
 const root=$('#modal-root');if(!root?.querySelector('.modal'))return false;
 modalPending=true;
 root.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=true);
 const status=document.createElement('div');status.className='modal-progress';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 status.innerHTML='<span class="busy-spinner" aria-hidden="true"></span><span></span>';
 status.querySelector('span:last-child').textContent=message;
 root.querySelector('.modal-actions')?.before(status);
 return true;
}
function modalWorkFinished(){
 if(!modalPending)return;
 modalPending=false;
 const root=$('#modal-root');root.querySelector('.modal-progress')?.remove();
 root.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=false);
 syncTouchSelects(root);
}

async function copy(value){
 if(navigator.clipboard&&window.isSecureContext){try{await navigator.clipboard.writeText(value);}catch(_){throw Error('Copy failed. Select the displayed text and copy it manually.');}}
 else{const el=document.createElement('textarea');el.value=value;el.className='clipboard-helper';document.body.append(el);el.select();try{if(!document.execCommand('copy'))throw Error('Copy not available in this browser. Select and copy the displayed text.');}finally{el.remove();}}
 toast('Copied to clipboard.');return {message:'Copied to clipboard.'};
}
function overview(){const ds=configured();return header('Your storage, at a glance','USB drive overview','View all configured drives and manage each one independently.',B('Add USB drive','open-add-drive',{class:'button-add',icon:'plus'})+B('Refresh drives','refresh-drives',{class:'button-utility',icon:'refresh'}))+`<div class="stack"><div class="stat-grid"><div class="stat"><strong>${ds.length}</strong><span>Configured drives</span></div><div class="stat"><strong>${ds.filter(d=>d.monitoring).length}</strong><span>Monitoring enabled</span></div><div class="stat"><strong>${ds.filter(d=>d.connected===false).length}</strong><span>Disconnected</span></div></div><section class="stack">${ds.map(driveCard).join('')||`<div class="card empty"><strong>No drives configured</strong><p>Add your first supported USB drive to begin.</p></div>`}</section><p class="mini">Last refreshed: ${esc(state.lastRefresh)} · Each card shows its own monitoring and recovery state.</p></div>`;}
function activeDriveRecovery(d){
 if(d.stale)return null;
 const p=d.progress||{};
 return p.incident&&['stopping','waiting_stop','waiting_return','return_failed','waiting_manual','waiting','running','verify','applications','verifying','confirming'].includes(p.code)?p:null;
}
function discardPreRecoveryFeedback(d,progress){
 if(!progress||recoveryFeedbackIncidents.get(d.id)===progress.incident)return;
 recoveryFeedbackIncidents.set(d.id,progress.incident);
 for(const action of ['toggle-mount','reconnect-drive','mount-location','sleep-hdd','toggle-monitoring']){
   const record=actionFeedback.get(feedbackKey(action,d.id,'','drive/'+d.id));
   if(record)record.visible=false;
 }
}
function driveRecoveryMarkup(progress){
 if(!progress)return '';
 const busy=['stopping','running','verify','applications','verifying'].includes(progress.code);
 return `<span class="action-status drive-recovery-progress" data-recovery-progress="${attr(progress.code)}" role="status" aria-live="polite" aria-atomic="true" aria-busy="${busy}"><span class="action-status-message"><strong>${esc(progress.title||'Automatic recovery')}</strong>${progress.detail?' — '+esc(progress.detail):''}</span></span>`;
}
function usbIdentityMarkup(d){const u=d.usbDetails;if(!u)return '<dt>USB connection</dt><dd>Reading current connection…</dd>';return `<dt>${u.last_known?'Last-known USB connection':'Current USB connection'}</dt><dd class="path">${esc(u.topology||u.port||'Unavailable')}${u.bus_address?' · '+esc(u.bus_address):''}</dd><dt>USB VID:PID</dt><dd>${esc(u.usb_ids||'Unavailable')}</dd>${u.serial?`<dt>USB serial</dt><dd class="path">${esc(u.serial)}</dd>`:''}`;}
function driveManage(d){const recoveryProgress=activeDriveRecovery(d);discardPreRecoveryFeedback(d,recoveryProgress);const imageCount=d.images.length;const eh=state.history.filter(e=>e.drive===d.id).slice(0,3);return `${header('Drive management',d.name,`Control only ${d.model}. Other drives remain independent.`,B('Back to overview','nav',{class:'button-quiet',value:'overview',icon:'back'}))}<div class="stack"><section class="card" id="drive-summary"><div class="card-header"><div class="device-identity">${driveIcon(d)}<div><h2>${driveName(d)}</h2><p>${esc(d.model)} · ${esc(d.size)} · ${esc(d.uuid)}</p></div></div>${chip(d.stale||d.monitoringUnknown?'Status pending':d.monitoring?'Monitoring on':'Monitoring off',d.stale||d.monitoringUnknown?'muted':d.monitoring?'good':'bad')}</div><div class="labelrow">${driveStatus(d)}${standbyBadge(d)}</div><dl class="info-list"><dt>Current mount</dt><dd class="path">${esc(currentMountText(d))}</dd><dt>Configured mount</dt><dd class="path">${esc(d.mount)}</dd>${usbIdentityMarkup(d)}<dt>Software reset / reconnect</dt><dd>${esc(d.usbMessage||(d.hub?'Unavailable through this USB hub':d.direct?'Available, subject to live safety checks':'Availability has not been verified'))}</dd><dt>Electrical power cut</dt><dd>Unavailable in this build — power removal is not verified.</dd></dl>${mountStateNotice(d)}${deliberateStopNotice(d)}${d.connected===false?`<div class="callout warn">Was this drive reformatted on another computer? ${B('Find and reconnect configuration','find-reformatted-drive',{id:d.id,class:'button-neutral'})} The existing settings and history will be preserved if the physical device can be verified.</div>`:''}<div class="actions ${recoveryProgress?'has-recovery-progress':''}">${B(d.mounted?'Unmount safely':'Mount drive','toggle-mount',{id:d.id,icon:d.mounted?'eject':'folder',class:d.mounted?'mount-eject':'mount-folder',disabled:d.stale})}${B('Reset USB (software)','reconnect-drive',{id:d.id,class:'button-reset',disabled:d.stale||d.mounted||!d.resetAvailable||!d.connected})}${B('Change mount location','mount-location',{id:d.id,class:'button-neutral',disabled:mountLocationBlocked(d)})}${d.kind==='hdd'||d.standbyApplicable?B('Sleep HDD now','sleep-hdd',{id:d.id,icon:'moon',disabled:d.stale||!d.mounted||!d.connected||d.standbyState==='unknown'}):''}${B(d.monitoring?'Stop monitoring':'Start monitoring','toggle-monitoring',{id:d.id,class:d.monitoring?'button-warning':'button-start'})}${driveRecoveryMarkup(recoveryProgress)}</div>${mountLocationBlocked(d)?`<p class="mini mount-location-hint">${esc(mountLocationHint(d))}</p>`:''}<p class="mini">Software reconnect does not guarantee power off/on. USB control cannot switch off a separate disk power supply.</p></section><section class="card"><h2>Automatic recovery & alerts</h2><p>Simple settings for this drive. Changes apply immediately; no separate Save button.</p>${toggleRow('Automatic recovery','Allow safe automatic remount and recovery for this drive.','recovery',d)}${toggleRow('Email notifications','Send an alert about this drive when monitoring reports an incident.','notifications',d)}</section><section class="card"><div class="section-heading"><div><h2>Recent events</h2><p>Only events for this drive appear here.</p></div>${eventRefreshControl()}${B('All event history','open-drive-history',{id:d.id,class:'button-neutral'})}</div><p id="drive-events-updated" class="mini">Last updated: ${esc(state.historyUpdatedAt)}</p><div id="drive-recent-events">${renderHistoryEntries(eh)}</div></section><section class="card remove-drive-section"><h2>Remove this drive</h2><p>Stop managing a drive you no longer use with Storage Watch. Its files and current mounts are kept.</p>${B('Remove from Storage Watch','remove-drive-review',{id:d.id,class:'button-remove',disabled:d.busy})}</section></div>`;}
function toggleRow(title,description,key,drive){const feedback=feedbackKey('drive-setting',drive.id,key),r=actionFeedback.get(feedback);return `<div class="toggle-row"><div class="toggle-copy"><strong>${esc(title)}</strong><p>${esc(description)}</p></div><span class="action-control toggle-action"><input type="checkbox" class="toggle" role="switch" data-toggle="drive-setting" data-id="${attr(drive.id)}" data-key="${attr(key)}" data-feedback-key="${attr(feedback)}" data-base-disabled="false" aria-busy="${!!r?.busy}" aria-label="${attr(title+' for '+drive.name)}" ${drive[key]?'checked':''} ${r?.busy?'disabled':''}>${feedbackMarkup(feedback)}</span></div>`;}
function imagesPage(){const drives=configured();let d=find(state.selectedImageDrive);if(!d||!d.configured){d=drives[0];state.selectedImageDrive=d?.id;}if(!d)return header('Storage management','Virtual Disk Images (.img)')+'<div class="card empty">Add a USB drive first.</div>';
 const tabs=[['create','Create new'],['import','Add existing'],['configured',`Already configured (${d.images.length})`]];
 return `${header('Storage management','Virtual Disk Images (.img)','Manage images for one selected USB drive. Browse or import images without typing filesystem paths.')}
 <div class="stack"><section class="card"><div class="field" data-style="usw-inline-6"><label for="image-drive">Images belonging to</label><select id="image-drive" data-change="image-drive">${drives.map(x=>`<option value="${attr(x.id)}" ${x.id===d.id?'selected':''}>${driveName(x)} · ${esc(x.size)}</option>`).join('')}</select></div><div class="callout" data-style="usw-inline-5">${icon('images')} <div>A virtual disk image is a file stored on a drive that behaves like a separate disk. You can use it for backups or application storage, with a fixed capacity. It does not restrict applications from writing elsewhere.</div></div>
 ${!d.mounted?`<div class="callout warn">${icon('warning')}<div><strong>${d.stale?'Drive status is not verified yet.':'This USB drive is not mounted.'}</strong> Mount or verify the selected USB drive in Manage Drive before creating, scanning or importing images. Registered images remain listed below. ${B('Open Manage Drive','manage-drive',{id:d.id,class:'button-neutral'})}</div></div>`:''}
 <div class="tabs" role="tablist" aria-label="Virtual disk image actions">${tabs.map(([id,label])=>`<button class="tab ${state.imageTab===id?'active':''}" role="tab" aria-selected="${state.imageTab===id}" data-action="image-tab" data-value="${id}">${esc(label)}</button>`).join('')}</div><div class="tab-panel" role="tabpanel">${state.imageTab==='configured'?configuredImages(d):state.imageTab==='create'?createImageForm(d):importImageForm(d)}</div></section></div>`;
}
function renderHistoryEntries(entries){return entries.length?entries.map(e=>{const d=find(e.drive);return `<div class="history-entry"><span class="history-dot ${esc(e.type)}"></span><div class="history-content"><h3>${esc(e.title)}</h3><p>${esc(e.detail)}</p><div class="history-meta">${esc(d?.name||'Unknown drive')} · ${esc(humanTime(e.time))}</div>${e.outageStarted?`<div class="history-meta history-outage-start">Outage started: ${esc(humanTime(e.outageStarted))}</div>`:''}</div></div>`;}).join(''):'<div class="empty"><strong>No events recorded</strong><p>Recovery events and other incidents will appear here.</p></div>';}
function timingControl({key,label,step=1,min,max,hint='',value,inputId=''}){
 return `<div class="field timing-setting"><label for="${attr(inputId||'timing-'+key)}">${esc(label)}</label><div class="timing-row"><div class="stepper" data-stepper="${attr(key)}">${B('−','stepper-adjust',{id:key,value:'-'+step,class:'button-step'})}<input id="${attr(inputId||'timing-'+key)}" type="number" data-timing="${attr(key)}" value="${attr(value)}" min="${min}" max="${max}" step="${step}" required aria-label="${attr(label)}">${B('+','stepper-adjust',{id:key,value:'+'+step,class:'button-step'})}${B('Reset','stepper-reset',{id:key,class:'button-reset'})}</div><small class="timing-explain">${esc(hint)}</small></div></div>`;
}
function settingGroup(title,description,items,d){return `<div class="setting-group"><h3>${esc(title)}</h3><p class="small">${esc(description)}</p><div class="setting-grid">${items.map(item=>timingControl({...item,value:settingsValues(d,'timings')[item.key]})).join('')}</div></div>`;}
function standbyBadge(d){
 if(d.kind==='ssd'||d.kind==='flash'||d.standbyState==='not-applicable'||(d.kind!=='hdd'&&!d.standbyApplicable))return chip('HDD sleep: Not supported','muted');
 const label=d.stale?'Status pending':d.connected===false?'Unavailable':d.standby||'Unknown';
 return chip('HDD: '+label,d.stale||d.connected===false?'muted':d.standbyState==='standby'?'good':d.standbyState==='active'?'warn':'muted');
}

function render(){rememberAppExpansion();const current=route();let content='',active=current.split('/')[0],label='';
 if(activeTouchSelect?.route===current){touchRenderPending=true;return;}
 const body=$('#main-content');if(!body)return;
 const focus=body.contains(document.activeElement)?document.activeElement.id:'';
 const certificate=$('#integration-certificate',body);if(certificate)state.integrationCertificateOpen=certificate.open;
 const networkDetails=$$('#network-panel details',body).map(el=>el.open);
 const storageDetails=new Set($$('details.application-storage-details[open]',body).map(el=>el.dataset.storageKey));
 if(active==='drive'){
   const id=current.split('/')[1],d=find(id);content=d?.configured?driveManage(d):header('Drive management','Drive not found')+'<div class="callout warn">This drive is not configured. Return to Overview.</div>';label='Manage Drive';
 }else if(active==='overview'){content=overview();label='Overview';}
 else if(active==='images'){content=imagesPage();label='Virtual Disk Images';}
 else if(active==='apps'){content=appsPage();label='Docker & Applications';}
 else if(active==='prepare'){content=preparePage();label='Prepare Drive';}
 else if(active==='history'){content=historyPage();label='Event History';}
 else if(active==='email'){content=emailPage();label='Email & Notifications';}
 else if(active==='integrations'){content=integrationsPage();label='Integrations';}
 else if(active==='advanced'){content=advancedPage();label='Advanced Settings';}
 else {navigate('overview');return;}
 $('#crumb').textContent=label;
 $('#main-nav').innerHTML=NAV.map(([id,title,ico],i)=>`${i===5||i===7?'<div class="nav-sep"></div>':''}<button class="nav-link" type="button" data-action="nav" data-value="${id}" ${active===id?'aria-current="page"':''}>${icon(ico,'')}<span>${esc(title)}</span></button>`).join('');
 closeTouchSelect();body.innerHTML=content;enhanceSelects(body);if(active==='apps')syncAppControlLocks();updateSettingsButtons();
 $$('#network-panel details',body).forEach((el,i)=>{if(i<networkDetails.length)el.open=networkDetails[i];});
 $$('details.application-storage-details',body).forEach(el=>{el.open=storageDetails.has(el.dataset.storageKey);});
 if(focus)document.getElementById(focus)?.focus({preventScroll:true});
}
function openMountLocation(d){if(mountLocationBlocked(d)){toast(mountLocationHint(d),true);return;}modal(`<div class="modal-title">${icon('folder')}<h2 id="modal-title">Change mount location</h2></div><p>Inspect affected paths before committing a mount change. Existing files are not moved.</p><dl class="info-list"><dt>Drive</dt><dd>${driveName(d)}</dd><dt>Current location</dt><dd class="path">${esc(d.mount)}</dd></dl>${field('New mount folder','modal-mount-path',d.mount,'text','','autocomplete="off"')}${d.images.length?`<div class="callout warn" data-style="usw-inline-7">${icon('warning')}<div><strong>${d.images.length} dependent virtual disk image(s)</strong> use this drive. A real mount-location change requires dependency verification, migration preview and rollback.</div></div>`:''}${d.mounted?`<div class="callout warn" data-style="usw-inline-10">${icon('warning')}<div>Unmount the drive before changing the configured mount folder.</div></div>`:''}<div class="modal-actions">${B('Cancel','close-modal',{class:'button-quiet'})}${B('Preview changes','mount-location-preview',{id:d.id,class:'button-primary'})}</div>`);}
/* USB Storage Watch 2.0 — verified-backend frontend adapter.
 * The approved view/CSS above stays unchanged. No simulated actions are permitted.
 * Every mutation is sent through the existing authenticated, drive-scoped API.
 */
let csrfToken=null;
let apiBusy=false;
let lastRoute='';
const deviceMeta=new Map();
const detailCache=new Map();
const realDriveState=new Map();
const IMAGE_NAME=/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;
const readableSize=(n)=>typeof n==='number'?n>=1024**4?(n/1024**4).toFixed(1)+' TiB':n>=1024**3?(n/1024**3).toFixed(1)+' GiB':(n/1024**2).toFixed(0)+' MiB':n||'Unknown size';
const knownKind=(raw)=>['flash','hdd','ssd'].includes(raw)?raw:'unknown';
const humanTime=(value)=>{if(!value)return 'Not available';const d=new Date(value);return Number.isNaN(d.getTime())?'Not available':d.toLocaleString([], {hourCycle:'h23'});};
function errorMessage(err){return err instanceof Error?err.message:'Operation failed.';}
function hostConnection(available){
 const label=available?'Connected to host':'Host unavailable';
 const top=$('.top-pill');if(top)top.textContent=label.toUpperCase();
 const side=$('.sidebar-meta');if(side){side.innerHTML='<span class="status-light"></span>'+esc(label);side.classList.toggle('unavailable',!available);}
}
async function apiRequest(action,{drive=null,data=null,method=null,timeout=null}={}){
  const write=method==='POST'||data!==null;
  const [actionName,query]=action.split("?",2);
  const base=drive===null?`/api/${encodeURIComponent(actionName)}`:`/api/drives/${encodeURIComponent(drive)}/${encodeURIComponent(actionName)}`;
  const path=base+(query?"?"+query:"");
  const headers={'Accept':'application/json'};
  if(write){headers['Content-Type']='application/json';headers['X-USW-Request']='1';if(csrfToken)headers['X-CSRF-Token']=csrfToken;}
  let controller=null,timer=null;
  const limit=timeout??(write?450000:30000);
  if(limit){controller=new AbortController();timer=setTimeout(()=>controller.abort(),limit);}
  try{
    const response=await fetch(path,{method:write?'POST':'GET',credentials:'same-origin',headers,body:write?JSON.stringify(data||{}):undefined,signal:controller?.signal});
    let body;try{body=await response.json();}catch(_){throw Error(`Unexpected server response (${response.status}).`);}
    if(!response.ok){if(response.status===401&&action!=='login'&&action!=='session'){showLogin();}
      const error=Error(body.error||`Server returned ${response.status}.`);error.status=response.status;throw error;}
    hostConnection(true);return body;
  }catch(err){
    if(err.name==='AbortError'||err instanceof TypeError||/Administration service unavailable/.test(err.message))hostConnection(false);
    if(err.name==='AbortError'){const error=Error(write?'The host did not return the operation result in time.':'The host did not answer the status request in time.');error.uncertain=write;throw error;}
    if(write&&(!err.status||err.status>=500))err.uncertain=true;
    throw err;
  }
  finally{if(timer)clearTimeout(timer);}
}
async function waitLanOperation(operation){
 if(!operation)throw Error('The host did not provide a network operation ID.');
 const deadline=Date.now()+90000;
 while(Date.now()<deadline){
   await new Promise(resolve=>setTimeout(resolve,500));
   let info;
   try{info=await apiRequest('lan-status',{timeout:2500});}
   catch(e){if(e instanceof TypeError||/status request in time|Administration service unavailable/.test(errorMessage(e)))continue;throw e;}
   if(info.operation!==operation)throw Error('The network operation changed. Check the current settings before trying again.');
   if(info.phase==='complete')return info;
   if(info.phase==='failed')throw Error(info.message||'The previous LAN configuration was restored.');
 }
 throw Error('The new listener has not reported a verified result. Check it from localhost.');
}
function localDashboard(){return ['', 'localhost','127.0.0.1','[::1]'].includes(location.hostname);}
function networkHandoff({enabled,scheme,address},message,operation=''){
 const destination=enabled?scheme+'://'+address+':8765':'';
 modal(`<div class="modal-title"><h2 id="modal-title">Check network access</h2></div><div class="callout warn"><div>${esc(message)}</div></div><p class="network-result">${enabled?'Open the network dashboard to check the new connection. You may need to sign in again.':'Disabling LAN access closes dashboards opened through the network address.'} On the host computer, open <strong>http://localhost:8765</strong> and check Advanced Settings for the verified result.</p>${destination?`<p class="network-result"><a class="button button-primary" href="${attr(destination)}">Open network dashboard</a></p>`:''}${operation?`<p class="mini">Request: ${esc(operation)}</p>`:''}<div class="modal-actions">${B('Close','close-modal',{class:'button-neutral'})}</div>`);
}
async function changeLan(action,data){
 const target={enabled:data.enabled,scheme:data.scheme||state.lanSecure,address:data.address||state.lanAddress};
 const losesConnection=!localDashboard()&&(!target.enabled||target.scheme!==location.protocol.slice(0,-1)||target.address!==location.hostname);
 let result;
 try{result=await apiRequest(action,{data});}
 catch(e){
   if(e.status)throw e; // A definite server refusal; do not call it applied.
   closeModal();networkHandoff(target,'The browser lost the response. The result is unconfirmed; check the current setting before submitting another change.');return;
 }
 const label=$('#modal-root .modal-progress span:last-child');
 if(label)label.textContent='Applying network settings and waiting for the host to verify them…';
 if(losesConnection){
   closeModal();networkHandoff(target,'The host accepted the request. This page cannot verify completion after its current LAN connection closes.',result.operation);return;
 }
 try{
   const completed=await waitLanOperation(result.operation);
   await refreshSmtp({display:false});closeModal();render();
   toast(completed.message||'Network settings verified.');
 }catch(e){
   closeModal();
   try{await refreshSmtp({display:false});render();}catch(_){}
   networkHandoff(target,errorMessage(e),result.operation);
 }
}
function showLogin(message=''){
 actionFeedback.clear();recoveryFeedbackIncidents.clear();imageResults.clear();imagePreferenceFeedback.clear();
 // Static shell controls survive page renders and must not retain a prior
 // session's busy/disabled state when a logout or 401 clears the records.
 $$('[data-feedback-key]').forEach(el=>{el.disabled=el.dataset.baseDisabled==='true';el.setAttribute('aria-busy','false');});
 $$('[data-action-status]').forEach(el=>{$$('.action-status-label,.action-status-message',el).forEach(part=>part.textContent='');el.hidden=true;el.classList.remove('error');el.setAttribute('aria-busy','false');});
 resetNetwork();
 settingsDrafts.clear();resetDockerPage(); 
 closeModal();csrfToken=null;
 $('#usw-app').hidden=true;
 $('#usw-login').hidden=false;
 $('#usw-login-error').textContent=message;
 $('#usw-login-token').value='';
}
function showApp(){ $('#usw-login').hidden=true;$('#usw-app').hidden=false; }
function stateForId(id){return detailCache.get(id)||{};}
function adaptDrive(r){
 const previous=find(r.profile_id||'candidate-'+r.uuid);
 const id=r.profile_id||'candidate-'+r.uuid;
 const k=knownKind(r.media_kind);
 const mon=r.monitoring==='active';
 const drive={
   id,uuid:r.uuid||'',configured:!!r.configured,name:r.name||'USB drive',model:r.name||'USB drive',
   kind:k,size:readableSize(r.size),capacity:typeof r.size==='number'?r.size/1e9:1024,
   connected:r.connected===true?true:r.connected===false?false:null,
   mounted:r.mounted_expected===true,otherMount:r.mounted===true&&r.mounted_expected!==true,
   mountState:r.mount_state||'',mountDetail:r.mount_detail||'',mountLocations:r.mount_locations||[],mountTargetOccupied:r.mount_target_occupied===true,
   monitoring:mon,monitoringUnknown:r.monitoring==='unknown',recovery:r.recovery_enabled===true,
   notifications:previous?.notifications??false,
   standby:'Unknown',standbyState:'unknown',standbyApplicable:false,autoSleep:false,standbyIdleSeconds:1800,hub:!!r.hub,direct:r.reconnect_available===true,usbMessage:previous?.usbMessage||'',usbDetails:previous?.usbDetails||null,resetAvailable:previous?.resetAvailable===true,lastOperation:previous?.lastOperation||null,
   mount:r.mountpoint||'',lastSeen:r.observed_at?humanTime(r.observed_at):'Awaiting update',
   stale:!!r.stale, busy:!!r.busy,error:r.error||'',progress:r.progress||{},deliberateStopped:r.deliberate_stopped_apps||[],
   images:previous?.images||[],containers:previous?.containers||[],
   timings:previous?.timings||{check:15,confirm:2,recovery:60,returntimeout:5,usbwait:20,sleep:15}
 };
 const detail=detailCache.get(id);
 if(detail)enrichDrive(drive,detail,{includeStatus:false});
 if(r.standby)enrichDrive(drive,{status:{standby:r.standby}});
 return drive;
}
function enrichDrive(d,detail,{includeStatus=true}={}){
 const v=detail.status||{},c=detail.config?.config||{};
 if(includeStatus&&v.health){d.connected=v.health.detected===true;d.healthDetail=v.health.detail||'';}
 if(includeStatus&&typeof v.mounted_expected==='boolean')d.mounted=v.mounted_expected;
 if(includeStatus&&typeof v.mounted==='boolean')d.otherMount=v.mounted&&!d.mounted;
 if(includeStatus&&typeof v.mount_state==='string'){d.mountState=v.mount_state;d.mountDetail=v.mount_detail||'';}
 if(includeStatus&&Array.isArray(v.mount_locations))d.mountLocations=v.mount_locations;
 if(includeStatus&&'mount_target_occupied' in v)d.mountTargetOccupied=v.mount_target_occupied===true;
 if(includeStatus&&v.service){d.monitoring=v.service.ActiveState==='active';d.monitoringUnknown=!['active','inactive','failed'].includes(v.service.ActiveState);}
 if(v.notifications!==undefined)d.notifications=v.notifications===true;
 if(includeStatus&&v.recovery)d.recovery=v.recovery.mount===true;
 if(includeStatus&&v.discovered){const kind=knownKind(v.discovered.media_kind);if(kind!=='unknown'||d.kind==='unknown')d.kind=kind;d.model=v.discovered.model||d.model;}
 if(includeStatus&&v.standby){
   d.standbyState=v.standby.state||'unknown';
   d.standbyApplicable=v.standby.applicable===true;
   d.standby=v.standby.state==='active'?'In use':v.standby.state==='idle'?'Idle':v.standby.state==='standby'?'Spun down':v.standby.label||'Unknown';
   if(typeof v.standby.enabled==='boolean')d.autoSleep=v.standby.enabled;
   if(Number.isFinite(v.standby.idle_seconds))d.standbyIdleSeconds=v.standby.idle_seconds;
 }
 if(includeStatus&&v.usb){d.hub=v.usb.direct===false;d.direct=v.usb.direct===true&&v.usb.software_reconnect===true;d.usbMessage=v.usb.message||'';d.usbDetails=v.usb;d.resetAvailable=v.usb.manual_reset_available===true;}
 if(includeStatus&&Object.hasOwn(v,'last_operation'))d.lastOperation=v.last_operation;
 if(includeStatus&&v.progress)d.progress=v.progress;
 if(includeStatus&&Object.hasOwn(v,'deliberate_stopped_apps'))d.deliberateStopped=v.deliberate_stopped_apps||[];
 if(includeStatus&&v.observed_at)d.lastSeen=humanTime(v.observed_at);
 if(c.docker)d.containers=(c.docker.containers||[]).map(x=>x.name||x.source||'Application');
 if(c.standby){d.autoSleep=c.standby.enabled===true;d.standbyIdleSeconds=c.standby.idle_seconds||1800;}
 if(c.monitor&&c.recovery&&c.usb)d.timings={check:c.monitor.interval,confirm:c.monitor.observations,recovery:c.recovery.wait,returntimeout:c.recovery.return_timeout_minutes??5,usbwait:c.usb.enumeration_seconds,sleep:Math.round((c.standby?.idle_seconds||900)/60)};
 if(detail.images)d.images=(detail.images.images||[]).map(im=>({id:im.name,uuid:im.uuid,size:typeof im.size==='number'&&im.size>0?(im.size/1024**3).toFixed(1):'Unknown',
   mounted:im.mount_state==='mounted'||im.mounted,autoRestore:im.enabled!==false,access:im.access_message||im.access_state||'Unknown',path:im.image,folder:im.mountpoint}));
 for(const im of d.images||[]){const key=preferenceKey(d.id,im.uuid),pending=imagePreferences.get(key),feedback=imagePreferenceFeedback.get(key);if(pending)im.autoRestore=pending.desired;if(feedback){im.preferenceMessage=feedback.message;im.preferenceError=feedback.error;}}
}
let fleetReadSerial=0,fleetEpoch=0;
function forgetDrive(id){
 detailCache.delete(id);deviceMeta.delete(id);realDriveState.delete(id);dockerPage.loaded=false;
 for(const cache of [settingsDrafts,imagePreferences,imagePreferenceFeedback])for(const key of cache.keys())if(key.startsWith(id+':'))cache.delete(key);
 state.history=state.history.filter(e=>e.drive!==id);
 state.discoveredImages=state.discoveredImages.filter(im=>im.drive!==id);
}
function reconcileDriveSelections(){
 const first=configured()[0]?.id||null;
 for(const key of ['selectedImageDrive','advancedDrive']){
   if(!find(state[key])?.configured){
     state[key]=first;
     if(key==='selectedImageDrive')state.selectedDiscovered='';
   }
 }
 if(state.historyDrive!=='all'&&!find(state.historyDrive)?.configured)state.historyDrive='all';
}
async function refreshFleet({display=true}={}){
 const serial=++fleetReadSerial,epoch=fleetEpoch;
 const result=await apiRequest('fleet-status');
 if(serial!==fleetReadSerial||epoch!==fleetEpoch)return false;
 if(!Array.isArray(result.drives))throw Error('The host returned an incomplete drive list. Previous cards are retained.');
 const oldConfigured=state.drives.filter(d=>d.configured);
 state.drives=result.drives.map(adaptDrive);
 state.lastRefresh=humanTime(result.refreshed_at);
 for(const old of oldConfigured)if(!find(old.id)?.configured)forgetDrive(old.id);
 reconcileDriveSelections();
 if(display)render();
 return true;
}
async function refreshDetail(id,{images=false,renderPage=true}={}){
 if(!id||!find(id)?.configured)return;
 const config=await apiRequest('config',{drive:id});
 const status=await apiRequest('status',{drive:id});
 const detail={...(detailCache.get(id)||{}),status,config};
 if(images){detail.images=await apiRequest('application-images',{drive:id});}
 if(!find(id)?.configured)return;
 detailCache.set(id,detail);
 const d=find(id);if(d){enrichDrive(d,detail);syncSettingsDrafts(d,config);}
 if(renderPage)render();
}
async function refreshHistory({display=true}={}){
 const result=await apiRequest('fleet-events');
 state.history=(result.events||[]).map(e=>({drive:e.drive_id||e.profile_id,title:e.title||e.message||e.code||'Storage event',time:e.time||e.recorded_at||new Date().toISOString(),outageStarted:e.outage_started||null,type:/fail|error|outage|disconnected/i.test(e.title||'')?'warn':'good',detail:Array.isArray(e.lines)?e.lines.join(' · '):(e.detail||e.message||'')}));
 const seen=new Set();state.history=state.history.filter(e=>{const k=JSON.stringify([e.drive,e.time,e.title,e.detail]);if(seen.has(k))return false;seen.add(k);return true;}).sort((a,b)=>new Date(b.time)-new Date(a.time));
 state.historyUpdatedAt=ago();if(display)updateEventRegions();
}
function updateEventRegions(){
 const full=$('#history-events');if(full){const filter=state.historyDrive;full.innerHTML=renderHistoryEntries(state.history.filter(e=>filter==='all'||e.drive===filter).sort((a,b)=>new Date(b.time)-new Date(a.time)));}
 const recent=$('#drive-recent-events');if(recent){const id=route().split('/')[1];recent.innerHTML=renderHistoryEntries(state.history.filter(e=>e.drive===id).slice(0,3));}
 for(const id of ['history-updated','drive-events-updated'])if($('#'+id))$('#'+id).textContent='Last updated: '+state.historyUpdatedAt;
}
async function refreshSmtp({display=true}={}){
 const x=await apiRequest('global-config');const s=x.smtp||{};
 state.smtp={server:s.host||'',security:s.security||'starttls',port:String(s.port||587),user:s.username||'',from:s.sender||'',to:s.recipient||''};
 state.lan=!!x.network?.lan;state.lanSecure=x.network?.scheme||'https';state.lanDraftSecure=state.lanSecure;state.lanAddress=x.network?.address||'';
 try{const cert=await apiRequest('lan-info');state.lanFingerprint=cert.fingerprint||'';state.certificateAvailable=!!cert.certificate;state.lanOperation=cert.operation||null;}catch(_){state.lanFingerprint='';state.certificateAvailable=false;}
 if(display)render();
}
async function refreshPrepare({display=true}={}){
 const x=await apiRequest('prepare-disks');state.prepareDisks=x.disks||[];state.prepareOperations=x.operations||[];
 if(!state.prepareDisks.some(v=>v.device===state.selectedPrepare))state.selectedPrepare=null;
 if(display)render();
}
let routeLoading=0,lastLoadedRoute='';
async function loadForRoute(){
 const r=route(),page=r.split('/')[0];routeLoading++;
 try{
   if(page==='drive'){
     const id=r.split('/')[1];if(find(id))await Promise.all([refreshDetail(id,{renderPage:false}),refreshHistory({display:false})]);
   }else if(page==='history')await refreshHistory({display:false});
   else if(page==='email')await refreshSmtp({display:false});
   else if(page==='advanced'){
     await Promise.all([refreshNetwork({display:false}),refreshDetail(state.advancedDrive||configured()[0]?.id,{renderPage:false})]);
   }else if(page==='prepare')await refreshPrepare({display:false});
   else if(page==='images')await refreshDetail(state.selectedImageDrive||configured()[0]?.id,{images:true,renderPage:false});
   else if(page==='apps')await loadApplications();
   else if(page==='integrations'){await loadIntegrationData();return;}
   if(route()===r&&csrfToken)render();
 }catch(e){if(route()===r)toast(errorMessage(e),true);}
 finally{routeLoading--;if(route()===r){lastLoadedRoute=r;focusSettingsSection();}}
}

async function withAction(fn){
 if(apiBusy)throw Error(preferencesSaving?'Mount on recovery is still being saved. Wait for “Saved”, then try this action again. No storage command was sent.':'Another storage operation is still running. Wait for its result, then try again. No additional command was sent.');
 apiBusy=true;
 try{return await fn();}finally{apiBusy=false;}
}
async function openRemoveDrive(d){
 if(!d?.configured)return;
 await withAction(async()=>{
   const review=await apiRequest('remove-drive-plan',{drive:d.id});
   modalAction=()=>removeReviewedDrive(review);
   modal(`<div class="modal-title">${icon('warning')}<h2 id="modal-title">Remove ${esc(review.name)}?</h2></div><p>Storage Watch will stop monitoring this drive and stop managing its automatic recovery and alerts.</p><div class="callout warn"><div><strong>Your files will stay on the drive.</strong><p>Nothing is erased, formatted or unmounted. Existing files, virtual disk image files and current mounts are kept. Other drives keep their own settings.</p></div></div><dl class="info-list"><dt>Drive</dt><dd>${esc(review.name)}</dd><dt>Filesystem UUID</dt><dd class="path">${esc(review.uuid)}</dd><dt>Mount location</dt><dd class="path">${esc(review.mountpoint)}</dd></dl>${review.images||review.containers||review.services?`<p>This also removes this drive’s saved choices from the app: <strong>${review.images} virtual image(s)</strong>, <strong>${review.containers} container(s)</strong> and <strong>${review.services} application service(s)</strong>. Running applications are left running; Storage Watch will no longer restart them after this drive recovers.</p>`:''}<p class="mini">To manage this drive again, choose Add USB drive and configure it again.</p><div class="modal-actions">${B('Cancel','close-modal',{class:'button-quiet'})}${B('Remove from Storage Watch','confirmed-action',{class:'button-danger'})}</div>`,'danger');
 });
}
async function removeReviewedDrive(review){
 await withAction(async()=>{
   const status=$('#modal-root .modal-progress span:last-child');if(status)status.textContent='Stopping this drive’s monitoring and removing its saved registration…';
   fleetEpoch++;let result=null,failure=null,refreshed=false;
   try{result=await apiRequest('remove-drive',{drive:review.profile_id,data:{uuid:review.uuid,revision:review.revision,confirm:true},timeout:60000});}
   catch(error){failure=error;}
   fleetEpoch++;
   if(result?.removed){
     forgetDrive(review.profile_id);state.drives=state.drives.filter(d=>d.id!==review.profile_id);reconcileDriveSelections();
   }
   try{refreshed=await refreshFleet({display:false});}catch(_){/* Keep the verified removal visible even if the next read fails. */}
   if(result?.removed||(refreshed&&!find(review.profile_id)?.configured)){
     closeModal();navigate('overview');render();toast(result?.message||review.name+' is no longer managed by Storage Watch.');return;
   }
   modalAction=null;
   modal(`<div class="modal-title">${icon('warning')}<h2 id="modal-title">Removal not confirmed</h2></div><div class="callout danger" role="alert">${esc(errorMessage(failure||Error('The host did not confirm drive removal.')))}</div><p>The request will not be repeated automatically. Review the current drive state before trying again.</p><div class="modal-actions">${B('Close','close-modal',{class:'button-quiet'})}${B('Review removal','remove-drive-review',{id:review.profile_id,class:'button-neutral'})}</div>`,'danger');
 });
}
function directMessage(message){modal(`<div class="modal-title">${icon('warning')}<h2 id="modal-title">Confirm operation</h2></div><p>${esc(message)}</p><div class="modal-actions">${B('Cancel','close-modal',{class:'button-neutral'})}${B('Continue','confirmed-action',{class:'button-primary'})}</div>`);}
let modalAction=null;
function confirmAction(title,description,fn,{danger=false,independent=false,singleUse=false,singleUseMessage=null}={}){
 modalAction=fn;modalAction.independentOfStorage=independent;modalAction.singleUse=singleUse;modalAction.singleUseMessage=singleUseMessage;
 modal(`<div class="modal-title">${icon(danger?'warning':'check')}<h2 id="modal-title">${esc(title)}</h2></div><div class="callout ${danger?'danger':'warn'}">${icon(danger?'warning':'check')}<div>${esc(description)}</div></div><div class="modal-actions">${B('Cancel','close-modal',{class:'button-quiet'})}${B('Confirm','confirmed-action',{class:danger?'button-danger':'button-primary'})}</div>`,danger?'danger':'');
}
async function runDriveAction(d,kind,approval={}){
 if(!d||!d.configured)throw Error('Choose a configured drive.');
 const status=$('#modal-root .modal-progress span:last-child');
 if(status)status.textContent=kind==='reconnect'?'Checking safety, then reconnecting USB in software. Electrical power removal is not verified…':kind==='sleep'?'Flushing pending writes and requesting HDD standby. Monitoring stays unchanged…':kind==='mount'?'Mounting and verifying the selected drive…':'Stopping dependent apps, then unmounting images and the drive safely…';
 let response=null,requestError=null;
 try{response=await apiRequest('disk-operation',{drive:d.id,data:{uuid:d.uuid,action:kind,...approval}});}
 catch(error){requestError=error;}
 // A transport failure is not permission to retry. Read back the selected drive
 // and history without issuing another storage command.
 const refreshErrors=[];let fleetFailed=false;
 try{await refreshFleet({display:false});}catch(error){refreshErrors.push(error);fleetFailed=true;}
 const reads=await Promise.allSettled([refreshDetail(d.id,{renderPage:false}),refreshHistory({display:false})]);
 reads.forEach(r=>{if(r.status==='rejected')refreshErrors.push(r.reason);});
 const current=find(d.id);
 if(current&&response?.last_operation)current.lastOperation=response.last_operation;
 if(current&&(fleetFailed||reads[0].status==='rejected'))current.stale=true;
 render();
 if(requestError)throw requestError;
 const message=response.message||(response.ok===false?'Disk operation failed.':'Disk operation completed.');
 if(response.ok===false)throw Error(message);
 let detail=message;
 if(response.history_warning)detail+=' '+response.history_warning;
 if(refreshErrors.length)detail+=' Some status or history could not be refreshed. Refresh before another action.';
 toast(detail,!!refreshErrors.length);return {message:detail,error:!!refreshErrors.length};
}
async function showRebindReview(d,uuid){
 const plan=await apiRequest('drive-rebind-plan?uuid='+encodeURIComponent(uuid),{drive:d.id});
 confirmAction('Reconnect previously configured drive?',
   `${d.name}: The same verified USB hardware has a new filesystem UUID (${plan.new_uuid}). Keep its monitoring settings and history, update its mount path to ${plan.mountpoint}, and require fresh USB-port qualification. This does NOT restore files erased by formatting.`,
   async()=>{await withAction(async()=>{
     const applied=await apiRequest('drive-rebind-apply',{drive:d.id,data:{uuid:plan.new_uuid,revision:plan.revision,confirm:true}});
     detailCache.delete(d.id);closeModal();toast(applied.message||'Drive configuration reconnected.');
     await refreshFleet({display:false});navigate('drive/'+d.id);await refreshDetail(d.id);});});
}
async function setMonitoring(d,enabled){
 const result=await apiRequest('monitor',{drive:d.id,data:{enabled}});
 toast(result.message||'Monitoring updated.');await refreshFleet({display:false});await refreshDetail(d.id,{renderPage:true});return {message:result.message||'Monitoring updated.'};
}
async function setRecovery(d,enabled,context=null){
 const plan=await apiRequest(`recovery-plan?enabled=${enabled?'true':'false'}`,{drive:d.id});
 if(plan.ready===false || !plan.token)throw Error(plan.message||'Recovery settings are unavailable for this drive.');
 confirmAction(enabled?'Enable automatic recovery?':'Disable automatic recovery?',plan.message||'Review this drive’s recovery settings before applying the change.',async()=>{
   await withAction(async()=>{
     const response=await apiRequest('recovery-settings',{drive:d.id,data:{uuid:plan.uuid,token:plan.token,enabled,consent:true}});
     closeModal();actionNotice(context,response.message||'Recovery settings saved.');await refreshFleet({display:false});await refreshDetail(d.id,{renderPage:true});
   });
 });
}
async function setNotifications(d,enabled,el){
 el.disabled=true;
 try{
   const detail=detailCache.get(d.id)||{};
   if(!detail.config)await refreshDetail(d.id,{renderPage:false});
   const current=detailCache.get(d.id).config;
   await apiRequest('notification-settings',{drive:d.id,data:{revision:current.revision,enabled}});
   d.notifications=enabled;toast(d.name+': email notifications '+(enabled?'enabled':'disabled')+'.');
   await refreshDetail(d.id,{renderPage:false});
   return {message:d.name+': email notifications '+(enabled?'enabled':'disabled')+'.'};
 }catch(e){el.checked=!enabled;throw e;}finally{el.disabled=false;}
}
async function loadImages(id){const v=await apiRequest('application-images',{drive:id});
 const cur=detailCache.get(id)||{};detailCache.set(id,{...cur,images:v});const d=find(id);if(d)enrichDrive(d,detailCache.get(id));
}
async function discoverImages(id){const data=await apiRequest('image-discover',{drive:id});state.discoveredImages=state.discoveredImages.filter(x=>x.drive!==id).concat((data.images||[]).map(x=>({drive:id,name:x.name,size:x.size,path:x.path})));
 if(data.truncated)toast('Image search was limited. Some files may not be listed.',true);
 render();
}
function imageRecord(d,id){return d?.images.find(x=>x.id===id);}
const imageResults=new Map();
function imageResultMarkup(d){const result=imageResults.get(d.id);return result?`<div class="image-result ${result.error?'error':''}" data-image-result role="status" aria-live="polite">${esc(result.message)}</div>`:'';}
async function runImageMount(d,im,context){
 const desired=!im.mounted,action=desired?'mount':'unmount';let result;
 try{result=await apiRequest('image-action',{drive:d.id,data:{uuid:im.uuid,action}});}
 catch(e){
   // A mount can change before a later monitoring-resume step fails. Read back
   // after every submitted error, without repeating the storage command.
   try{await loadImages(d.id);render();}catch(_){}
   throw e;
 }
 const message=result.message||(desired?'Image mounted.':'Image unmounted.');
 actionNotice(context,message,result.ok===false);
 try{await loadImages(d.id);render();}catch(e){return {message:message+' The latest image list could not be refreshed. Refresh before another action.',error:true};}
 return {message,error:result.ok===false};
}
async function setupImagePlan(d,data,context=null){
 if(!d.mounted||d.stale)throw Error('Mount and verify the selected USB drive before creating or importing a virtual disk image.');
 const plan=await apiRequest('image-plan',{drive:d.id,data});
 confirmAction(plan.mode==='adopt'?'Adopt existing mounted image?':data.mode==='create'?'Create virtual disk image?':'Register existing virtual disk image?',plan.message||'Confirm the virtual disk operation.',async(confirmContext)=>{
   return await withAction(async()=>{
     actionProgress(context,data.mode==='create'?'Creating and mounting image…':'Registering image…');
     let result;
     try{result=await apiRequest('image-apply',{drive:d.id,data:{token:plan.token,confirm:true}});}
     catch(e){
       if(e.uncertain){
         const notice={message:operationError(e),error:true};imageResults.set(d.id,notice);actionNotice(context,notice.message,true);
         try{await loadImages(d.id);}catch(_){}
         state.imageTab='configured';closeModal();render();
       }else{
         // image-apply consumes its review token even for a definite refusal.
         // Keep the explanation in this dialog, but require a fresh review.
         if(confirmContext)confirmContext.uncertain=true;
         modalAction=null;actionNotice(context,operationError(e),true);
       }
       throw e;
     }
     const notice={message:result.message||'Virtual disk updated.',error:result.ok===false};
     // A partial create consumed the reviewed request too. Never leave Confirm available
     // for a file that was already created or registered.
     closeModal();state.imageTab='configured';imageResults.set(d.id,notice);actionNotice(context,notice.message,notice.error);
     try{await loadImages(d.id);}catch(e){notice.message+=' The current image list could not be refreshed. Refresh before another action.';notice.error=true;}
     render();return notice;
   });
 });
 return {message:'Review the image details, then confirm.'};
}
function createImageForm(d){return `<h3>Create a virtual disk image</h3><p class="small">Choose a name and size. The .img file and accessible folder are created on the host's selected USB drive. Monitoring may stay enabled; if active, it is briefly paused and resumed automatically during creation.</p><form data-form="image-create"><div class="form-grid"><div class="wide">${field('Image name','new-image-name','','text','Letters, numbers, hyphens or underscores.','required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,31}" maxlength="32" placeholder="e.g. project-backups"')}</div>${field('Capacity (GB)','new-image-capacity','2','number','Available capacity is verified on the host before creation.','required min="0.125" step="0.125" max="65536"')}<div class="field"><label for="new-image-access">Folder access</label><select id="new-image-access"><option value="user">My user account</option><option value="applications">Applications / Docker</option></select><small>My user account is recommended for file manager access.</small></div></div><div class="actions">${submitControl('Review image creation','image-create',d.id,!d.mounted||d.stale)}</div></form>`;}
function importImageForm(d){const list=state.discoveredImages.filter(i=>i.drive===d.id&&!d.images.some(im=>im.path===i.path));return `<h3>Add an existing virtual disk image</h3><p class="small">Scan this drive for .img files. A verified mounted ext4 image can keep its existing fstab mount and permissions; review the detected file, UUID and mountpoint before adopting it.</p><div class="actions">${B('Scan USB drive','rescan-images',{class:'button-utility',icon:'refresh',disabled:!d.mounted||d.stale})}</div>${list.map(x=>`<label class="selection-row"><span><strong class="title">${esc(x.name)} · ${readableSize(x.size)}</strong><span class="desc path">${esc(x.path)}</span></span><input type="radio" name="existing-image" data-change="select-discovered" value="${attr(x.path)}" ${state.selectedDiscovered===x.path?'checked':''}></label>`).join('')||'<div class="empty">No unregistered files listed. Select Scan USB drive to search.</div>'}<div class="actions">${B('Add selected image','import-discovered',{class:'button-primary',disabled:!state.selectedDiscovered||!d.mounted||d.stale})}</div><details class="detail"><summary>Advanced — Enter an image path on the host</summary>${field('Existing image file','existing-image-path','','text','Absolute path on the selected USB drive.','placeholder="/mnt/.../backup.img"')}${field('Image name','existing-image-name','','text','Name for this image.','placeholder="backup"')}${B('Review existing image','import-by-path',{class:'button-primary',disabled:!d.mounted||d.stale})}</details><p class="mini">Remote upload and network-share copying require a separately verified file-transfer backend and are not enabled in this build.</p>`;}
/* Container-first restart settings. Monitoring state never gates this editor. */
const applicationViews=new Map();
const dockerPage={containers:[],drives:[],revision:null,loaded:false,loading:false,reading:false,saving:null,sequence:0,runtimeSequence:0,error:'',observedAt:null,refreshMessage:''};
const dockerCollapseKey='usw-docker-collapsed-v1';
const imageExpansionKey='usw-app-image-expansion-v1';
function savedImageExpansion(id){try{return JSON.parse(localStorage.getItem(imageExpansionKey)||'{}')[id]||{};}catch(_){return {};}}
function dockerCollapsed(id){try{return JSON.parse(localStorage.getItem(dockerCollapseKey)||'{}')[id]===true;}catch(_){return false;}}
function rememberDockerCollapse(id,value){try{const saved=JSON.parse(localStorage.getItem(dockerCollapseKey)||'{}');saved[id]=value;localStorage.setItem(dockerCollapseKey,JSON.stringify(saved));}catch(_){/* This browser may restrict local storage. */}}
function dockerView(id){
 if(!applicationViews.has(id))applicationViews.set(id,{imageExpanded:savedImageExpansion(id),saved:null,draft:null,server:null,baseRevision:null,collapsed:dockerCollapsed(id),saving:false,sent:null,conflict:false,unconfirmed:false,message:'',messageError:false,bodyKey:null,controlBusy:false,controlAction:'',controlMessage:'',controlError:false,controlUncertain:false,controlToken:null});
 return applicationViews.get(id);
}
function resetDockerPage(){applicationViews.clear();dockerPage.entryMessage='';dockerPage.inventoryOK=false;dockerPage.savedEntryIDs=[];Object.assign(dockerPage,{containers:[],drives:[],revision:null,loaded:false,loading:false,reading:false,saving:null,error:'',observedAt:null,refreshMessage:''});dockerPage.sequence++;dockerPage.runtimeSequence++;}
function dockerChoices(choices){return (choices||[]).map(v=>({id:String(v.id),enabled:v.enabled===true,images:v.enabled===true?[...new Set(v.images||[])].sort():[]})).sort((a,b)=>a.id.localeCompare(b.id));}
function copyDockerChoices(choices){return (choices||[]).map(v=>({...v,images:[...(v.images||[])]}));}
function dockerDirty(v){return !!v.saved&&!!v.draft&&!sameValues(dockerChoices(v.saved),dockerChoices(v.draft));}
function dockerSetting(settings,row){return settings.find(x=>x.id===row.id)||(row.id.startsWith('saved:')?settings.find(x=>x.name===row.name):null);}
function dockerCurrentChoices(settings,row){
 const saved=dockerSetting(settings,row)?.drives||[];
 return dockerPage.drives.map(d=>{const choice=saved.find(v=>v.id===d.id);return {id:d.id,enabled:choice?.enabled===true,images:[...(choice?.images||[])]};});
}
function applyDockerOverview(result,{runtimeSequence=dockerPage.runtimeSequence}={}){
 if(!Array.isArray(result.containers)||!Array.isArray(result.drives)||!Array.isArray(result.settings)||typeof result.revision!=='string')throw Error('The host returned incomplete Docker settings. Previous choices are retained.');
 // A settings read begun before a manual command may update settings, but
 // must not restore an older runtime state over that command's result.
 if(runtimeSequence===dockerPage.runtimeSequence)dockerPage.containers=result.containers;
 dockerPage.settingsStale=false;dockerPage.inventoryOK=result.inventory_ok===true;dockerPage.savedEntryIDs=result.applications?.saved_ids||[];dockerPage.configured=result.applications?.configured||{};dockerPage.appRevision=result.applications?.revision;dockerPage.boot=result.boot||{settings:[],results:{},revision:null};dockerPage.drives=result.drives;dockerPage.revision=result.revision;dockerPage.observedAt=result.observed_at||null;dockerPage.error=result.error||'';dockerPage.loaded=true;
 for(const row of dockerPage.containers){
   if(!dockerPage.inventoryOK||row.control_block||appBlocked(dockerView(row.id).entryPlan?.target?.id))dockerView(row.id).entryPlan=null;
   if(row.control_block)dockerView(row.id).appPlan=null;
   const v=dockerView(row.id),actual=dockerCurrentChoices(result.settings,row),dirty=dockerDirty(v);
   const bootActual=dockerPage.boot.settings.find(x=>x.id===row.id)||{id:row.id,name:row.name,enabled:false,drives:[]};
   if(!v.bootDraft||sameValues(v.bootDraft,v.bootSaved)){v.bootDraft=structuredClone(bootActual);v.bootRevision=dockerPage.boot.revision;}
   v.bootSaved=structuredClone(bootActual);
   const appActual=result.applications?.settings?.find(x=>x.id===row.id);
   if(appActual){
     const clean=!v.appDraft||sameValues(v.appDraft,v.appSaved), unchanged=sameValues(appActual,v.appSaved);
     v.appServer=structuredClone(appActual);v.appHeaderUnknown=false;
     if(clean||sameValues(appActual,v.appDraft)){v.appDraft=structuredClone(appActual);v.appSaved=structuredClone(appActual);v.appConflict=false;}
     else if(!unchanged){v.appConflict=true;v.appPlan=null;}
     if(clean||unchanged||!v.appConflict)v.appRevision=result.applications.revision;
   }
   v.appReadError=result.applications?.error||(!appActual?'App settings are unavailable. Refresh before editing.':'');
   v.server=copyDockerChoices(actual);
   const ownSave=v.saving&&v.sent&&sameValues(dockerChoices(actual),dockerChoices(v.sent));
   const matchingDraft=!!v.draft&&sameValues(dockerChoices(actual),dockerChoices(v.draft));
   if(!v.saved||!dirty||ownSave||matchingDraft){
     v.saved=copyDockerChoices(actual);v.baseRevision=result.revision;v.conflict=false;
     // Even a newer edit back to the old saved value must survive this save response.
     if(!dirty&&!ownSave)v.draft=copyDockerChoices(actual);
   }else if(sameValues(dockerChoices(v.saved),dockerChoices(actual))){
     // An unrelated card/settings change can advance the revision without overwriting this draft.
     v.baseRevision=result.revision;v.conflict=false;
   }else{v.conflict=true;}
   if(!v.saving&&v.unconfirmed&&matchingDraft){v.message='Saved. Current settings confirmed.';v.messageError=false;}
   if(!v.saving)v.unconfirmed=false;
 }
}
function applicationState(row){
 if(!row)return chip('Unknown','muted');
 const status=row.state||(row.dead?'dead':row.paused?'paused':row.restarting?'restarting':row.running===true?'running':row.running===false?'stopped':'unknown');
 const label=status==='running'&&row.health==='unhealthy'?'Unhealthy':status==='running'&&row.health==='starting'?'Starting':status.charAt(0).toUpperCase()+status.slice(1);
 return chip(label,label==='Running'||label==='Healthy'?'good':label==='Unknown'||label==='Stopped'||label==='Missing'?'muted':'warn');
}
function dockerControlId(container,drive,suffix){return 'docker-'+encodeURIComponent(container+'-'+drive+'-'+suffix).replaceAll('%','_');}
function dockerDriveKind(d){return d.kind||((d.media_kind&&knownKind(d.media_kind))||find(d.id)?.kind)||'unknown';}
function dockerDriveDescription(d){const kind=dockerDriveKind(d);return [readableSize(d.size),({hdd:'Mechanical HDD',ssd:'Solid-state drive',flash:'USB flash drive'})[kind]].filter(Boolean).join(' · ');}
function appBlocked(id){return dockerPage.containers.find(row=>row.id===id)?.control_block||'';}
function savedAppState(row,kind){
 const v=dockerView(row.id),known=!dockerPage.settingsStale&&!v.appReadError&&!v.appHeaderUnknown;
 const value=known?v.appServer?.[kind]?.enabled:undefined;
 if(typeof value!=='boolean')return 'unknown';
 if(dockerPage.configured?.[row.id]?.[kind]===false)return 'unconfigured';
 return value?'enabled':'off';
}
function appSettingIndicators(row){
 return `<span class="app-saved-indicators" id="${dockerControlId(row.id,'','saved-indicators')}" aria-label="Saved app settings">${['boot','recovery'].map(kind=>{const status=savedAppState(row,kind),label=kind==='boot'?'Startup':'Recovery';return `<span class="app-saved-indicator ${status}" data-saved-setting="${kind}">${label} ${status==='unconfigured'?'not configured':status}</span>`;}).join('')}</span>`;
}
function appRecoveryNotice(row){return `<p class="app-recovery-notice" role="status" aria-live="polite" ${row.control_block?'':'hidden'}>${esc(row.control_block||'')}</p>`;}
function syncAppControlLocks(){
 for(const card of $$('.docker-container,.unavailable-entry')){
   const id=card.dataset.containerId||card.dataset.unavailableEntry,reason=appBlocked(id),locked=!!reason;
   card.toggleAttribute('data-app-locked',locked);
   const fields=$('.app-control-fields',card);if(fields)fields.disabled=locked;
   const header=$('.docker-container-header',card);if(header)header.disabled=locked;
   const notice=$('.app-recovery-notice',card);if(notice){notice.textContent=reason;notice.hidden=!locked;}
   for(const control of $$('summary,a[href]',card)){
     if(locked){control.setAttribute('aria-disabled','true');control.tabIndex=-1;}
     else{control.removeAttribute('aria-disabled');control.removeAttribute('tabindex');}
   }
 }
 // A confirmation opened before an outage stays cancellable, but cannot submit.
 const dialog=$('#modal-root .modal[data-app-id]');
 if(dialog&&!modalPending){
   const reason=appBlocked(dialog.dataset.appId),confirm=$('[data-action="confirmed-action"]',dialog);
   if(confirm)confirm.disabled=!!reason;
   let notice=$('.app-recovery-notice',dialog);
   if(!notice){notice=document.createElement('p');notice.className='app-recovery-notice';notice.setAttribute('role','status');dialog.append(notice);}
   notice.textContent=reason;notice.hidden=!reason;
 }
 if(activeTouchSelect&&(!activeTouchSelect.button.isConnected||activeTouchSelect.button.matches(':disabled')))closeTouchSelect();
}
// Fieldsets cover form controls; native details/links also need event admission.
for(const type of ['click','keydown','change','input','submit'])document.addEventListener(type,event=>{
 const card=event.target.closest?.('.docker-container,.unavailable-entry');
 if(!card||!appBlocked(card.dataset.containerId||card.dataset.unavailableEntry))return;
 if(type==='click'&&!event.target.closest('button,input,select,textarea,label,a,summary'))return;
 if(type==='keydown'&&!['Enter',' ','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 event.preventDefault();event.stopImmediatePropagation();
},true);

function dockerControlAllowed(row,action){
 if(!row||row.control_block||row.discovered===false||!/^[a-f0-9]{64}$/.test(row.id))return false;
 return action==='start'?row.state==='stopped':['stop','restart'].includes(action)&&row.state==='running';
}
function dockerControls(row,v){
 const available=row.discovered!==false&&/^[a-f0-9]{64}$/.test(row.id),running=row.state==='running',stopped=row.state==='stopped';
 const commands=stopped?['start','restart']:running?['stop','restart']:['start','stop','restart'];
 const labels={start:'Start app',stop:'Stop app',restart:'Restart app'};
 const unavailable=row.control_block||(!available?'This container is not currently detected. Refresh containers to check again.':!running&&!stopped?'Manual controls are unavailable while the container is '+(row.state||'unknown')+'. Check it in Docker, then refresh.':'');
 return `<section class="docker-manual-controls" aria-label="Manual controls for ${attr(row.name)}"><h3>Manual controls</h3><div class="actions docker-control-actions">${commands.map(action=>B(labels[action],'docker-'+action,{id:row.id,class:action==='start'?'button-start':action==='stop'?'button-warning':'button-primary',disabled:v.controlBusy||!dockerControlAllowed(row,action)})).join('')}</div><p class="inline-status docker-control-status ${v.controlError?'error':''}" data-docker-control-status role="status" aria-live="polite" aria-atomic="true" aria-busy="${v.controlBusy}">${esc(row.control_block?'':v.controlMessage||unavailable)}</p>${!row.control_block&&unavailable&&v.controlMessage?`<p class="mini">${esc(unavailable)}</p>`:''}</section>`;
}
function invalidateDockerReads(){dockerPage.sequence++;dockerPage.runtimeSequence++;dockerPage.reading=false;dockerPage.loading=false;}
function setDockerRuntime(row,observed){
 const current=dockerPage.containers.find(item=>item.id===row.id&&item.name===row.name);
 if(!current)return false;
 if(!observed||observed.id!==row.id||observed.name!==row.name||!['running','stopped','paused','dead','restarting','missing','unknown'].includes(observed.state))return false;
 if('control_block' in observed)current.control_block=observed.control_block;
 Object.assign(current,{state:observed.state,health:observed.health||null,discovered:observed.discovered!==false});return true;
}
async function runDockerControl(row,action,context){
 const v=applicationViews.get(row.id);
 if(!v||v.controlBusy)throw Error('A command for this container is already running. Wait for its result.');
 if(!dockerControlAllowed(dockerPage.containers.find(item=>item.id===row.id&&item.name===row.name),action)){
   const notice={message:appBlocked(row.id)||'The container state changed. Refresh containers before choosing an action. No command was sent.',error:true};
   v.controlMessage=notice.message;v.controlError=true;v.controlUncertain=false;actionNotice(context,notice.message,true);refreshDockerDOM();return notice;
 }
 const session=csrfToken,token={},labels={start:'Starting',stop:'Stopping',restart:'Restarting'};
 const current=()=>csrfToken===session&&applicationViews.get(row.id)===v&&v.controlToken===token;
 v.controlToken=token;v.controlBusy=true;v.controlAction=action;v.controlMessage=labels[action]+' '+row.name+'…';v.controlError=false;v.controlUncertain=false;
 for(const command of ['start','stop','restart']){const key=feedbackKey('docker-'+command,row.id);if(key!==context?.key)actionFeedback.delete(key);}
 actionProgress(context,v.controlMessage);invalidateDockerReads();refreshDockerDOM();
 let result=null,failure=null,notice=null;
 try{
   try{result=await apiRequest('docker-container-action',{data:{id:row.id,name:row.name,action,confirm:true}});}catch(e){failure=e;}
   if(!current())return;
   invalidateDockerReads();
   if(!failure&&(!result||typeof result.ok!=='boolean'))failure=Object.assign(Error('The host returned an incomplete container result.'),{uncertain:true});
   const verified=result?.container&&setDockerRuntime(row,result.container);
   notice=failure?{message:operationError(failure),error:true,uncertain:!!failure.uncertain}:{message:result.message||'The host returned no container result.',error:result.ok!==true,uncertain:result.uncertain===true};
   if(result?.ok===true&&!verified){notice={message:'The host accepted the command, but the current container state could not be verified. Refresh containers before another action.',error:true,uncertain:true};}
   if(!verified||failure||result?.ok===false){
     // Only read current state after a refusal or lost result. Never replay a POST.
     try{
       const snapshot=await apiRequest('docker-overview');if(!current())return;
       if(!Array.isArray(snapshot.containers))throw Error('Docker returned an incomplete container list.');
       const observed=snapshot.containers.find(item=>item.id===row.id&&item.name===row.name);
       if(observed)setDockerRuntime(row,observed);
       else setDockerRuntime(row,{...row,state:snapshot.error?'unknown':'missing',health:null,discovered:false});
     }catch(e){
       if(!current())return;
       setDockerRuntime(row,{...row,state:'unknown',health:null});
       notice.message+=' The latest container state could not be refreshed.';
     }
   }
   if(!current())return;
   v.controlMessage=notice.message;v.controlError=notice.error;v.controlUncertain=notice.uncertain;
   actionNotice(context,notice.message,notice.error);return notice;
 }finally{
   if(current()){v.controlBusy=false;v.controlAction='';v.controlToken=null;invalidateDockerReads();refreshDockerDOM();}
 }
}
function reviewDockerControl(id,action,context){
 const row=dockerPage.containers.find(item=>item.id===id);if(!row)throw Error('This container is no longer listed. Refresh containers.');
 // Capture the exact full ID and name now; a later poll cannot retarget the confirmation.
 const target={id:row.id,name:row.name};
 if(action==='start')return runDockerControl(target,action,context);
 const title=action==='stop'?'Stop '+row.name+'?':'Restart '+row.name+'?';
 const description=action==='stop'?'Stop this app now. It will be unavailable until started again. Automatic recovery choices are unchanged.':'Restart this app now. Active connections and uploads may be interrupted. Automatic recovery choices are unchanged.';
 confirmAction(title,description,async()=>{
   const dialog=$('#modal-root .modal');
   try{return await runDockerControl(target,action,context);}
   finally{if(dialog?.isConnected)closeModal();}
 },{danger:action==='stop',independent:true});
 const dialog=$('#modal-root .modal');if(dialog)dialog.dataset.appId=row.id;
 syncAppControlLocks();
 return {message:'Review the '+action+' request, then confirm.'};
}

function policyLabel(policy){return policy?policy.Name+(policy.Name==='on-failure'&&policy.MaximumRetryCount?':'+policy.MaximumRetryCount:''):'Unavailable';}
function setupStorageSummary(choices){
 return (choices||[]).map(choice=>{const drive=dockerPage.drives.find(d=>d.id===choice.id);return (drive?.name||choice.id)+(choice.images?.length?' + '+choice.images.map(id=>drive?.images?.find(im=>im.uuid===id)?.name||id).join(', '):' (ordinary folders; no image required)');}).join('; ')||'None selected';
}
function rememberImageExpansion(el){
 const v=dockerView(el.dataset.container);v.imageExpanded??={};
 if(v.imageExpanded[el.dataset.imageSection]===el.open)return;
 v.imageExpanded[el.dataset.imageSection]=el.open;
 try{const saved=JSON.parse(localStorage.getItem(imageExpansionKey)||'{}');saved[el.dataset.container]=v.imageExpanded;localStorage.setItem(imageExpansionKey,JSON.stringify(saved));}catch(_){/* Session memory still preserves expansion if browser storage is restricted. */}
}
document.addEventListener('toggle',event=>{if(event.target.isConnected&&event.target.matches('[data-image-section]'))rememberImageExpansion(event.target);},true);
function rememberAppExpansion(){
 for(const el of $$('[data-image-section]'))rememberImageExpansion(el);
 for(const el of $$('[data-unavailable-entry]'))dockerView(el.dataset.unavailableEntry).entryOpen=el.open;
}
function appDirty(v){return !!v.appDraft&&!sameValues(v.appDraft,v.appSaved);}
function appDriveChoices(row,v,kind){
 const settings=v.appDraft?.[kind]||{enabled:false,drives:[]},disabled=!settings.enabled||v.appBusy||!!row.control_block;
 const drives=[...dockerPage.drives];
 for(const choice of settings.drives)if(!drives.some(d=>d.id===choice.id))drives.push({id:choice.id,name:'Unavailable drive · '+choice.id,images:[],missing:true});
 return drives.map(d=>{
   const choice=settings.drives.find(x=>x.id===d.id),id=dockerControlId(row.id,d.id,kind),images=[...(d.images||[])],sectionKey=kind+':'+d.id;
   for(const uuid of choice?.images||[])if(!images.some(im=>im.uuid===uuid))images.push({uuid,name:'Unavailable image · '+uuid,missing:true});
   const selectedNames=(choice?.images||[]).map(uuid=>images.find(im=>im.uuid===uuid)?.name||uuid);
   const warnings=[];
   if(choice&&settings.enabled){
     if(d.missing)warnings.push('Drive no longer configured. Review this selection.');
     if(kind==='recovery'){
       if(d.monitoring===false)warnings.push('Monitoring is off. Start monitoring for this drive in Overview to protect this app.');
       else if(d.monitoring!==true)warnings.push('Monitoring status is unavailable. Check this drive in Overview.');
       else if(d.monitor_enabled===false)warnings.push('Monitoring will not start with the computer. Enable it for this drive in Overview.');
       if(d.automatic_mount===false)warnings.push('Automatic mounting is off. Enable automatic mount recovery for this drive in Advanced.');
     }
   }
   return `<div class="app-drive ${choice?'selected':''}"><label class="app-drive-choice" for="${id}"><input id="${id}" type="checkbox" data-change="app-drive" data-kind="${kind}" data-container="${attr(row.id)}" data-drive="${attr(d.id)}" ${choice?'checked':''} ${disabled?'disabled':''}><span><strong>${esc(d.name)}</strong>${d.mountpoint?`<small class="path">${esc(d.mountpoint)}</small>`:''}${dockerDriveDescription(d)?`<small>${esc(dockerDriveDescription(d))}</small>`:''}</span></label>${choice&&images.length?`<details class="app-images" data-container="${attr(row.id)}" data-image-section="${attr(sectionKey)}" ${v.imageExpanded?.[sectionKey]?'open':''}><summary>Virtual images · ${selectedNames.length} selected${selectedNames.length?': '+esc(selectedNames.join(', ')):''}</summary><div class="app-image-options">${images.map(im=>{const imageID=dockerControlId(row.id,d.id,kind+im.uuid);return `<label class="app-image-choice" for="${imageID}"><input id="${imageID}" type="checkbox" data-change="app-image" data-kind="${kind}" data-container="${attr(row.id)}" data-drive="${attr(d.id)}" value="${attr(im.uuid)}" ${choice.images.includes(im.uuid)?'checked':''} ${disabled?'disabled':''}><span>${esc(im.name)}${im.mountpoint?`<small class="path">${esc(im.mountpoint)}</small>`:''}</span></label>`;}).join('')}<p class="mini">Select only the virtual images this app needs. Otherwise, leave them unselected.</p></div></details>`:''}${warnings.map(t=>`<p class="app-drive-warning" role="status">${esc(t)}</p>`).join('')}</div>`;
 }).join('')||'<p class="mini">Add a drive in Overview to select it here.</p>';
}
function appPanel(row,v,kind){
 const boot=kind==='boot',settings=v.appDraft?.[kind]||{enabled:false},id=dockerControlId(row.id,'',kind+'-enabled');
 return `<section class="app-settings-panel ${settings.enabled?'enabled':''}" data-app-panel="${kind}"><h3>${boot?'Computer startup':'Drive failure &amp; recovery'}</h3><p class="app-configuration-status">${({enabled:'Saved and enabled',off:'Saved and off',unconfigured:'Not configured',unknown:'Saved settings unavailable'})[savedAppState(row,kind)]}</p><label class="app-option" for="${id}"><input id="${id}" class="toggle" type="checkbox" role="switch" data-change="app-enabled" data-kind="${kind}" data-container="${attr(row.id)}" ${settings.enabled?'checked':''} ${row.control_block||v.appBusy||!v.appDraft||v.appReadError?'disabled':''}><strong>${boot?'Start with the computer':'Restart after a drive problem'}</strong></label><p class="small app-panel-description">${boot?'Start this app after the computer turns on, once the selected drives are ready.':'Stop this app if a selected drive fails. Start it again when the drive has recovered.'}</p><h4>${boot?'Wait for these drives':'Drives this app depends on'}</h4><div class="app-drive-list" ${settings.enabled?'':'data-disabled="true"'}>${appDriveChoices(row,v,kind)}</div>${!settings.enabled?'<p class="mini app-off-note">Off. Selections are kept for later.</p>':''}</section>`;
}
function appAdvanced(row,v){
 const setup=row.setup||{},plan=v.appPlan?.policy,receipt=dockerPage.boot?.results?.[row.id];
 return `<details class="detail app-advanced" ${v.advanced?'open':''}><summary>Advanced details</summary><p>Docker restart policy: <strong>${esc(policyLabel(setup.policy))}</strong><br>Deployment manager: <strong>${esc(setup.manager||'Unavailable')}</strong></p>${(setup.conflicts||[]).map(t=>`<p class="setup-conflict">${esc(t)}</p>`).join('')}<p>Container ID: <code>${esc(row.id)}</code></p>${setup.compose_source?`<p>Compose source reported by Docker: <code>${esc(setup.compose_source)}</code><br>Service: <code>${esc(setup.compose_service)}</code>. ${setup.source_verified?'Source was verified; changes are checked again on save.':'Source requires validation during review.'}</p>`:''}${plan?.compose?`<p>Validated Compose files, in override order: ${plan.compose.files.map(f=>`<code>${esc(f)}</code>`).join(' → ')}</p>`:''}${setup.original_policy?`<p>Original policy saved for restoration: <strong>${esc(policyLabel(setup.original_policy))}</strong>. Disable Storage Watch startup and recovery before restoring it through Docker. Keep the Compose source consistent; private source backups are retained with the setup record.</p>`:''}<p>This manages computer startup and drive recovery. It is not a general application-crash restart watchdog.</p><p>Computer startup respects later manual stops. Enabled drive recovery may start the app again after a selected drive recovers.</p><p>Virtual images are optional. Ordinary folders work once the correct physical filesystem is mounted; an empty mountpoint directory does not count as ready storage.</p>${dockerPage.boot?.results?.[row.id]?.message?`<p>Startup status: ${esc(dockerPage.boot.results[row.id].message)}</p>`:''}${receipt?.notification?`<p>Startup email: ${esc(receipt.notification)}${receipt.notification_error?' · '+esc(receipt.notification_error):receipt.notification==='failed'?' · No error reason was retained for this earlier attempt.':''}</p>`:''}${(row.warnings||[]).map(t=>`<p>${esc(t)}</p>`).join('')}</details>`;
}
function permissionAccess(value){
 const group=value.group||{},names=value.affected_users||[];
 return [names.length?'Group '+(group.name||group.id)+': '+names.join(', '):'',value.affects_others?'All other local users':'',group.known===false?'Group membership could not be verified':''].filter(Boolean).join('; ')||'No additional group members were identified.';
}
function permissionDetails(value){
 const owner=value.owner||{},group=value.group||{};
 return `<details class="permission-details"><summary>Technical details</summary><dl><dt>Type</dt><dd>${esc(value.type)}</dd><dt>Owner</dt><dd>${esc(owner.name??'Unknown')} (UID ${esc(owner.uid??'unknown')})</dd><dt>Group</dt><dd>${esc(group.name??'Unknown')} (GID ${esc(group.id??'unknown')})</dd><dt>Permissions</dt><dd>${esc(value.mode??'Unknown')}</dd><dt>Group members</dt><dd>${group.known?(group.members||[]).map(m=>esc(m.name)+' (UID '+esc(m.uid)+')').join(', ')||'None': 'Membership unavailable'}</dd><dt>Access ACL</dt><dd>${esc(value.acl||'unknown')}</dd>${value.hard_links!=null?`<dt>Hard links</dt><dd>${esc(value.hard_links)}</dd>`:''}</dl></details>`;
}
function accessPathMarkup(value){
 return `<section class="permission-issue"><h4>${esc(({compose_file:'Compose file',environment_file:'Environment file',project_directory:'Project directory',parent_directory:'Parent directory'})[value.role]||'Configuration path')}</h4><p><code>${esc(value.path)}</code></p><p>Permissions: <strong>${esc(value.mode??'Unknown')}${value.proposed_mode?' → '+esc(value.proposed_mode):''}</strong></p><p>${value.problem==='shared_write'?'Write permission: '+esc(permissionAccess(value)):'This path’s ownership, type or file identity needs review.'}</p>${value.type==='directory'?'<p>Removing directory write access prevents the affected accounts from creating, deleting or renaming entries directly here. Read/traverse access and child-file permissions stay unchanged.</p>':''}${(value.child_data||[]).map(d=>`<p>Known data subfolder: <code>${esc(d.path)}</code> (${esc(d.app)}). Its own permissions will not change.</p>`).join('')}${value.limitation?`<p>${esc(value.limitation)}</p>`:''}${permissionDetails(value)}</section>`;
}
function permissionIssues(row,v,p){
 const values=p.diagnostics||[];
 return values.map(accessPathMarkup).join('')+(values.some(v=>v.adjustable)?B('Review access changes','app-permission',{id:row.id,class:'button-primary',disabled:v.appBusy||!!row.control_block}):'');
}

async function reviewAppPermission(id){
 const row=dockerPage.containers.find(r=>r.id===id),v=dockerView(id),p=v.appPlan?.policy;
 if(!row||!p||v.appBusy||appBlocked(id))return;
 const session=csrfToken;v.appBusy=true;v.appError=false;invalidateDockerReads();refreshDockerDOM();
 let review;
 try{review=await apiRequest('docker-permission-plan',{data:{id,name:row.name,token:p.token}});}
 catch(e){if(csrfToken===session){v.appMessage=operationError(e);v.appError=true;}return {message:operationError(e),error:true};}
 finally{if(csrfToken===session){v.appBusy=false;refreshDockerDOM();}}
 if(csrfToken!==session)return;
 confirmAction('Review access changes',review.message,async()=>{
   if(appBlocked(id))throw Error(appBlocked(id));
   v.appBusy=true;v.appMessage='Checking and applying the reviewed access changes…';refreshDockerDOM();
   let result;
   try{
     result=await apiRequest('docker-permission-apply',{data:{id,name:row.name,token:review.token,confirm:true}});
     if(csrfToken!==session)return;
     v.appPlan=null;v.appMessage=result.message;v.appError=!result.ok;closeModal();
     if(result.ok)toast('Access changes updated and verified.');
   }catch(e){if(csrfToken===session){v.appPlan=null;v.appMessage=operationError(e)+' No request was repeated. Review again to check current permissions.';v.appError=true;}throw e;}
   finally{if(csrfToken===session){v.appBusy=false;refreshDockerDOM();}}
   // Normal app review runs again; permission repair never saves the draft.
   if(result?.ok&&csrfToken===session){await reviewAppSettings(id);v.appMessage=result.message;refreshDockerDOM();}
 },{independent:true,singleUse:true,singleUseMessage:'This permission review has been used. Close this dialog and review the app settings again to inspect current permissions. No request will be repeated.'});
 const dialog=$('#modal-root .modal');if(dialog){dialog.dataset.appId=id;
   $('.modal-actions',dialog).insertAdjacentHTML('beforebegin',`<div class="permission-review">${review.paths.map(accessPathMarkup).join('')}${review.remaining?.length?'<h4>Not changed by this plan</h4>'+review.remaining.map(accessPathMarkup).join(''):''}</div>`);
 }
 syncAppControlLocks();return {message:'Permission review prepared. No change applied.'};
}
function appReview(row,v){
 const plan=v.appPlan;if(!plan)return '';
 const p=plan.policy;
 return `<section class="app-review setup-review" aria-label="Review changes"><h3>Review changes for ${esc(row.name)}</h3>${['boot','recovery'].map(kind=>{const value=plan.settings[kind],label=kind==='boot'?'Computer startup':'Drive failure &amp; recovery';return `<p><strong>${label}: ${value.enabled?'On':'Off'}</strong>${plan.changed.includes(kind)?'':' · unchanged'}<br>${value.enabled?esc(setupStorageSummary(value.drives)):'Saved drive and image selections will be retained.'}</p>`;}).join('')}${plan.changed.includes('boot')&&plan.settings.boot.enabled?'<p class="small">Startup can run during this computer session once storage is ready, unless it already completed or was cancelled this boot.</p>':''}${p?`<p>${p.live_change?'Let Storage Watch control automatic startup by changing Docker’s restart policy from '+esc(policyLabel(p.policy))+' to <strong>no</strong>. This does not restart or recreate the app. The previous policy will be saved for restoration.':'Docker’s restart policy is already <strong>no</strong>; no live policy change is needed.'}</p>${p.compose?`<p>Compose service: <strong>${esc(p.compose.service)}</strong></p>${p.compose.changes?`<p>Only the restart field in <code>${esc(p.compose.file)}</code> will change:</p><pre class="setup-diff">${esc('- restart: '+(p.compose.source_before??'(absent)')+'\n+ restart: '+p.compose.source_after)}</pre><p class="small">The original will be backed up privately. Effective configuration, including overrides, will be validated before and after saving.</p>`:'<p>Effective Compose policy is already no; its source will be verified again on save.</p>'}`:''}${permissionIssues(row,v,p)}${(p.instructions||[]).filter(t=>!t.includes('docker ')).map(t=>`<p class="setup-instruction">${esc(t)}</p>`).join('')}${[...(p.technical||[]),...(p.instructions||[]).filter(t=>t.includes('docker '))].length?`<details class="permission-details"><summary>Technical setup details</summary>${[...(p.technical||[]),...(p.instructions||[]).filter(t=>t.includes('docker '))].map(t=>`<p>${esc(t)}</p>`).join('')}</details>`:''}`:''}<p class="mini">Monitoring and global image-recovery settings are unchanged. These settings do not provide general application-crash recovery.</p>${plan.allowed?B('Save settings','app-save',{id:row.id,class:'button-primary',disabled:v.appBusy||!!row.control_block}):'<p class="inline-status error">Settings have not been saved. Resolve the setup issue shown above, then review again.</p>'}${B('Back to editing','app-cancel',{id:row.id,class:'button-neutral',disabled:v.appBusy})}</section>`;
}
function dockerCardBody(row,v){
 return `<fieldset class="app-control-fields" ${row.control_block?'disabled':''} aria-label="App controls">${dockerControls(row,v)}<div class="app-settings-grid">${appPanel(row,v,'boot')}${appPanel(row,v,'recovery')}</div>${appAdvanced(row,v)}<div class="docker-card-footer">${v.appConflict?`<p class="inline-status error">Settings changed elsewhere. Your draft is retained. ${B('Reload saved settings','docker-reload',{id:row.id,class:'button-neutral'})}</p>`:''}${row.discovered===false?'<p class="mini">This saved app is not currently detected. Automatic settings can still be turned off.</p>':''}${!v.appPlan?B('Review changes','app-review',{id:row.id,class:'button-docker-save',disabled:!!row.control_block||!appDirty(v)||v.appBusy||v.appConflict||!!v.appReadError}):''}${appReview(row,v)}<p class="inline-status app-save-status ${v.appError||v.appReadError?'error':''}" role="status" aria-live="polite">${esc(v.appBusy?'Working…':v.appMessage||v.appReadError||(appDirty(v)?'Changes are not saved yet.':''))}</p></div></fieldset>`;
}
function dockerCardBodyKey(row,v){return JSON.stringify([dockerPage.drives,v.appDraft,v.appSaved,v.appPlan,v.appBusy,v.appConflict,v.appMessage,v.appError,v.appReadError,row.discovered,row.control_block,row.warnings,row.state,row.health,row.setup,v.controlBusy,v.controlMessage,v.controlError,dockerPage.boot?.results]);}
function editAppChoice(el){
 const v=applicationViews.get(el.dataset.container),kind=el.dataset.kind,settings=v?.appDraft?.[kind];if(!settings||v.appBusy||appBlocked(el.dataset.container))return;
 if(el.dataset.change==='app-enabled')settings.enabled=el.checked;
 else if(settings.enabled&&el.dataset.change==='app-drive'){
   settings.drives=settings.drives.filter(d=>d.id!==el.dataset.drive);
   if(el.checked)settings.drives.push({id:el.dataset.drive,images:[]});
 }else if(settings.enabled){
   const drive=settings.drives.find(d=>d.id===el.dataset.drive);if(!drive)return;
   drive.images=drive.images.filter(id=>id!==el.value);if(el.checked)drive.images.push(el.value);drive.images.sort();
 }
 settings.drives.sort((a,b)=>a.id.localeCompare(b.id));v.appPlan=null;v.appMessage='';v.appError=false;refreshDockerDOM();
}
async function reviewAppSettings(id){
 const v=dockerView(id);if(!appDirty(v)||v.appBusy||v.appConflict||appBlocked(id))return;
 const session=csrfToken;v.appBusy=true;v.appError=false;v.appMessage='';invalidateDockerReads();refreshDockerDOM();
 try{const result=await apiRequest('docker-app-plan',{data:{revision:v.appRevision,settings:structuredClone(v.appDraft)}});if(csrfToken!==session)return;v.appPlan=result;}
 catch(e){if(csrfToken===session){v.appMessage=operationError(e);v.appError=true;}}
 finally{if(csrfToken===session){v.appBusy=false;refreshDockerDOM();}}
}
async function saveAppSettings(id){
 const v=dockerView(id),plan=v.appPlan;if(!plan?.allowed||v.appBusy||appBlocked(id))return;
 const session=csrfToken;v.appBusy=true;v.appError=false;v.appMessage='';invalidateDockerReads();refreshDockerDOM();
 let result,failure;
 try{
   try{result=await apiRequest('docker-app-save',{data:{token:plan.token,confirm:true}});}catch(e){failure=e;}
   if(csrfToken!==session)return;v.appPlan=null;
   // Read back after success, partial failure or lost response. Never replay save.
   let refreshed=false;
   try{const overview=await apiRequest('docker-overview');if(csrfToken!==session)return;applyDockerOverview(overview);refreshed=true;}catch(e){failure=failure||e;}
   const matches=refreshed&&sameValues(v.appServer,plan.settings);
   v.appMessage=result?((result.applied||[]).join('. ')+(result.applied?.length?'. ':'')+result.message):'Save response unavailable. '+operationError(failure);
   v.appError=!result?.ok||!matches;
   if(matches){v.appDraft=structuredClone(v.appServer);v.appSaved=structuredClone(v.appServer);v.appConflict=false;if(!result)v.appMessage+=' Storage settings match the review; Docker policy/source confirmation is unavailable. Review Advanced details before assuming setup completed.';}
   else if(refreshed){v.appSaved=structuredClone(v.appServer);v.appConflict=false;v.appRevision=dockerPage.appRevision;v.appMessage+=' Unsaved choices remain in this draft; review them again.';}
   else {v.appHeaderUnknown=true;v.appConflict=true;v.appMessage+=' Current settings could not be read. Refresh before another save.';}
 }finally{if(csrfToken===session){v.appBusy=false;invalidateDockerReads();refreshDockerDOM();}}
}
function unavailableEntries(){return dockerPage.containers.filter(row=>row.discovered===false);}
function availableApps(){return dockerPage.containers.filter(row=>row.discovered!==false);}
function unavailableCard(row){
 const v=dockerView(row.id),missing=dockerPage.inventoryOK&&row.state==='missing',plan=v.entryPlan;
 const candidates=availableApps(),eligible=candidates.filter(x=>!appBlocked(x.id)&&!dockerPage.savedEntryIDs?.includes(x.id));
 const disabled=!!row.control_block||!missing||v.entryBusy||!!v.appReadError;
 const settings=v.appSaved;
 const picker=v.entryMode==='reconnect'?`<div class="entry-picker"><label for="${dockerControlId(row.id,'','target')}">Choose an existing container</label><select id="${dockerControlId(row.id,'','target')}" data-change="entry-target" data-container="${attr(row.id)}" ${disabled?'disabled':''}><option value="">Select a container identity…</option>${candidates.map(x=>`<option value="${attr(x.id)}" ${v.entryTarget===x.id?'selected':''} ${appBlocked(x.id)||dockerPage.savedEntryIDs?.includes(x.id)?'disabled':''}>${esc(x.name)} · ${esc(x.id)}${dockerPage.savedEntryIDs?.includes(x.id)?' · already has saved settings':''}</option>`).join('')}</select>${v.entryTarget?`<p class="mini">Selected ID: <code>${esc(v.entryTarget)}</code></p>`:''}${!eligible.length?'<p class="mini">No unconfigured destination is available. Existing app settings will not be merged or overwritten. Remove the obsolete entry to leave those apps unchanged.</p>':''}${B('Review reconnection','entry-review',{id:row.id,class:'button-primary',disabled:disabled||!eligible.some(x=>x.id===v.entryTarget)})}</div>`:'';
 return `<details class="unavailable-entry" data-unavailable-entry="${attr(row.id)}" ${v.entryOpen?'open':''}><summary><strong>${esc(row.name)}</strong> ${chip(missing?'Missing':'Status unavailable','muted')}${appSettingIndicators(row)}<span class="mini entry-id">ID ${esc(row.id.slice(0,12))}…</span>${appRecoveryNotice(row)}</summary><div class="unavailable-entry-body"><fieldset class="app-control-fields" ${row.control_block?'disabled':''} aria-label="Saved app controls"><p class="mini">Saved container ID: <code>${esc(row.id)}</code></p>${settings?`<p class="small">Computer startup: ${settings.boot.enabled?'On':'Off'} · ${esc(setupStorageSummary(settings.boot.drives))}</p><p class="small">Drive failure &amp; recovery: ${settings.recovery.enabled?'On':'Off'} · ${esc(setupStorageSummary(settings.recovery.drives))}</p>`:''}${!missing?'<p class="inline-status">Docker inventory is unavailable. Saved settings are retained; reconnect and removal require a successful refresh.</p>':''}<p class="mini">Remove saved entry deletes Storage Watch settings only. Docker containers, application files and historical recovery records are kept.</p><div class="actions">${B('Reconnect to an existing container','entry-reconnect',{id:row.id,class:'button-neutral',disabled})}${B('Remove saved entry','entry-remove',{id:row.id,class:'button-warning',disabled})}</div>${!plan?picker:`<section class="setup-review entry-review"><h3>${plan.operation==='remove'?'Remove saved entry?':'Reconnect saved entry?'}</h3><p>${esc(plan.message)}</p><p>From: <strong>${esc(plan.source.name)}</strong><br><code>${esc(plan.source.id)}</code></p>${plan.target?`<p>To: <strong>${esc(plan.target.name)}</strong><br><code>${esc(plan.target.id)}</code></p>`:''}<p class="mini">The affected settings will be backed up privately before this change.</p>${B(plan.operation==='remove'?'Confirm removal':'Confirm reconnection','entry-apply',{id:row.id,class:'button-primary',disabled})}${B('Cancel','entry-cancel',{id:row.id,class:'button-neutral',disabled:v.entryBusy})}</section>`}<p class="inline-status ${v.entryError?'error':''}" role="status" aria-live="polite">${esc(v.entryBusy?'Checking saved identity…':v.entryMessage||'')}</p></fieldset></div></details>`;
}
function unavailableSection(){
 const rows=unavailableEntries();
 return `${rows.length?`<section class="unavailable-apps"><h2>${dockerPage.inventoryOK?'Unavailable apps':'Saved apps · Docker status unavailable'} <span class="mini">${rows.length}</span></h2>${rows.map(unavailableCard).join('')}</section>`:''}<p id="entry-result" class="inline-status" role="status" aria-live="polite">${esc(dockerPage.entryMessage||'')}</p>`;
}
function entryEditable(id){const row=dockerPage.containers.find(x=>x.id===id);return !appBlocked(id)&&dockerPage.inventoryOK&&row?.state==='missing'&&row.discovered===false;}
function beginEntryReconnect(id){const v=dockerView(id);if(!entryEditable(id)||v.entryBusy)return;v.entryMode='reconnect';v.entryPlan=null;v.entryMessage='';v.entryError=false;refreshDockerDOM();}
async function reviewEntry(id,operation){
 const row=dockerPage.containers.find(x=>x.id===id),v=dockerView(id);if(!entryEditable(id)||v.entryBusy)return;
 const target=operation==='reconnect'?availableApps().find(x=>x.id===v.entryTarget):null;
 if(operation==='reconnect'&&(!target||appBlocked(target.id)))return;
 const session=csrfToken;v.entryBusy=true;v.entryPlan=null;v.entryMessage='';v.entryError=false;invalidateDockerReads();refreshDockerDOM();
 try{
   const result=await apiRequest('docker-entry-plan',{data:{id:row.id,name:row.name,revision:dockerPage.appRevision,operation,target:target?{id:target.id,name:target.name}:null}});
   if(session===csrfToken)v.entryPlan=result;
 }catch(e){if(session===csrfToken){v.entryMessage=operationError(e);v.entryError=true;}}
 finally{if(session===csrfToken){v.entryBusy=false;refreshDockerDOM();}}
}
async function applyEntry(id){
 const v=dockerView(id),plan=v.entryPlan;if(!plan||v.entryBusy||!entryEditable(id))return;
 const session=csrfToken;v.entryBusy=true;v.entryMessage='';v.entryError=false;invalidateDockerReads();refreshDockerDOM();
 let result,failure;
 try{
   try{result=await apiRequest('docker-entry-apply',{data:{token:plan.token,confirm:true}});}catch(e){failure=e;}
   if(session!==csrfToken)return;v.entryPlan=null;
   let refreshed=false;
   try{const overview=await apiRequest('docker-overview');if(session!==csrfToken)return;applyDockerOverview(overview);refreshed=true;}catch(e){failure=failure||e;}
   if(result?.ok){dockerPage.entryMessage=result.message;v.entryMessage='';}
   else {v.entryMessage=(failure?operationError(failure):result?.message||'The change was not confirmed.')+' No request was repeated. Refresh saved settings before another action.';v.entryError=true;if(refreshed&&!dockerPage.savedEntryIDs?.includes(id))dockerPage.entryMessage=v.entryMessage;}
 }finally{if(session===csrfToken){v.entryBusy=false;invalidateDockerReads();refreshDockerDOM();}}
}
function dockerCard(row){
 const v=dockerView(row.id),bodyId=dockerControlId(row.id,'','body');v.bodyKey=dockerCardBodyKey(row,v);
 return `<article class="docker-container card" data-container-id="${attr(row.id)}"><button id="${dockerControlId(row.id,'','header')}" type="button" class="docker-container-header" data-action="docker-collapse" data-id="${attr(row.id)}" aria-expanded="${!v.collapsed}" aria-controls="${bodyId}" aria-describedby="${dockerControlId(row.id,'','saved-indicators')}" aria-label="${v.collapsed?'Expand':'Collapse'} settings for ${attr(row.name)}"><span class="docker-header-main"><span class="docker-container-name">${icon('apps','docker-container-icon')}<span role="heading" aria-level="2">${esc(row.name)}</span></span>${appSettingIndicators(row)}</span><span class="docker-container-header-end"><span class="docker-live-state">${applicationState(row)}</span>${icon('chevron','docker-collapse-icon')}</span></button>${appRecoveryNotice(row)}<div id="${bodyId}" class="docker-container-body" ${v.collapsed?'hidden':''}>${dockerCardBody(row,v)}</div></article>`;
}
function dockerControlsBusy(){return [...applicationViews.values()].some(v=>v.controlBusy||v.appBusy||v.entryBusy);}
function dockerRefreshFeedback(){return dockerPage.loading?'Refreshing containers…':dockerPage.refreshMessage||(dockerPage.observedAt?'Updated '+humanTime(dockerPage.observedAt):'Not refreshed yet');}
function dockerContainerCount(){const count=dockerPage.containers.filter(row=>row.discovered!==false).length;return count+' container'+(count===1?'':'s')+' detected';}
function appsPage(){
 return `${header('Startup and recovery','Docker & Applications','Control your apps and choose their drives separately for computer startup and drive recovery.')}<p class="docker-page-guidance">Docker options stay editable whether drive monitoring is on or off.</p><div class="section-heading docker-toolbar"><div><h2>Apps</h2><p class="mini docker-container-count">${dockerPage.loaded?dockerContainerCount():'Reading Docker containers…'}</p></div><div class="refresh-control">${B('Refresh apps','applications-refresh',{class:'button-utility',icon:'refresh',disabled:dockerPage.loading||!!dockerPage.saving||dockerControlsBusy()})}<span id="docker-refresh-status" class="inline-status" role="status" aria-live="polite">${esc(dockerRefreshFeedback())}</span></div></div><div id="docker-page-error" ${dockerPage.error?'':'hidden'} class="callout warn" role="status">${esc(dockerPage.error)}</div><div id="docker-containers" class="stack">${availableApps().map(dockerCard).join('')||`<div class="card empty"><strong>${dockerPage.error?'Docker inventory unavailable':dockerPage.loaded?'No Docker containers detected':'Loading containers…'}</strong><p>${dockerPage.error?'Refresh when Docker is available. Saved settings are retained below.':dockerPage.loaded?'Install a container with your preferred Docker tools, then refresh this list.':'Your saved recovery settings will appear here.'}</p></div>`}</div><div id="unavailable-app-list">${unavailableSection()}</div>`;
}
function refreshDockerDOM(){
 if(route()!=='apps')return;
 const root=$('#docker-containers');if(!root){render();return;}
 rememberAppExpansion();
 const focused=document.activeElement?.id;
 const current=$$('.docker-container',root);
 const live=availableApps();
 if(current.length!==live.length||current.some((el,i)=>el.dataset.containerId!==live[i]?.id))root.innerHTML=availableApps().map(dockerCard).join('')||`<div class="card empty"><strong>${dockerPage.error?'Docker inventory unavailable':dockerPage.loaded?'No Docker containers detected':'Loading containers…'}</strong><p>${dockerPage.error?'Refresh when Docker is available. Saved settings are retained below.':'Install a container with your preferred Docker tools, then refresh this list.'}</p></div>`;
 else for(const row of live){
   const node=current.find(el=>el.dataset.containerId===row.id),v=dockerView(row.id),body=$('.docker-container-body',node),button=$('.docker-container-header',node);
   $('.docker-live-state',node).innerHTML=applicationState(row);$('.app-saved-indicators',node).outerHTML=appSettingIndicators(row);button.setAttribute('aria-expanded',String(!v.collapsed));button.setAttribute('aria-label',(v.collapsed?'Expand':'Collapse')+' settings for '+row.name);body.hidden=v.collapsed;
   const key=dockerCardBodyKey(row,v);if(v.bodyKey!==key){v.advanced=$('.app-advanced',body)?.open||false;body.innerHTML=dockerCardBody(row,v);v.bodyKey=key;}
 }
 const unavailable=$('#unavailable-app-list');if(unavailable){const markup=unavailableSection();if(unavailable._markup!==markup){unavailable.innerHTML=markup;unavailable._markup=markup;}}
 const count=$('.docker-container-count');if(count)count.textContent=dockerPage.loaded?dockerContainerCount():'Reading Docker containers…';
 const error=$('#docker-page-error');if(error){error.hidden=!dockerPage.error;error.textContent=dockerPage.error;}
 const feedback=$('#docker-refresh-status');if(feedback)feedback.textContent=dockerRefreshFeedback();
 syncAppControlLocks();syncTouchSelects();
 const refresh=$('[data-action="applications-refresh"]');if(refresh)refresh.disabled=dockerPage.loading||!!dockerPage.saving||dockerControlsBusy();
 if(focused&&document.activeElement?.id!==focused)document.getElementById(focused)?.focus({preventScroll:true});
}
async function loadApplications({background=false}={}){
 if(dockerPage.reading||dockerPage.saving||dockerControlsBusy())return;
 const sequence=++dockerPage.sequence,session=csrfToken;dockerPage.reading=true;dockerPage.loading=!background;
 if(!background){dockerPage.refreshMessage='';refreshDockerDOM();}
 try{
   const result=await apiRequest('docker-overview');if(sequence!==dockerPage.sequence||csrfToken!==session)return;
   applyDockerOverview(result);dockerPage.refreshMessage='Updated '+humanTime(result.observed_at);
 }catch(e){
   if(sequence!==dockerPage.sequence||csrfToken!==session)return;
   dockerPage.settingsStale=true;dockerPage.inventoryOK=false;for(const v of applicationViews.values())v.entryPlan=null;
   dockerPage.error='Docker refresh failed: '+errorMessage(e);dockerPage.refreshMessage='Refresh failed. Your choices are retained.';
   dockerPage.containers=dockerPage.containers.map(row=>({...row,state:'unknown',health:null}));
 }finally{if(sequence===dockerPage.sequence&&csrfToken===session){dockerPage.reading=false;dockerPage.loading=false;refreshDockerDOM();}}
}
function collapseDockerCard(id){const v=applicationViews.get(id);if(!v||appBlocked(id))return;v.collapsed=!v.collapsed;rememberDockerCollapse(id,v.collapsed);refreshDockerDOM();}
function reloadDockerSettings(id){const v=applicationViews.get(id);if(!v?.appServer||appBlocked(id))return;v.appSaved=structuredClone(v.appServer);v.appDraft=structuredClone(v.appServer);v.appRevision=dockerPage.appRevision;v.appConflict=false;v.appPlan=null;v.appMessage='Saved settings loaded.';v.appError=false;refreshDockerDOM();}

const settingsDrafts=new Map();
const sameValues=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function settingsRecord(d,group){
 if(!d)return null;
 const key=d.id+':'+group;
 if(!settingsDrafts.has(key))settingsDrafts.set(key,{saved:null,draft:group==='timings'?{check:d.timings.check,confirm:d.timings.confirm,recovery:d.timings.recovery,returntimeout:d.timings.returntimeout??5,usbwait:d.timings.usbwait}:{minutes:Math.round(d.standbyIdleSeconds/60),enabled:d.autoSleep},saving:false,message:'',error:false});
 return settingsDrafts.get(key);
}
function settingsValues(d,group){return settingsRecord(d,group).draft;}
function settingsFeedback(d,group){const r=settingsRecord(d,group);return `<span class="inline-status ${r?.error?'error':''}" data-settings-status="${group}" role="status">${esc(r?.message||'')}</span>`;}
function syncSettingsDrafts(d,config){
 for(const group of ['timings','standby']){
   const r=settingsRecord(d,group),clean=r.saved===null||sameValues(r.saved,r.draft);
   const saved=group==='timings'?{check:d.timings.check,confirm:d.timings.confirm,recovery:d.timings.recovery,returntimeout:d.timings.returntimeout??5,usbwait:d.timings.usbwait}:{minutes:Math.round(d.standbyIdleSeconds/60),enabled:d.autoSleep};
   r.saved=saved;r.revision=config.revision;
   if(clean)r.draft={...saved};
 }
}
function captureSettings(el){
 const group=el.dataset.timing==='sleep'||el.id==='standby-auto'?'standby':'timings';
 const parent=el.closest(group==='standby'?'form[data-form="standby-settings"]':'.timing-settings');
 const d=find(parent?.dataset.id);if(!d)return;
 const r=settingsRecord(d,group);
 r.draft=group==='standby'?{minutes:Number($('#standby-idle',parent).value),enabled:$('#standby-auto',parent).checked}:Object.fromEntries(['check','confirm','recovery','returntimeout','usbwait'].map(k=>[k,Number($(`[data-timing="${k}"]`,parent).value)]));
 if(!r.saving){r.message='';r.error=false;}
 updateSettingsButtons();
}
function updateSettingsButtons(){
 if(route()!=='advanced')return;
 const d=find(state.advancedDrive)||configured()[0];if(!d)return;
 for(const group of ['timings','standby']){
   const r=settingsRecord(d,group),parent=group==='timings'?$('.timing-settings'):$('[data-form="standby-settings"]');
   if(!parent)continue;
   const button=$(group==='timings'?'[data-action="timings-save"]':'[data-settings-save="standby"]',parent);
   if(button)button.disabled=!r.saved||r.saving||sameValues(r.saved,r.draft)||!Array.from(parent.querySelectorAll(group==='timings'?'[data-timing]:not([data-timing="sleep"])':'[data-timing]')).every(el=>el.checkValidity());
   const status=$('[data-settings-status="'+group+'"]',parent);if(status){status.textContent=r.message;status.classList.toggle('error',r.error);}
 }
}
async function saveSettings(id,group){
 const d=find(id);if(!d)return;
 const r=settingsRecord(d,group);
 if(apiBusy){r.error=true;r.message='Another operation is still running. Wait for its result, then save again.';updateSettingsButtons();return;}
 if(!r.saved||r.saving||sameValues(r.saved,r.draft))return;
 const values={...r.draft};
 await withAction(async()=>{
   r.saving=true;r.message='Saving…';r.error=false;updateSettingsButtons();
   try{
     const cfg=detailCache.get(id)?.config;if(!cfg?.revision)throw Error('Reload settings before saving.');
     const data=group==='timings'?{revision:cfg.revision,timings:{monitor:{interval:values.check,observations:values.confirm},recovery:{wait:values.recovery,return_timeout_minutes:values.returntimeout},usb:{enumeration_seconds:values.usbwait}}}:{revision:cfg.revision,enabled:values.enabled,idle_seconds:values.minutes*60};
     const result=await apiRequest(group==='timings'?'timing-settings':'standby-settings',{drive:id,data});
     // An acknowledged write is the baseline even if a later status read fails.
     r.saved={...values};r.message='Saved';
     if(group==='timings'){Object.assign(cfg.config.monitor,data.timings.monitor);Object.assign(cfg.config.recovery,data.timings.recovery);Object.assign(cfg.config.usb,data.timings.usb);}
     else cfg.config.standby={...cfg.config.standby,enabled:values.enabled,idle_seconds:data.idle_seconds};
     if(result.revision)cfg.revision=result.revision;
     enrichDrive(d,{config:cfg});
     toast(result.message||'Settings saved.');
   }catch(e){r.message='Save not confirmed: '+errorMessage(e);r.error=true;toast(r.message,true);}
   finally{r.saving=false;updateSettingsButtons();}
 });
}
const eventRefresh={busy:false,message:'',error:false};
function eventRefreshControl(){return `<div class="refresh-control">${B('Refresh events','refresh-events',{class:'button-utility',icon:'refresh',disabled:eventRefresh.busy})}<span class="inline-status ${eventRefresh.error?'error':''}" data-event-refresh-status role="status">${esc(eventRefresh.message)}</span></div>`;}
function updateEventRefresh(){
 $$('[data-action="refresh-events"]').forEach(b=>b.disabled=eventRefresh.busy);
 $$('[data-event-refresh-status]').forEach(el=>{el.textContent=eventRefresh.message;el.classList.toggle('error',eventRefresh.error);});
}
async function refreshEventsInline(){
 if(eventRefresh.busy)return;
 eventRefresh.busy=true;eventRefresh.message='Refreshing…';eventRefresh.error=false;updateEventRefresh();
 try{await refreshHistory({display:true});eventRefresh.message='Updated';}
 catch(e){eventRefresh.error=true;eventRefresh.message='Refresh failed: '+errorMessage(e);}
 finally{eventRefresh.busy=false;updateEventRefresh();}
}

function preparationProgress(value){
 const working=['preparing','erasing','formatting','formatted','mounting','verifying'].includes(value.phase);
 const ready=['ready','complete'].includes(value.phase),failed=value.phase==='failed';
 const style=working?'working':ready?'finished success':failed?'finished failed':'finished';
 const mark=working?'<span class="busy-spinner" aria-hidden="true"></span>':ready?icon('check'):failed?icon('warning'):'';
 const label=ready?'Ready':failed?'Failed':value.phase||'Status unavailable';
 return `<div class="helper-panel preparation-progress ${style}" role="status" aria-busy="${working}">${mark}<strong>${esc(value.name||value.model||'Drive')} — ${esc(label)}</strong><p>${esc(value.message||'')}</p></div>`;
}
function preparePage(){const s=state.prepareDisks?.find(x=>x.device===state.selectedPrepare);return `${header('Storage tools','Prepare Drive','Formatting is optional. Existing ext4 drives can be monitored without formatting.')}<section class="card"><div class="callout danger">${icon('warning')}<div><strong>Formatting permanently erases ALL files on the selected physical USB drive.</strong> The server checks drive identity and exclusive access again before acting.</div></div><div class="section-heading" data-style="usw-inline-10"><h2>Select the USB drive to prepare</h2>${B('Refresh drives','refresh-drives',{class:'button-utility',icon:'refresh'})}</div><div class="prep-disk-list">${(state.prepareDisks||[]).map(d=>`<label class="prep-disk ${state.selectedPrepare===d.device?'selected':''}"><input type="radio" class="radio" name="prepare-device" data-change="prepare-selection" value="${attr(d.device)}" ${state.selectedPrepare===d.device?'checked':''}><span class="icon-device">${icon(d.media_kind||'unknown','')}</span><span class="info"><strong>${esc(d.model)} · ${readableSize(d.size)}</strong><span>${esc(d.reason||'Eligible for formatting review')}</span></span>${d.reason?chip('Unavailable','warn'):chip('Available','good')}</label>`).join('')||'<div class="empty">No physical USB disks detected.</div>'}</div><div class="actions">${B('Review drive erasure','format-review',{class:'button-danger',disabled:!s||!!s.reason})}</div>${(state.prepareOperations||[]).map(preparationProgress).join('')}</section>`;}
function historyPage(){const filter=state.historyDrive;const events=state.history.filter(e=>filter==='all'||e.drive===filter).sort((a,b)=>new Date(b.time)-new Date(a.time));return `${header('Monitoring history','Event History','Events from all configured drives, with a stable filter and drive identification.')}<section class="card"><div class="field" data-style="usw-inline-3"><label for="history-filter">Show events for</label><select id="history-filter" data-change="history-filter"><option value="all">All drives</option>${configured().map(d=>`<option value="${attr(d.id)}" ${d.id===filter?'selected':''}>${driveName(d)}</option>`).join('')}</select></div><div class="callout">${icon('history')}<div>Event history describes earlier incidents, not current drive health.</div></div><div class="actions">${eventRefreshControl()}<span id="history-updated" class="mini">Last updated: ${esc(state.historyUpdatedAt)}</span></div><div id="history-events">${renderHistoryEntries(events)}</div></section>`;}
function emailPage(){const s=state.smtp;return `${header('Notifications','Email & Notifications','One shared SMTP account. Per-drive alert switches are in Manage Drive.')}<div class="stack"><section class="card"><h2>SMTP account settings</h2><p>These settings are shared. Sending a test email contacts your configured SMTP server.</p><form data-form="email-save"><div class="form-grid">${field('SMTP server','smtp-server',s.server,'text','','required')}<div class="field"><label for="smtp-security">Connection security</label><select id="smtp-security"><option value="tls" ${s.security==='tls'?'selected':''}>TLS — usually port 465</option><option value="starttls" ${s.security==='starttls'?'selected':''}>STARTTLS — usually port 587</option></select></div>${field('Port','smtp-port',s.port,'number','','min="1" max="65535" required')}${field('SMTP username','smtp-user',s.user,'text','','autocomplete="username"')}${field('SMTP password','smtp-password','','password','Saved passwords are not returned to the browser.','autocomplete="new-password" placeholder="Leave blank to keep existing"')}${field('Send from','smtp-from',s.from,'email')}${field('Send to','smtp-to',s.to,'email')}</div><div class="actions">${submitControl('Save email settings','email-save')}${B('Send test email','test-email',{class:'button-utility'})}</div></form></section><section class="card"><h2>Per-drive notification preferences</h2><p>Use the immediate checkbox in each Manage Drive page.</p>${configured().map(d=>`<div class="selection-row"><span><strong class="title">${driveName(d)}</strong></span>${B('Manage','manage-drive',{id:d.id,class:'button-neutral'})}</div>`).join('')}</section></div>`;}
function managementTokenPanel(){return `<section class="card" id="management-token-panel"><h2 id="management-token-heading" tabindex="-1">Management token</h2><p>Use the same management token as dashboard login. On the Storage Watch computer, retrieve it with:</p><div class="helper-panel"><code>sudo cat /var/lib/usb-storage-watch/management.token</code><div class="actions">${B('Copy command','copy-token-command',{class:'button-neutral',icon:'copy'})}</div></div><p>Paste it into Companion’s <strong>Dashboard management token</strong> field. It grants dashboard administration; keep it private.</p><p class="mini">Replacement is only needed to revoke access. It signs out dashboard sessions and requires updating Companion’s token.</p><div class="actions">${B('Replace management token','rotate-token',{class:'button-utility'})}</div></section>`;}
function integrationConnection(){
 const v=networkView,known=v.loaded&&!v.readError,url=known?(v.saved?.lan?v.url:v.localUrl):null;
 const message=!known?(v.readError||'Checking active network settings…'):v.saved?.lan?(v.listener?.message||'Waiting for a network address'):'Network access is disabled. This URL works only on the Storage Watch computer.';
 return `<section class="card"><h2>Server URL</h2><div class="network-url-line"><code id="integration-url">${esc(url||message)}</code>${url?B('Copy URL','integration-copy-url',{class:'button-neutral',icon:'copy'}):''}</div>${url?`<p>${esc(message)}</p>`:''}${url?.startsWith('http:')&&v.saved?.lan?'<p class="inline-status error">Companion requires HTTPS for a network connection. Enable HTTPS in Advanced Settings.</p>':''}<div class="actions">${B('Network Settings','nav',{id:'network-panel',value:'advanced',class:'button-quiet'})}</div></section>`;
}
function integrationsPage(){
 const info=state.integrationInfo||{},pem=info.certificate_pem,module=info.module;
 return `${header('Companion setup','Integrations','Connect Bitfocus Companion to this Storage Watch server.')}<div class="stack" id="integration-setup">${integrationConnection()}
 <section class="card"><h2>Management token</h2><p>On the Storage Watch computer, retrieve your existing dashboard token:</p><div class="helper-panel"><code>sudo cat /var/lib/usb-storage-watch/management.token</code><div class="actions">${B('Copy command','copy-token-command',{class:'button-neutral',icon:'copy'})}</div></div><p>Paste it into Companion’s <strong>Dashboard management token</strong> field. Keep it private.</p><div class="actions">${B('Manage token','nav',{id:'management-token-panel',value:'advanced',class:'button-quiet'})}</div></section>
 <section class="card"><h2>Public CA certificate</h2><p>For HTTPS, paste the complete PEM into Companion’s <strong>Trusted public CA certificate (PEM, optional)</strong> field. Verify this certificate on the Storage Watch computer before trusting it. Certificate verification stays enabled.</p>${pem?`<div class="actions">${B('Copy certificate','integration-copy-ca',{class:'button-neutral',icon:'copy'})}</div><details class="detail" id="integration-certificate" ${state.integrationCertificateOpen?'open':''}><summary>Show public certificate (PEM)</summary><div class="field"><label for="integration-pem">Complete public certificate (PEM)</label><textarea id="integration-pem" class="integration-pem" rows="9" readonly spellcheck="false">${esc(pem)}</textarea></div></details>`:`<p role="status">${esc(info.error||(!info.module?'Loading public certificate…':'Public CA certificate unavailable. Check HTTPS setup in Advanced Settings.'))}</p>`}</section>
 <section class="card"><h2>Install the Companion module</h2><p>In Companion 5.1 or later, open <strong>Modules → Import module package</strong>, import the archive, then add USB Storage Watch or select the imported version on your existing connection.</p><p>Enter the server URL, management token and public CA above. Existing 0.2.5/0.2.6 buttons do not need replacement. Drives and apps are discovered automatically.</p>${module?.available?`<a class="button button-primary" href="/download/companion-module.tgz" download="usb-storage-watch-companion-${attr(module.version)}.tgz">Download module ${esc(module.version)}</a>`:`<p role="status">${esc(info.error||(!module?'Checking module package…':'No module package is bundled with this installation. Import the release archive supplied with Storage Watch.'))}</p>`}</section></div>`;
}

function httpsTrustGuide(){
 if(!state.lan||state.lanSecure!=='https')return '';
 return `<details class="detail network-trust"><summary>HTTPS certificate — download and setup instructions</summary><p>For Chrome or other browsers on another device, first verify the certificate fingerprint against the one displayed on the host computer. Only trust a certificate from a host you control.</p>${state.certificateAvailable?`<div class="actions"><a class="button button-neutral" href="/download/trust-certificate.pem" download="usb-storage-watch-trust-certificate.pem">Download local HTTPS trust certificate</a></div>`:'<div class="callout warn">No downloadable local trust certificate is currently available. Check your HTTPS setup on the host computer.</div>'}${state.lanFingerprint?`<p class="mini path">${esc(state.lanFingerprint)}</p>`:''}<div class="card-section"><h3>Windows — Chrome and Edge</h3><p>Save the public certificate. On Windows, open the Certificates manager for your account (Win + R → certmgr.msc). Import the VERIFIED local CA certificate under Trusted Root Certification Authorities, then restart the browser and reopen the same HTTPS address.</p><h3>Linux — Chrome or Chromium</h3><p>Import the verified CA certificate into the trusted certificate store used by your browser/distribution. Restart the browser. Certificate management differs between Linux distributions and browser installations.</p><h3>macOS — Chrome or Safari</h3><p>Import the verified certificate using Keychain Access or the macOS certificate trust settings. Explicitly enable trust for this local CA, then restart the browser.</p><h3>Android and other devices</h3><p>Device-managed certificate settings vary. Some browsers or applications may not trust user-installed CAs. Do not bypass security warnings; use a certificate from an already trusted issuer when necessary.</p></div><p class="mini">This downloads the public local CA certificate, never the private key. Verify the fingerprint directly on the host computer before trusting it. A different IP address or an expired certificate can still cause warnings.</p></details>`;
}
function standbyControls(d){
 const enabled=!!d&&(d.kind==='hdd'||d.standbyApplicable)&&!d.stale;
 const draft=d?settingsValues(d,'standby'):{minutes:30,enabled:false};
 const idle=draft.minutes;
 return `<section class="standby-card standby-subsection ${enabled?'':'unavailable'}" aria-labelledby="standby-heading"><h3 id="standby-heading">HDD standby & noise control</h3><p>${enabled?`Configure automatic spin-down for <strong>${driveName(d)}</strong>.`:'Select a mechanical HDD to use standby settings.'} Active files, Docker containers or disk I/O will prevent standby.</p><div class="labelrow">${d?standbyBadge(d):chip('HDD sleep: No drive selected','muted')}</div><form data-form="standby-settings" data-id="${attr(d?.id||'')}"><fieldset ${enabled?'':'disabled'}><legend class="sr-only">Automatic HDD standby</legend><div class="toggle-row"><div class="toggle-copy"><label for="standby-auto"><strong>Automatically spin down this HDD when idle</strong></label></div><input type="checkbox" role="switch" class="toggle" id="standby-auto" aria-label="Automatically spin down this HDD when idle" ${draft.enabled?'checked':''}></div>${timingControl({key:'sleep',inputId:'standby-idle',label:'Sleep after inactivity (minutes)',min:1,max:1440,value:idle,hint:'Wait this long without drive activity before requesting standby. A busy disk will not be forced to sleep.'})}<div class="actions"><button type="submit" class="button button-primary" data-settings-save="standby" disabled>Save HDD standby settings</button>${settingsFeedback(d,'standby')}</div></fieldset></form><p class="mini">Use Sleep HDD now on Manage Drive to request standby without waiting for the idle timer. Pending writes are flushed, then the app waits up to 15 seconds for activity to settle. Monitoring stays in its current state. Normal file access can wake the disk.</p></section>`;
}

function advancedPage(){const d=find(state.advancedDrive)||configured()[0];return `${header('Configuration','Advanced Settings','Technical controls stay separate from everyday drive management.')}<div class="stack">${networkPanel()}${d?`<section class="card timing-settings" data-id="${attr(d.id)}"><h2>Timing & recovery limits</h2><div class="field"><label for="advanced-drive">Drive</label><select id="advanced-drive" data-change="advanced-drive">${configured().map(x=>`<option value="${attr(x.id)}" ${x.id===d.id?'selected':''}>${driveName(x)}</option>`).join('')}</select></div>${settingGroup('Drive monitoring','Observe the selected filesystem independently.',[{key:'check',label:'Check drive every (seconds)',step:1,min:5,max:3600,hint:'How often Storage Watch checks whether the selected drive is still available. A shorter interval detects problems sooner.'},{key:'confirm',label:'Checks to confirm a change',step:1,min:1,max:10,hint:'Number of consecutive checks that must report the same problem before an outage is confirmed. This avoids false alarms from brief interruptions.'}],d)}${settingGroup('USB recovery','Bounded recovery windows.',[{key:'recovery',label:'Wait before recovery (seconds)',step:5,min:15,max:86400,hint:'How long Storage Watch waits after confirming an outage before beginning its guarded recovery attempts.'},{key:'returntimeout',label:'Drive return timeout (minutes)',step:1,min:1,max:1440,hint:'Report recovery failure if the drive has not returned within this time.'},{key:'usbwait',label:'Wait for USB drive to return (seconds)',step:1,min:1,max:60,hint:'How long the application waits for the verified USB drive to reappear after a software port reconnect.'}],d)}<div class="actions">${B('Save timing settings','timings-save',{class:'button-primary',id:d.id,disabled:true})}${settingsFeedback(d,'timings')}</div>${standbyControls(d)}</section>`:''}${managementTokenPanel()}</div>`;}
async function loadIntegrationData(){
 const session=csrfToken,before=JSON.stringify([state.integrationInfo,networkView.saved,networkView.url,networkView.localUrl,networkView.listener,networkView.readError]);
 const results=await Promise.allSettled([refreshNetwork({display:false}),apiRequest('integration-info')]);
 if(session!==csrfToken)return;
 if(results[0].status==='rejected'){networkView.readError='Network status unavailable. '+errorMessage(results[0].reason);networkView.url=null;}
 state.integrationInfo=results[1].status==='fulfilled'?results[1].value:{error:'Setup information unavailable. '+errorMessage(results[1].reason)};
 const after=JSON.stringify([state.integrationInfo,networkView.saved,networkView.url,networkView.localUrl,networkView.listener,networkView.readError]);
 if(route()==='integrations'&&before!==after)render();
}
async function act(action,id,value,context=null){
 if(/^(docker-|app-|entry-)/.test(action)&&appBlocked(id))return {message:appBlocked(id),error:true};
 const d=find(id);
 const notify=(message,error=false)=>actionNotice(context,message,error);
 try{
 if(action.startsWith('network-'))return await networkCommand(action,id,value,context);
 switch(action){
 case 'nav':navigate(value,id);return;
 case 'notifications':showNotifications();return;
 case 'clear-notifications':clearNotifications();return;
 case 'applications-refresh':await loadApplications();return;
 case 'entry-reconnect':beginEntryReconnect(id);return;
 case 'entry-review':await reviewEntry(id,'reconnect');return;
 case 'entry-remove':await reviewEntry(id,'remove');return;
 case 'entry-apply':await applyEntry(id);return;
 case 'entry-cancel':dockerView(id).entryPlan=null;dockerView(id).entryMode=null;refreshDockerDOM();return;
 case 'app-permission':return await reviewAppPermission(id,Number(value));
 case 'app-review':await reviewAppSettings(id);return;
 case 'app-save':await saveAppSettings(id);return;
 case 'app-cancel':dockerView(id).appPlan=null;refreshDockerDOM();return;
 case 'docker-start':case 'docker-stop':case 'docker-restart':return await reviewDockerControl(id,action.slice(7),context);
 case 'docker-collapse':collapseDockerCard(id);return;
 case 'docker-reload':reloadDockerSettings(id);return;
 case 'menu':{const sidebar=$('#sidebar'),open=!sidebar.classList.contains('open');sidebar.classList.toggle('open',open);$('#mobile-backdrop').hidden=!open;$('[data-action="menu"]')?.setAttribute('aria-expanded',String(open));return;}
 case 'sign-out':await withAction(async()=>{await apiRequest('logout',{data:{}});showLogin();});return;
 case 'close-modal':if(modalPending)return;closeModal();modalAction=null;return;
 case 'confirmed-action':{
   if(modalPending)return;
   const fn=modalAction;
   if(apiBusy&&!fn?.independentOfStorage)throw Error(preferencesSaving?'Mount on recovery is still being saved. Wait for “Saved”, then confirm.':'Another storage operation is still running. Wait for its result, then confirm.');
   if(!fn||!modalWorking())return;
   const original=$('#modal-root .modal');modalAction=null;
   try{return await fn(context);}catch(e){
     if(e.uncertain){modalAction=null;if(context)context.uncertain=true;}
     throw e;
   }finally{
     // Failed/refused operations may leave the confirmation open for review.
     if(original?.isConnected&&modalPending){
       modalWorkFinished();
       if(!modalAction&&context?.uncertain!==true&&!fn.singleUse)modalAction=fn;
       if(context?.uncertain||fn.singleUse){const confirm=$('[data-action="confirmed-action"]',original);if(confirm){confirm.dataset.baseDisabled='true';confirm.disabled=true;}}
       if(fn.singleUse){
         const note=document.createElement('p');note.className='callout warn';note.setAttribute('role','status');
         note.textContent=fn.singleUseMessage||'This confirmation has been used. Close this dialog, check the current drive and app status, then choose Unmount safely to review again. No request will be repeated automatically.';
         $('.modal-actions',original)?.before(note);
         const close=$('[data-action="close-modal"]',original);if(close)close.textContent='Close';
       }
     }
   }
   return;
 }
 case 'refresh-events':await refreshEventsInline();return;
 case 'refresh-drives':await withAction(async()=>{if(route()==='prepare'){await refreshPrepare();notify('Physical USB drive list refreshed.');}else{await refreshFleet();notify('Drive list refreshed at '+state.lastRefresh);}});return;
 case 'open-add-drive':await withAction(async()=>{await refreshFleet({display:false});openAddDrive();});return;
 case 'add-detected':if(!d||d.configured||!d.uuid)return;await withAction(async()=>{const result=await apiRequest('add-drive',{data:{uuid:d.uuid}});closeModal();notify(result.message||'Drive registered.');await refreshFleet({display:false});navigate('drive/'+result.profile_id);await refreshDetail(result.profile_id);});return;
 case 'manage-drive':if(d?.configured)navigate('drive/'+id);return;
 case 'remove-drive-review':return await openRemoveDrive(d,context);
 case 'toggle-monitoring':if(!d||!d.configured)return;
   return await withAction(async()=>setMonitoring(d,!d.monitoring));
 case 'sleep-hdd':if(!d)return;
   confirmAction('Sleep HDD now?',`Request standby now for ${d.name}, without waiting for the idle timer. The app checks active users, flushes pending writes and allows up to 15 seconds for disk activity to settle. Monitoring stays in its current state. Active applications or continuing disk I/O can prevent standby.`,async()=>{
     return await withAction(async()=>{try{const result=await runDriveAction(d,'sleep');closeModal();notify(result.message,result.error);return result;}catch(e){notify(operationError(e),true);throw e;}});
   });return;
 case 'toggle-mount':if(!d)return;{const mountAction=d.mounted?'unmount':'mount';
   let approval={},description=`${d.model} (${d.uuid}). The server checks open files, mounted images and the configured filesystem identity.`;
   if(mountAction==='unmount'){
     const plan=await apiRequest('unmount-plan?uuid='+encodeURIComponent(d.uuid),{drive:d.id});
     approval={token:plan.token,confirm:true};
     const running=plan.apps.filter(v=>v.running).map(v=>`${v.name} (${v.id.slice(0,12)})${v.images.length?' · images: '+v.images.join(', '):''}`);
     const stopped=plan.apps.filter(v=>!v.running).map(v=>v.name);
     description+=' '+(running.length?'Apps to stop: '+running.join('; ')+'.':'No configured dependent apps are running.')+(stopped.length?' Already stopped: '+stopped.join(', ')+'.':'')+' '+plan.message;
   }
   confirmAction(d.mounted?'Unmount drive safely?':'Mount the selected drive?',description,async()=>{return await withAction(async()=>{try{const result=await runDriveAction(d,mountAction,approval);closeModal();notify(result.message,result.error);return result;}catch(e){notify(operationError(e),true);throw e;}});},{singleUse:mountAction==='unmount'});return;}
 case 'reconnect-drive':if(!d)return;
   if(d.stale||d.mounted||!d.resetAvailable||!d.connected){notify('Unmount relevant storage and verify the current USB connection before reset.',true);return;}
   confirmAction('Reset USB in software?',`This is a guarded software reset or reconnect of ${d.name} (${d.uuid}). The disk will remain unmounted and monitoring is unchanged. Electrical power off/on is not verified, and a separate disk power supply is not controlled. The server checks open files and device identity before reconnecting. If any check fails, the action is refused.`,async()=>{return await withAction(async()=>{try{const result=await runDriveAction(d,'reconnect');closeModal();notify(result.message,result.error);return result;}catch(e){notify(operationError(e),true);throw e;}});},{danger:true});return;
 case 'mount-location':if(d)openMountLocation(d);return;
 case 'mount-location-preview':if(!d||mountLocationBlocked(d))return;{
   const loc=$('#modal-mount-path')?.value.trim();if(!loc||!loc.startsWith('/')||loc.includes('..')||/\s/.test(loc)){notify('Use an absolute folder path without whitespace or parent traversal.',true);return;}
   await withAction(async()=>{
     // Reuse the backend's exact reviewed proposal, token, and saved configuration revision.
     // Do not display a confirmation button unless the backend has accepted the review.
     const plan=await apiRequest('migration-plan?uuid='+encodeURIComponent(d.uuid)+'&mountpoint='+encodeURIComponent(loc),{drive:d.id});
     const config=await apiRequest('config',{drive:d.id});
     if(!plan.token||!config.revision)throw Error('The server could not verify this mount-location review. Nothing was changed.');
     const desc=plan.message||'The permanent mount entry will be updated. Files are not moved; dependent application paths may require separate review.';
     confirmAction('Apply mount location change?',`${d.name}: ${d.mount} → ${loc}. ${desc}`,async()=>{await withAction(async()=>{
       // The server rechecks the complete proposal, configuration revision, and explicit consent.
       const r=await apiRequest('change-mount-location',{drive:d.id,data:{uuid:d.uuid,mountpoint:loc,token:plan.token,revision:config.revision,confirm:true}});
       closeModal();notify(r.message||'Mount location updated.');await refreshFleet({display:false});await refreshDetail(d.id,{renderPage:true});});});
   });return;
 }
 case 'find-reformatted-drive':if(!d||!d.configured)return;
   await withAction(async()=>{
     const result=await apiRequest('drive-rebind-candidates',{drive:d.id});
     if(result.drives?.length!==1)throw Error(result.drives?.length?'Multiple matching devices found. Re-identification is not safe.':'No matching reformatted ext4 USB drive was found. The device must be connected and safely unmounted first.');
     await showRebindReview(d,result.drives[0].new_uuid);
   });return;
 case 'open-images':if(d){state.selectedImageDrive=d.id;state.imageTab='configured';navigate('images');}return;
 case 'open-drive-history':state.historyDrive=id;navigate('history');return;
 case 'image-tab':state.imageTab=value;state.selectedDiscovered='';render();return;
 case 'rescan-images':if(state.selectedImageDrive)await withAction(async()=>{await discoverImages(state.selectedImageDrive);notify('USB image search completed.');});return;
 case 'import-discovered':{
    const target=find(state.selectedImageDrive);const path=state.selectedDiscovered;
    const found=state.discoveredImages.find(x=>x.drive===target?.id&&x.path===path);
    if(!target||!found){notify('Select an existing image.',true);return;}
    await withAction(async()=>setupImagePlan(target,{mode:'existing',name:found.name.replace(/\.img$/i,''),image:found.path},context));return;
 }
 case 'import-by-path':{
    const target=find(state.selectedImageDrive);const image=$('#existing-image-path')?.value.trim(),name=$('#existing-image-name')?.value.trim();
    if(!target||!image||!name)throw Error('Enter a host image file path and a name.');
    await withAction(async()=>setupImagePlan(target,{mode:'existing',name,image},context));return;
 }
 case 'image-toggle-mount':{
   const im=imageRecord(d,value);if(!im)return;
   return await withAction(async()=>runImageMount(d,im,context));
 }
 case 'copy-image-folder':{const im=imageRecord(d,value);if(im)return await copy(im.folder);return;}
 case 'image-remove':{const im=imageRecord(d,value);if(!im)return;confirmAction('Remove virtual disk registration?',`Remove ${im.id} from USB Storage Watch? This keeps the .img file and all its contents.`,async()=>{return await withAction(async()=>{const r=await apiRequest('image-action',{drive:d.id,data:{uuid:im.uuid,action:'remove',confirm:true}});closeModal();const result=notify(r.message||'Registration removed.');imageResults.set(d.id,result);await loadImages(d.id);render();return result;});},{danger:true});return;}
 case 'format-review':await withAction(async()=>{
   const x=state.prepareDisks.find(x=>x.device===state.selectedPrepare);if(!x||x.reason)throw Error(x?.reason||'Choose an eligible USB disk.');
   const plan=await apiRequest('prepare-drive-plan',{data:{device:x.device,name:$('#prepared-name')?.value?.trim()||''}});
   modal(`<div class="modal-title">${icon('warning')}<h2 id="modal-title">Permanently erase this USB drive?</h2></div><div class="callout danger"><div><strong>ALL files on this drive will be permanently erased.</strong> This cannot be undone.</div></div><dl class="info-list"><dt>Drive</dt><dd>${esc(plan.model)}</dd><dt>Capacity</dt><dd>${readableSize(plan.size)}</dd><dt>Serial</dt><dd class="path">${esc(plan.serial)}</dd></dl><label class="checkline"><input id="erase-ack" type="checkbox">I understand that all data on this specific drive will be erased.</label>${field('Type '+plan.phrase+' to confirm','erase-phrase','','text','','autocomplete="off" spellcheck="false"')}<div class="modal-actions">${B('Cancel','close-modal',{class:'button-quiet'})}${B('Permanently erase drive','confirm-real-format',{class:'button-danger',disabled:true})}</div>`,'danger');
   state.pendingFormat=plan;
   const update=()=>{const btn=$('[data-action="confirm-real-format"]');if(btn)btn.disabled=!$('#erase-ack').checked||$('#erase-phrase').value!==plan.phrase;};
   $('#erase-ack').addEventListener('change',update);$('#erase-phrase').addEventListener('input',update);
 });return;
 case 'confirm-real-format':{
   const plan=state.pendingFormat;if(!plan||!$('#erase-ack').checked||$('#erase-phrase').value!==plan.phrase)return;
   if(modalPending||!modalWorking('Preparing the selected disk. The operation cannot be cancelled once accepted…'))return;
   try{await withAction(async()=>{
     const result=await apiRequest('prepare-drive',{data:{token:plan.token,confirmation:plan.phrase,erase:true}});
     state.pendingFormat=null;closeModal();notify('Formatting accepted. Do not disconnect the selected drive.');await refreshPrepare();
     if(result?.operation){state.prepareOperation=result.operation;await waitFormat(result.operation);}
   });}finally{modalWorkFinished();}return;
 }
 case 'test-email':confirmAction('Send a test email?',`USB Storage Watch will contact the configured SMTP server and send to the saved recipient.`,async()=>{await withAction(async()=>{const r=await apiRequest('test-email',{data:{}});closeModal();notify((r.accepted?'SMTP accepted test message: ':'Test email not accepted: ')+(r.message||''),!r.accepted);});});return;
 case 'copy-token-command':return await copy('sudo cat /var/lib/usb-storage-watch/management.token');
 case 'rotate-token':
   confirmAction('Replace management token?', 'The host generates a new token. Every existing dashboard session and previous management token will be invalidated. Retrieve the replacement from the host using sudo cat /var/lib/usb-storage-watch/management.token. Companion must also be updated with the replacement token.',async()=>{
     await withAction(async()=>{
       await apiRequest('management-token',{data:{confirm:true}});
       closeModal();showLogin('Token replaced. Retrieve the new token on the host computer using the command shown below, then connect again.');
     });
   },{danger:true});return;
 case 'copy-lan':return await copy(state.lanSecure+'://'+state.lanAddress+':8765');
 case 'apply-network-security':{
   const requested=state.lanDraftSecure||state.lanSecure;
   if(requested===state.lanSecure){notify('Connection type is already active.');return;}
   const note=requested==='http'?
     'HTTP does not encrypt login tokens or commands. Use only on a trusted private network or encrypted VPN. Never forward this port to the public internet.':
     'Switch to HTTPS. Browsers on other devices may need the trusted local certificate. Changing the network protocol may interrupt the current remote page.';
   confirmAction('Apply network security?',note,async()=>{
     await withAction(async()=>{
       const selected=state.lan;
       const data=selected?
         {enabled:true,confirm:true,address:state.lanAddress,scheme:requested,...(requested==='http'?{acknowledge_http:true}:{})}:
         {enabled:false,confirm:true,scheme:requested};
       await changeLan(selected?'lan-auto':'network',data);
     });
   },{danger:requested==='http'});
   return;
 }
 case 'timings-save':await saveSettings(id,'timings');return;
 case 'stepper-adjust':{const el=$(`[data-timing="${id}"]`);if(!el)return;el.value=String(Math.min(+el.max,Math.max(+el.min,(+el.value||+el.min)+Number(value))));captureSettings(el);return;}
 case 'stepper-reset':{const el=$(`[data-timing="${id}"]`);if(el){el.value=String({check:15,confirm:2,recovery:60,returntimeout:5,usbwait:20,sleep:30}[id]);captureSettings(el);}return;}
 case 'integration-copy-url':{
   // Recheck active settings before copying; never use a URL from an old render.
   await loadIntegrationData();
   if(networkView.readError)throw Error(networkView.readError);
   const url=networkView.saved?.lan?networkView.url:networkView.localUrl;
   if(!url)throw Error('No verified server URL is available. Check Network settings.');
   return await copy(url);
 }
 case 'integration-copy-ca':{
   await loadIntegrationData();
   if(!state.integrationInfo?.certificate_pem)throw Error('Public CA certificate unavailable. Check HTTPS setup.');
   return await copy(state.integrationInfo.certificate_pem);
 }
 default:notify('This operation is not yet available in the integrated interface. No change was made.',true);return;
 }
 }catch(e){throw e;}
}
async function waitFormat(operation){
 let done=false;
 for(let attempt=0;attempt<80;attempt++){
   await new Promise(resolve=>setTimeout(resolve,2000));
   try{const result=await apiRequest('prepare-progress?operation='+encodeURIComponent(operation));
     state.prepareOperations=[result];render();
     if(['ready','failed'].includes(result.phase)){
       toast(result.message||'Formatting complete.',result.phase==='failed');done=true;
       if(result.phase==='ready' && result.uuid){
         // Formatting can replace the filesystem of previously monitored USB
         // hardware. Offer a verified in-app profile reconnect, never a shell script.
         try{
           await refreshFleet({display:false});render();
           for(const previous of configured().filter(d=>d.connected===false)){
             const matching=await apiRequest('drive-rebind-candidates',{drive:previous.id});
             if(matching.drives?.some(x=>x.new_uuid===result.uuid)){
               await showRebindReview(previous,result.uuid);break;
             }
           }
         }catch(_){/* A failed discovery never affects successful formatting. */}
       }
       break;
     }
   }catch(err){toast(errorMessage(err),true);break;}
 }
 if(!done)toast('Formatting status is not final. Check Prepare Drive before starting any other operation.',true);
}
function openAddDrive(){const options=state.drives.filter(d=>!d.configured&&d.connected===true);modal(`<div class="modal-title">${icon('plus')}<h2 id="modal-title">Add USB drive</h2></div><p>Choose a detected supported ext4 USB drive. Existing monitors stay active.</p>${options.map(d=>`<div class="selection-row"><span><strong class="title">${driveName(d)} · ${esc(d.size)}</strong><span class="desc">${esc(d.uuid)}${d.error?' · '+esc(d.error):''}</span></span>${B('Add drive','add-detected',{id:d.id,class:'button-add',disabled:d.error||!d.uuid})}</div>`).join('')||'<div class="empty">No additional eligible ext4 USB filesystems were found.</div>'}<div class="modal-actions">${B('Close','close-modal',{class:'button-neutral'})}</div>`);}
async function handleToggle(el,context=null){
 if(el.dataset.toggle==='image-recovery'){
   const d=find(el.dataset.id),im=d?.images.find(x=>x.uuid===el.dataset.key);if(!im)return;
   queueImagePreference(d,im,el.checked);return;
 }
 if(el.dataset.toggle==='drive-setting'){
   const d=find(el.dataset.id),key=el.dataset.key;if(!d)return;
   if(key==='recovery'){el.checked=d.recovery;return await withAction(async()=>setRecovery(d,!d.recovery,context));}
   if(key==='notifications')return await setNotifications(d,el.checked,el);
 }else if(el.dataset.toggle==='lan'){
   const next=el.checked;el.checked=state.lan;
   confirmAction(next?'Enable LAN access?':'Disable LAN access?',next?`LAN access will be enabled on a private host address. Do not forward port 8765 from your router.`:'Remote LAN access will be disabled; localhost access remains available.',async()=>{
     await withAction(async()=>{
       let address=state.lanAddress;
       if(next){const info=await apiRequest('lan-info');address=(info.addresses||[]).some(a=>a.address===address)?address:info.addresses?.[0]?.address;if(!address)throw Error('No private LAN address is available.');}
       const data=next?{enabled:true,confirm:true,address,scheme:state.lanSecure, ...(state.lanSecure==='http'?{acknowledge_http:true}:{})}:{enabled:false,confirm:true};
       await changeLan('lan-auto',data);
     });
   });
 }
}
const imagePreferences=new Map();
const imagePreferenceFeedback=new Map();
let preferenceTimer=null,preferencesSaving=false;
const preferenceKey=(drive,uuid)=>drive+':'+uuid;
function imagePreferenceStatus(d,im){
 const pending=imagePreferences.get(preferenceKey(d.id,im.uuid));
 return pending?'Saving…':im.preferenceMessage||'';
}
function updateImagePreference(d,im,message='',error=false){
 im.preferenceMessage=message;im.preferenceError=error;
 imagePreferenceFeedback.set(preferenceKey(d.id,im.uuid),{message,error});
 const cached=detailCache.get(d.id)?.images?.images?.find(x=>x.uuid===im.uuid);
 if(cached)cached.enabled=im.autoRestore;
 $$('[data-toggle="image-recovery"]').forEach(el=>{
   if(el.dataset.id!==d.id||el.dataset.key!==im.uuid)return;
   el.checked=im.autoRestore;
   const status=el.closest('.toggle-row')?.querySelector('.preference-status');
   if(status){status.textContent=message;status.classList.toggle('error',error);}
 });
}
function queueImagePreference(d,im,desired){
 const key=preferenceKey(d.id,im.uuid);
 const pending=imagePreferences.get(key)||{drive:d.id,uuid:im.uuid,confirmed:im.autoRestore};
 pending.desired=desired;imagePreferences.set(key,pending);
 im.autoRestore=desired;updateImagePreference(d,im,'Saving…');
 clearTimeout(preferenceTimer);preferenceTimer=setTimeout(flushImagePreferences,120);
}
async function flushImagePreferences(){
 if(preferencesSaving||!imagePreferences.size)return;
 if(apiBusy){preferenceTimer=setTimeout(flushImagePreferences,120);return;}
 preferencesSaving=true;apiBusy=true;
 try{
   for(const [key,pending] of imagePreferences){
     try{
       // Send absolute preferences one at a time; a later tap replaces the
       // queued value. Never retry a failed or interrupted write automatically.
       while(pending.desired!==pending.confirmed){
         const sent=pending.desired;
         await apiRequest('image-action',{drive:pending.drive,data:{uuid:pending.uuid,action:'set-recovery',enabled:sent}});
         pending.confirmed=sent;
       }
       imagePreferences.delete(key);
       const d=find(pending.drive),im=d?.images.find(x=>x.uuid===pending.uuid);
       if(im){im.autoRestore=pending.confirmed;updateImagePreference(d,im,'Saved');}
     }catch(e){
       imagePreferences.delete(key);
       let confirmed=pending.confirmed,verified=false;
       try{
         const current=await apiRequest('application-images',{drive:pending.drive});
         const image=current.images?.find(x=>x.uuid===pending.uuid);
         if(image){confirmed=image.enabled!==false;verified=true;}
       }catch(_){}
       const d=find(pending.drive),im=d?.images.find(x=>x.uuid===pending.uuid);
       if(im){im.autoRestore=confirmed;updateImagePreference(d,im,verified?'Save failed; showing current setting.':'Save unconfirmed. Refresh before trying again.',true);}
       toast('Mount on recovery could not be saved. '+errorMessage(e),true);
     }
   }
 }finally{apiBusy=false;preferencesSaving=false;}
}
function handleChange(el){if(el.matches(':disabled')||appBlocked(el.dataset.container))return;const key=el.dataset.change;
 switch(key){
 case 'image-drive':state.selectedImageDrive=el.value;state.selectedDiscovered='';render();withAction(async()=>{await loadImages(el.value);render();}).catch(e=>toast(operationError(e),true));return;
 case 'select-discovered':state.selectedDiscovered=el.value;render();return;
 case 'entry-target':{const v=dockerView(el.dataset.container);v.entryTarget=el.value;v.entryPlan=null;refreshDockerDOM();return;}
 case 'app-enabled':case 'app-drive':case 'app-image':editAppChoice(el);return;
 case 'prepare-selection':state.selectedPrepare=el.value;render();return;
 case 'history-filter':state.historyDrive=el.value;render();return;
 case 'advanced-drive':state.advancedDrive=el.value;render();withAction(async()=>refreshDetail(el.value)).catch(e=>toast(operationError(e),true));return;
 case 'network-security':{
   state.lanDraftSecure=el.value;const button=$('[data-action="apply-network-security"]');if(button)button.disabled=el.value===state.lanSecure;
   return;
 }
 }
}
async function submit(form,context=null){const kind=form.dataset.form;
 if(kind==='image-create'){
   const target=find(state.selectedImageDrive),name=$('#new-image-name')?.value.trim(),size=Number($('#new-image-capacity')?.value),access=$('#new-image-access')?.value;
   if(!target||!IMAGE_NAME.test(name||''))throw Error('Choose a valid image name.');
   if(!Number.isFinite(size)||size<0.125)throw Error('Choose a valid capacity.');
   return await withAction(async()=>setupImagePlan(target,{mode:'create',name,size_gb:size,permissions:{kind:access==='applications'?'applications':'user'}},context));
 }else if(kind==='standby-settings'){
   await saveSettings(form.dataset.id,'standby');
 }else if(kind==='email-save'){
   await withAction(async()=>{
     const get=id=>$('#'+id)?.value||'';
     const data={host:get('smtp-server'),port:Number(get('smtp-port')),security:get('smtp-security'),username:get('smtp-user'),sender:get('smtp-from'),recipient:get('smtp-to'),password:get('smtp-password')};
     const result=await apiRequest('smtp',{data});toast(result.message||'SMTP settings saved.');await refreshSmtp();
   });
 }
}
function mountLocationBlocked(d){return d.mounted||d.otherMount||d.mountTargetOccupied||d.stale||d.busy||['conflict','unavailable'].includes(d.mountState);}
function mountLocationHint(d){return d.mountState==='conflict'?'Resolve the mount conflict before changing the mount location.':d.mountState==='unavailable'?'Mount status must be verified before changing the mount location.':'Unmount the drive before changing its mount location.';}
function currentMountText(d){return d.mountState==='conflict'?'Mount conflict — see details below':d.mountState==='unavailable'?'Mount status unavailable':d.mounted?d.mount:d.otherMount?(d.mountLocations?.join(', ')||'Mounted elsewhere'):'Not mounted';}
function deliberateStopNotice(d){return d.deliberateStopped?.length&&!d.stale&&!d.busy&&d.mounted&&d.mountState==='mounted'?`<p class="callout warn deliberate-stop-notice" role="status"><span>Drive ready. Apps remain stopped after safe unmount. Start them from <a href="#apps">Docker Apps</a> when you’re ready.</span></p>`:'';}
function mountStateNotice(d){return ['conflict','unavailable'].includes(d.mountState)?`<div class="callout ${d.mountState==='conflict'?'danger':'warn'} mount-state-notice">${icon('warning')}<div><strong>${d.mountState==='conflict'?'The configured mount is blocked':'Mount status could not be verified'}</strong><p>${esc(d.mountDetail||'Refresh the drive status for more information.')}</p></div></div>`:'';}
function driveStatus(d){
 const connected=d.connected===null?'Connection unknown':d.connected?'Connected':'Disconnected';
 const mounted=d.stale?'Mount status pending':d.mountState==='conflict'?'Mount conflict':d.mountState==='unavailable'?'Mount status unavailable':d.mounted?'Mounted':d.otherMount?'Mounted elsewhere':'Unmounted';
 const monitoring=d.monitoringUnknown||d.stale?'Monitoring status pending':d.monitoring?'Monitoring on':'Monitoring off';
 return chip(connected,d.connected===null?'muted':d.connected?'good':'bad')+chip(mounted,d.stale||d.mountState==='unavailable'?'muted':d.mountState==='conflict'?'bad':d.mounted?'good':'warn')+chip(monitoring,d.stale||d.monitoringUnknown?'muted':d.monitoring?'good':'bad')+chip(d.recovery?'Recovery enabled':'Recovery disabled',d.recovery?'good':'muted');
}
function driveCard(d){return `<article class="card" data-drive-card="${attr(d.id)}"><div class="card-header"><div class="device-identity">${driveIcon(d)}<div><h2>${driveName(d)} <span class="muted">· ${esc(d.size)}</span></h2><p>${esc(d.model)} · ${d.kind==='flash'?'USB flash drive':d.kind==='hdd'?'Mechanical HDD':d.kind==='ssd'?'Solid-state drive':'Storage device'}</p></div></div>${chip(d.monitoringUnknown||d.stale?'Status pending':d.monitoring?'Monitoring':'Not monitoring',d.stale?'muted':d.monitoring?'good':'bad')}</div><div class="labelrow">${driveStatus(d)}${standbyBadge(d)}</div><dl class="info-list"><dt>Mount location</dt><dd class="path">${esc(d.mount)}</dd><dt>Last observation</dt><dd>${esc(d.lastSeen)}</dd></dl>${mountStateNotice(d)}${deliberateStopNotice(d)}${driveRecoveryMarkup(activeDriveRecovery(d))}${d.error?`<div class="callout warn">${esc(d.error)}</div>`:''}${d.connected===false?`<div class="callout warn">${B('Find reformatted drive','find-reformatted-drive',{id:d.id,class:'button-neutral'})} Reconnect this drive's saved settings if its filesystem was replaced.</div>`:''}<div class="drive-card-actions"><div class="actions drive-primary-actions">${B('Manage drive','manage-drive',{class:'button-primary',id:d.id})}${B(d.monitoring?'Stop monitoring':'Start monitoring','toggle-monitoring',{class:d.monitoring?'button-warning':'button-start',id:d.id,disabled:d.stale||d.busy||d.monitoringUnknown})}</div><div class="drive-remove-action">${B('Remove from Storage Watch','remove-drive-review',{class:'button-remove',id:d.id,disabled:d.busy})}</div></div></article>`;}
function configuredImages(d){return imageResultMarkup(d)+(d.images.length?`<div class="stack">${d.images.map(im=>`<article class="helper-panel"><div class="section-heading"><div><h3>${esc(im.id)}</h3><p>${im.size} GiB · ${im.mounted?'Mounted':'Unmounted'} · ${esc(im.access)}</p></div>${chip(im.mounted?'Mounted':'Unmounted',im.mounted?'good':'warn')}</div><dl class="info-list compact"><dt>Image file</dt><dd class="path">${esc(im.path)}</dd><dt>Accessible folder</dt><dd class="path">${esc(im.folder)}</dd></dl><div class="toggle-row image-recovery-switch"><div class="toggle-copy"><strong>Mount on recovery</strong><p>Restore this image after USB drive recovery. The current mount remains unchanged. Manual mount and unmount leave this preference unchanged.</p><span class="preference-status ${im.preferenceError?'error':''}" role="status">${esc(imagePreferenceStatus(d,im))}</span></div><input type="checkbox" class="toggle" role="switch" data-toggle="image-recovery" data-id="${attr(d.id)}" data-key="${attr(im.uuid)}" aria-label="Mount on recovery for ${attr(im.id)}" ${im.autoRestore?'checked':''}></div><div class="drive-card-actions image-card-actions"><div class="actions drive-primary-actions">${B(im.mounted?'Unmount image':'Mount image','image-toggle-mount',{id:d.id,value:im.id})}${B('Copy folder location','copy-image-folder',{id:d.id,value:im.id,class:'button-neutral',icon:'copy'})}</div><div class="drive-remove-action">${B('Remove from Storage Watch','image-remove',{id:d.id,value:im.id,class:'button-remove'})}</div></div></article>`).join('')}</div>`:'<div class="empty"><strong>No virtual disks configured</strong><p>Create or import one using the tabs above.</p></div>');}
async function initLive(){
 try{
   const auth=await apiRequest('session');csrfToken=auth.csrf;showApp();
   await refreshFleet({display:false});render();await loadForRoute();
 }catch(e){showLogin();}
}
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-action]');if(!button||button.matches(':disabled'))return;
 if(modalPending&&button.closest('#modal-root')){event.preventDefault();return;}
 event.preventDefault();runButtonAction(button,context=>act(button.dataset.action,button.dataset.id,button.dataset.value,context));
});
document.addEventListener('change',event=>{
 if(event.target.matches('[data-network-input]'))editNetwork(event.target);
 if(event.target.matches('[data-toggle]'))runButtonAction(event.target,context=>handleToggle(event.target,context));
 if(event.target.matches('[data-change]'))handleChange(event.target);
 if(event.target.matches('[data-timing],#standby-auto'))captureSettings(event.target);
});
document.addEventListener('input',event=>{if(event.target.matches('[data-network-input]'))editNetwork(event.target);if(event.target.matches('[data-timing],#standby-auto'))captureSettings(event.target);});
document.addEventListener('submit',event=>{
 if(!event.target.matches('[data-form]'))return;event.preventDefault();const button=event.submitter||event.target.querySelector('[type=submit]');runButtonAction(button,context=>submit(event.target,context));
});
$('#usw-login-form').addEventListener('submit',async event=>{
 event.preventDefault();const token=$('#usw-login-token').value,button=event.submitter||$('#usw-login-form button');
 await runButtonAction(button,async()=>{
 try{
   await apiRequest('login',{data:{management_token:token}});
   const session=await apiRequest('session');csrfToken=session.csrf;showApp();
   await refreshFleet({display:false});render();await loadForRoute();
 }catch(e){$('#usw-login-error').textContent=errorMessage(e);throw e;}
 });
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(modalPending)return;if($('#modal-root').children.length)closeModal();else closeMenu();}});
$('#mobile-backdrop').addEventListener('click',closeMenu);
window.addEventListener('hashchange',()=>{render();loadForRoute();window.scrollTo({top:0,behavior:'instant'});});
// One read cycle at a time. Never replace editable forms or open dialogs.
let pollPending=false;
async function pollLive(){
 const current=route(),session=csrfToken;
 if(!csrfToken||apiBusy||pollPending||routeLoading||(current!=='apps'&&($('#modal-root').children.length||document.querySelector('.touch-options'))))return;
 if(current!=='overview'&&current!=='history'&&current!=='apps'&&!current.startsWith('drive/'))return;
 pollPending=true;
 const canDisplay=()=>csrfToken===session&&route()===current&&!apiBusy&&!$('#modal-root').children.length;
 try{
   if(current==='apps'){
     await loadApplications({background:true});
   }else if(current==='overview'){
     await refreshFleet({display:false});if(canDisplay())render();
   }else if(current==='history'){
     await refreshHistory({display:false});if(canDisplay())updateEventRegions();
   }else{
     const id=current.split('/')[1];
     const results=await Promise.allSettled([apiRequest('status',{drive:id}),refreshHistory({display:false})]);
     if(!canDisplay())return;
     const d=find(id);
     if(d){
       if(results[0].status==='fulfilled'){
         const status=results[0].value;detailCache.set(id,{...detailCache.get(id),status});
         enrichDrive(d,{status});d.stale=false;
       }else{d.stale=true;}
       updateDriveSummary(d);
     }
     if(results[1].status==='fulfilled')updateEventRegions();
   }
 }catch(_){
   if(canDisplay()){
     state.drives.forEach(d=>{d.stale=true;});state.lastRefresh='Host unavailable — showing previous observations';render();
   }
 }finally{pollPending=false;}
}
function updateDriveSummary(d){
 const old=$('#drive-summary');if(!old)return;
 const fragment=document.createElement('template');fragment.innerHTML=driveManage(d);
 const next=fragment.content.querySelector('#drive-summary');
 const focused=document.activeElement?.closest('[data-action]'), action=old.contains(focused)?focused.dataset.action:null;
 old.replaceWith(next);
 if(action)Array.from(next.querySelectorAll('[data-action]')).find(el=>el.dataset.action===action)?.focus({preventScroll:true});
}
setInterval(pollLive,15000);
function initializeStaticFeedback(){
 for(const button of [$('#usw-login-form button'),...$$('#usw-login [data-action],.topbar [data-action="sign-out"],#usw-app [data-action="sign-out"]')]){
   if(!button||button.closest('.action-control'))continue;
   const key=feedbackKey(button.dataset.action||'login','','','shell');button.dataset.feedbackKey=key;button.dataset.feedbackLabel=button.textContent.trim();button.dataset.baseDisabled=String(button.disabled);
   const wrapper=document.createElement('span');wrapper.className='action-control';button.before(wrapper);wrapper.append(button);wrapper.insertAdjacentHTML('beforeend',feedbackMarkup(key,button.textContent.trim()));
 }
}
initializeStaticFeedback();
initLive();

// Every select uses the same touch picker, including selects inside dialogs.
// The native select is retained only as the form value and change-event source.
let activeTouchSelect=null,touchSelectSequence=0,touchRenderPending=false;
function closeTouchSelect(focus=false){
 if(!activeTouchSelect)return;
 const {button,panel}=activeTouchSelect;activeTouchSelect=null;
 panel.close();panel.remove();document.documentElement.classList.remove('picker-open');
 button.setAttribute('aria-expanded','false');
 if(focus&&button.isConnected)button.focus({preventScroll:true});
 if(touchRenderPending)queueMicrotask(()=>{if(touchRenderPending){touchRenderPending=false;render();}});
 if(networkView.renderPending)queueMicrotask(()=>{if(networkView.renderPending){networkView.renderPending=false;renderNetwork();}});
}
function selectOptionCopy(select,option){
 if(!option)return {title:'Choose an option',description:''};
 if(option.dataset.title)return {title:option.dataset.title,description:option.dataset.description||''};
 const d=find(option.value);
 if(d&&/drive|filter/.test(select.id))return {title:d.name,description:[d.size,d.kind==='hdd'?'Mechanical HDD':d.kind==='ssd'?'Solid-state drive':'USB storage device'].filter(Boolean).join(' · ')};
 return {title:option.textContent,description:option.dataset.description||''};
}
function selectPickerTitle(select){
 if(select.dataset.pickerTitle)return select.dataset.pickerTitle;
 if(/drive/.test(select.id))return 'Choose a drive';
 if(select.id==='history-filter')return 'Choose event history';
 if(select.id==='new-image-access')return 'Choose folder access';
 if(select.id==='smtp-security')return 'Choose email security';
 if(select.id.startsWith('application-bind-'))return 'Choose an access-check folder';
 return 'Choose an option';
}
function pickerCopyNode(copy){const span=document.createElement('span'),strong=document.createElement('strong');strong.textContent=copy.title;span.append(strong);if(copy.description){const small=document.createElement('small');small.textContent=copy.description;span.append(small);}return span;}
function syncTouchSelects(root=document){
 root.querySelectorAll('.touch-select').forEach(wrapper=>{
   const select=wrapper.querySelector('select'),button=wrapper.querySelector('.touch-trigger');
   button.disabled=select.matches(':disabled');
   button.querySelector('.touch-value').replaceChildren(pickerCopyNode(selectOptionCopy(select,select.selectedOptions[0])));
 });
}
function enhanceSelects(root=document){
 root.querySelectorAll('select:not([data-touch-select])').forEach(select=>{
   if(select.multiple)return;
   select.dataset.touchSelect='true';select.id||='touch-select-'+(++touchSelectSequence);
   const wrapper=document.createElement('div');wrapper.className='touch-select';select.before(wrapper);wrapper.append(select);
   select.hidden=true;select.tabIndex=-1;select.setAttribute('aria-hidden','true');
   const button=document.createElement('button');button.type='button';button.className='touch-trigger picker-trigger';button.id=select.id+'-control';
   button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',select.id+'-picker');
   const labels=Array.from(select.labels||[]);
   if(labels.length){labels.forEach((label,i)=>{label.id||=select.id+'-label-'+i;label.addEventListener('click',event=>{event.preventDefault();button.focus();});});button.setAttribute('aria-labelledby',labels.map(l=>l.id).join(' '));}
   else button.setAttribute('aria-label',select.getAttribute('aria-label')||selectPickerTitle(select));
   button.innerHTML='<span class="touch-value"></span><span class="picker-mark" aria-hidden="true">⌄</span>';wrapper.append(button);
   const open=()=>{
     if(button.disabled||select.matches(':disabled'))return;
     if(activeTouchSelect?.button===button){closeTouchSelect(true);return;}
     closeTouchSelect();
     const dialog=document.createElement('dialog');dialog.className='touch-picker';dialog.id=select.id+'-picker';dialog.setAttribute('aria-labelledby',select.id+'-picker-title');
     const head=document.createElement('div');head.className='picker-heading';
     const title=document.createElement('div');if(select.dataset.pickerEyebrow){const eyebrow=document.createElement('span');eyebrow.className='eyebrow';eyebrow.textContent=select.dataset.pickerEyebrow;title.append(eyebrow);}
     const h=document.createElement('h2');h.id=select.id+'-picker-title';h.textContent=selectPickerTitle(select);title.append(h);
     const close=document.createElement('button');close.type='button';close.className='picker-close';close.setAttribute('aria-label','Close picker');close.textContent='×';close.addEventListener('click',()=>closeTouchSelect(true));
     head.append(title,close);dialog.append(head);
     if(select.dataset.pickerDescription){const intro=document.createElement('p');intro.textContent=select.dataset.pickerDescription;dialog.append(intro);}
     const list=document.createElement('div');list.className='picker-list touch-options';list.setAttribute('role','listbox');list.setAttribute('aria-label',h.textContent);dialog.append(list);
     const rows=[];
     Array.from(select.options).forEach(option=>{
       const row=document.createElement('button');row.type='button';row.className='picker-option touch-option';row.setAttribute('role','option');row.setAttribute('aria-selected',String(option.selected));row.setAttribute('aria-current',String(option.selected));
       row.disabled=option.disabled||option.parentElement?.disabled===true;
       row.append(pickerCopyNode(selectOptionCopy(select,option)));
       const mark=document.createElement('span');mark.className='picker-mark';mark.setAttribute('aria-hidden','true');mark.textContent=option.selected?'✓':'›';row.append(mark);
       row.addEventListener('click',()=>{
         if(select.matches(':disabled')||!select.isConnected)return;
         select.value=option.value;syncTouchSelects(wrapper.parentElement);closeTouchSelect();select.dispatchEvent(new Event('change',{bubbles:true}));
         document.getElementById(select.id+'-control')?.focus({preventScroll:true});
       });list.append(row);if(!row.disabled)rows.push(row);
     });
     if(!rows.length){const empty=document.createElement('p');empty.textContent='No options are available. Close this picker and refresh the page.';list.append(empty);}
     if(select.dataset.pickerFooter){const footer=document.createElement('p');footer.className='picker-footer';footer.textContent=select.dataset.pickerFooter;dialog.append(footer);}
     let buffer='',lastKey=0;
     dialog.addEventListener('keydown',event=>{
       if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeTouchSelect(true);return;}
       if(event.key==='Tab'){
         const targets=[close,...rows],first=targets[0],last=targets[targets.length-1];
         if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
         else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
         return;
       }
       if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
         event.preventDefault();let index=rows.indexOf(document.activeElement);
         index=event.key==='Home'?0:event.key==='End'?rows.length-1:(index+(event.key==='ArrowDown'?1:-1)+rows.length)%rows.length;rows[index]?.focus();return;
       }
       if(event.key.length===1&&!event.ctrlKey&&!event.altKey&&event.key!==' '){
         const now=Date.now();buffer=(now-lastKey<700?buffer:'')+event.key.toLowerCase();lastKey=now;
         const match=rows.find(row=>row.textContent.toLowerCase().startsWith(buffer));if(match){event.preventDefault();match.focus();}
       }
     });
     dialog.addEventListener('cancel',event=>{event.preventDefault();closeTouchSelect(true);});
     dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeTouchSelect(true);});
     document.body.append(dialog);activeTouchSelect={button,panel:dialog,route:route()};button.setAttribute('aria-expanded','true');document.documentElement.classList.add('picker-open');dialog.showModal();
     const selected=rows.find(row=>row.getAttribute('aria-selected')==='true');
     if(selected){const offset=selected.getBoundingClientRect().top-list.getBoundingClientRect().top;list.scrollTo({top:Math.max(0,offset-list.clientHeight/2+selected.offsetHeight/2),behavior:'instant'});}
     (selected||rows[0]||close).focus({preventScroll:true});
   };
   button.addEventListener('click',open);
   button.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();open();if(event.key==='End')activeTouchSelect?.panel.querySelector('.touch-option:last-child')?.focus();}});
   select.addEventListener('change',()=>syncTouchSelects(wrapper.parentElement));
 });
 syncTouchSelects(root);
}
