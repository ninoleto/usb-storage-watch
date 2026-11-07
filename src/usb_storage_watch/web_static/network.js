/* SPDX-License-Identifier: MIT
 * Network layout and certificate walkthrough adapted from RF433 Button Manager
 * 0.4.0-test.5, Copyright (c) 2026 Nino Milin. See THIRD-PARTY-NOTICES.md.
 * Saved listeners remain active until the proposed origin confirms the change.
 */
'use strict';
const networkDefaults={lan:false,address:'127.0.0.1',address_mode:'manual',scheme:'http',http_port:8765,https_port:8766};
const initialNetwork=()=>({loaded:false,saved:null,draft:null,addresses:[],transaction:{phase:'idle'},certificate:{available:false},listener:{phase:'checking',message:'Checking the network listener.'},replaceTrust:false,busy:false,error:'',readError:'',message:''});
let networkView=initialNetwork(),networkReading=false;
function resetNetwork(){networkView=initialNetwork();}
const networkActive=()=>['preparing','pending','committing','cancelling'].includes(networkView.transaction.phase);
const networkValues=c=>Object.fromEntries(Object.keys(networkDefaults).map(k=>[k,c?.[k]??networkDefaults[k]]));
const networkKey=c=>JSON.stringify([c?.lan,c?.address_mode||'manual',!c?.lan||c?.address_mode==='automatic'?'':c?.address,c?.lan?c.scheme:'http',Number(c?.http_port),Number(c?.https_port)]);
const networkDirty=()=>networkView.loaded&&networkKey(networkView.draft)!==networkKey(networkValues(networkView.saved));
function networkValidation(){
 const d=networkView.draft;if(!d)return '';
 for(const [key,label] of [['http_port','HTTP / localhost'],['https_port','Network HTTPS']]){
   if(!/^\d+$/.test(String(d[key]))||!Number.isInteger(Number(d[key]))||Number(d[key])<1024||Number(d[key])>65535)
     return `${label} port: enter a whole number from 1024 to 65535, or use Reset.`;
 }
 if(d.lan&&d.address_mode!=='automatic'&&!networkView.addresses.some(a=>a.address===d.address&&a.available!==false))return 'Choose an available address assigned to this server, or switch to Automatic.';
 if(networkTrustChange()&&!networkView.replaceTrust)return 'Review and acknowledge the HTTPS trust replacement below before applying.';
 return '';
}
// Certificate creation is part of Apply/Download, never an unexplained disabled prerequisite.
function networkCanApply(){return networkDirty()&&!networkValidation()&&!networkActive()&&!networkView.busy&&!networkView.recoveryError;}
function networkSelectedAddress(){return networkView.draft?.address_mode==='automatic'?networkView.addresses.find(a=>a.automatic)?.address:networkView.draft?.address;}
function networkNeedsCertificate(){const v=networkView;return v.draft?.lan&&v.draft.scheme==='https'&&!(v.saved?.lan&&v.saved.scheme==='https'&&v.saved.address===networkSelectedAddress()&&Number(v.saved.https_port)===Number(v.draft.https_port));}
function networkTrustChange(){return networkNeedsCertificate()&&networkView.certificate.replacement_required;}
function networkRemaining(){return Math.max(0,Math.ceil((networkView.transaction.seconds_left||0)-(performance.now()-(networkView.observedAt??performance.now()))/1000));}
function networkMessage(){
 const v=networkView;if(v.busy)return v.message||'Sending request…';
 if(v.recoveryError)return v.recoveryError;
 if(v.error)return v.error;
 if(networkActive()||['failed','expired','cancelled'].includes(v.transaction.phase))return v.transaction.message;
 if(networkValidation())return networkValidation();
 if(networkDirty())return 'Unsaved changes. Apply, open the proposed address, then confirm there within 3 minutes. Without confirmation, your current settings stay in place.';
 return v.readError||v.message||(['failed','expired','cancelled'].includes(v.transaction.phase)?v.transaction.message:'')||(v.listener?.phase!=='ready'?v.listener?.message:'')||v.transaction.message||v.listener?.message||'Current settings saved. Changes here affect this app only.';
}
function networkUrlCard(title,url,description,unavailable='Local network access is disabled.'){return `<section class="network-url"><h3>${esc(title)}</h3><p>${esc(description)}</p><div class="network-url-line"><code>${esc(url||unavailable)}</code>${url?B('Copy URL','network-copy',{value:url,class:'button-neutral'}):''}</div></section>`;}
function networkPort(key,label,reset){const d=networkView.draft;return `<div class="field"><label for="network-${key}">${esc(label)}</label><div class="network-port-stepper"><button type="button" class="button button-neutral" data-action="network-step" data-id="${key}" data-value="-1" aria-label="Decrease ${esc(label)}">−</button><input type="number" inputmode="numeric" id="network-${key}" data-network-input="${key}" value="${attr(d[key])}" min="1024" max="65535" step="1" required aria-describedby="network-message"><button type="button" class="button button-neutral" data-action="network-step" data-id="${key}" data-value="1" aria-label="Increase ${esc(label)}">+</button>${B('Reset to '+reset,'network-step',{id:key,value:String(reset),class:'button-neutral port-reset'})}</div></div>`;}
function networkAddressDescription(a){return `${a.interface} · ${a.automatic?'Physical connection':a.advanced?'Virtual / VPN — Manual selection only':'Network interface'}${a.default_route?' · default route, metric '+a.metric:''}`;}
function networkAddressField(){
 const v=networkView,d=v.draft,options=v.addresses.map(a=>a.available===false?{...a,unavailable:true,interface:'Unavailable — '+a.interface}:a),automatic=d.address_mode==='automatic',selected=options.find(a=>a.automatic);
 if(!options.some(a=>a.address===d.address))options.unshift({address:d.address,interface:'Unavailable — choose an assigned address',unavailable:true});
 return `<div class="field network-address" ${!d.lan?'hidden':''}><div class="network-protocols" role="radiogroup" aria-label="Address selection mode">${['automatic','manual'].map(mode=>`<label class="network-protocol ${d.address_mode===mode?'selected':''}"><input type="radio" name="network-address-mode" data-network-input="address_mode" value="${mode}" ${d.address_mode===mode?'checked':''}><span><strong>${mode==='automatic'?'Automatic':'Manual selection'}</strong><small>${mode==='automatic'?'Follow the current physical connection':'Keep the chosen address'}</small></span></label>`).join('')}</div>
 ${automatic?`<p class="network-selected-interface">${selected?'Selected interface: '+esc(selected.interface)+' · '+esc(selected.address):'Waiting for a network address'}</p><p>Follows DHCP changes and reconnects without changing your computer’s network settings. Physical connections with a default route are preferred, then the lowest route metric, interface name and address. Virtual and VPN interfaces require Manual selection.</p>`:`<label for="network-address">Server address</label><select id="network-address" data-network-input="address" data-picker-title="Choose an address" data-picker-eyebrow="LINUX SERVER" data-picker-description="Select an assigned physical, VPN or advanced interface. This does not connect or configure it." data-picker-footer="The chosen address stays fixed. If it disappears, the network listener waits; localhost stays available.">${options.map(a=>`<option value="${attr(a.address)}" data-title="${attr(a.address)}" data-description="${attr(a.unavailable?a.interface:networkAddressDescription(a))}" ${a.unavailable?'disabled':''} ${a.address===d.address?'selected':''}>${esc(a.address)} · ${esc(a.interface)}</option>`).join('')}</select><p>If this address becomes unavailable, switch to Automatic above to follow the current physical connection.</p>`}</div>`;
}
function networkTestPanel(){
 const v=networkView,t=v.transaction;if(!networkActive())return '';
 if(t.kind==='address-follow')return `<div class="network-test" role="status">${esc(t.message)}</div>`;
 if(t.kind==='certificate-renew')return `<div class="network-test" role="status"><strong>Renewing server certificate</strong><p>${esc(t.message)}</p><p>Your trust certificate and saved addresses stay the same.</p></div>`;
 const pending=t.phase==='pending',canConfirm=pending&&location.origin===t.url&&networkRemaining()>0;
 return `<div class="network-test"><strong>Test your new connection</strong><p id="network-countdown" role="timer" aria-live="off">${pending?`${networkRemaining()} seconds left to confirm. If you do not confirm, the previous settings are kept automatically.`:esc(t.message)}</p>${pending&&t.url?`<a class="button button-neutral network-test-link" href="${attr(t.url)}/#advanced" target="_blank" rel="noopener noreferrer">${esc(t.url)}</a>`:''}<p>Open the proposed address in a new tab, log in with your existing token and return to Advanced Settings to confirm. Keep this tab open until you finish. Your token is never included in the link.</p>${v.draft?.lan&&v.draft?.address_mode==='automatic'&&!networkSelectedAddress()?'<p>No eligible address exists yet. Confirm from localhost to save Automatic mode; the network listener will wait.</p>':''}${!v.draft?.lan?'<p>To disable LAN access, open the localhost link in a browser on the Linux server and confirm there.</p>':''}<div class="actions">${B('Confirm connection','network-confirm',{class:'button-primary',disabled:!canConfirm||v.busy})}${B('Cancel change','network-cancel',{class:'button-neutral',disabled:!['preparing','pending'].includes(t.phase)||v.busy})}</div>${pending&&!canConfirm?'<p>Confirmation is available only through the proposed connection.</p>':''}</div>`;
}
function networkRenewalMessage(){const c=networkView.certificate;return networkDirty()?'Apply or reset your network changes before renewing the certificate.':c.renewable?'Renewal keeps the same trust certificate. You do not need to reinstall it.':c.renewal_reason||'Enable and confirm HTTPS first. You can then renew its server certificate here.';}
function networkCertificateGuide(locked){
 const c=networkView.certificate;
 return `<details class="network-section certificate-guide network-trust" data-network-detail="certificate"><summary>HTTPS certificate — download and setup instructions</summary>
 <p class="certificate-intro">HTTPS encrypts the connection. Because this certificate is created by your own server, each browser or device must trust it once. Downloading it alone is not enough.</p>
 <p>Only trust a certificate from a server you control. Compare its SHA-256 fingerprint with the one shown when accessing the app directly on the server or through a trusted SSH/VPN connection. Do not rely on an untrusted HTTP page to verify itself.</p>
 ${B('Download local HTTPS trust certificate','network-download',{class:'button-neutral',disabled:!c.available&&locked})}
 <p>${esc(c.server_expires?'Server certificate expires '+new Date(c.server_expires).toLocaleDateString()+'. ':'')}${c.available?'Trust certificate SHA-256:':'The download button creates the trust certificate if needed. This does not change your current connection.'}</p>
 ${c.fingerprint?`<code class="fingerprint">${esc(c.fingerprint)}</code>`:''}
 <p>The downloaded file is <code>usb-storage-watch-ca.crt</code>. It contains the public CA certificate, never its private key. Install it on the device where you use the browser.</p>
           <details><summary>Windows — Chrome and Edge</summary><ol>
            <li>Save the certificate on your Windows PC. Press <strong>Win + R</strong>, type <code>certmgr.msc</code> and press Enter.</li>
            <li>Open <strong>Trusted Root Certification Authorities → Certificates</strong>. Right-click <strong>Certificates → All Tasks → Import</strong>.</li>
            <li>Choose the downloaded <code>usb-storage-watch-ca.crt</code>. Keep <strong>Trusted Root Certification Authorities</strong> as the destination. Review the certificate before accepting the trust prompt.</li>
            <li>Close and reopen your browser. Choose HTTPS above, apply and open the proposed address. Log in and select <strong>Confirm connection</strong> in <strong>Advanced Settings</strong>.</li>
          </ol></details>
          <details><summary>Linux — Chrome and Chromium</summary><ol>
            <li>Save the certificate on the Linux computer where you use the browser.</li>
            <li>Type <code>chrome://certificate-manager</code> into the browser’s address bar. Open <strong>Local certificates</strong>, then the <strong>Custom / Installed by you</strong> section. Under <strong>Trusted certificates</strong>, choose <strong>Import</strong> and select the downloaded file.</li>
            <li>Older browsers use <code>chrome://settings/certificates</code>: open <strong>Authorities → Import</strong> and enable trust for identifying websites. Do not import it as a personal/client certificate.</li>
            <li>Restart the browser, then open and confirm the proposed HTTPS address. If your browser or distribution has a different certificate manager, use its documented CA import procedure; do not bypass a warning.</li>
          </ol></details>
          <details><summary>Firefox — desktop</summary><ol>
            <li>Open <strong>Settings → Privacy &amp; Security</strong>. Find <strong>Certificates → View Certificates → Authorities → Import</strong>.</li>
            <li>Select the downloaded certificate and allow it to identify websites after verifying it.</li>
            <li>Restart Firefox, then open and confirm the HTTPS address. Firefox may already trust the verified certificate installed in Windows or macOS.</li>
          </ol></details>
          <details><summary>Android — Chrome</summary><ol>
            <li>Download the certificate on your phone. In Android <strong>Settings</strong>, search for <strong>Install a certificate</strong> or <strong>Encryption &amp; credentials</strong> (often under Security &amp; privacy → More security settings).</li>
            <li>Choose <strong>CA certificate</strong>, verify the source, unlock the phone and select the downloaded file. Menu names vary by manufacturer; this is not a Wi-Fi or personal client certificate.</li>
            <li>Restart Chrome, then open and confirm the HTTPS address. Some managed devices and apps do not accept user-installed CAs. If trust still fails, use a supported browser or a certificate already trusted by your device; never skip the warning.</li>
          </ol></details>
          <details><summary>macOS — Safari and Chrome</summary><ol>
            <li>Open <strong>Keychain Access</strong> on the Mac and import the downloaded certificate into your login keychain.</li>
            <li>Open <strong>USB Storage Watch Local Network</strong>, expand <strong>Trust</strong> and allow trust for <strong>Secure Sockets Layer (SSL)</strong> after verifying its fingerprint. Save and authenticate if asked.</li>
            <li>Restart the browser, then open and confirm the proposed HTTPS address.</li>
          </ol></details>
          <details><summary>iPhone and iPad — Safari</summary><ol>
            <li>Download the certificate in Safari. Open <strong>Settings → General → VPN &amp; Device Management</strong> (or <strong>Profile Downloaded</strong>) and install the certificate profile after checking its source.</li>
            <li>Go to <strong>Settings → General → About → Certificate Trust Settings</strong>. Enable full trust for <strong>USB Storage Watch Local Network</strong>.</li>
            <li>Reopen Safari and confirm the HTTPS address. If your device cannot install the certificate, use your device’s administrator or a certificate it already trusts; do not bypass warnings.</li>
          </ol></details>
          <p class="hint">A changed server address, an expired certificate or importing into the wrong browser/profile can cause warnings. Match the exact address shown by the app. To remove trust later, remove only this app’s CA from the same certificate manager.</p>

 ${B('Renew server certificate','network-renew-prompt',{class:'button-neutral',disabled:locked||!c.renewable||networkDirty()})}<p id="network-renew-hint">${esc(networkRenewalMessage())}</p>
 </details>`;
}
function networkPanel(){
 const v=networkView;if(!v.loaded)return `<section class="card network-card" id="network-panel"><h2 id="network-heading" tabindex="-1">Network access</h2><p role="status">${esc(v.error||'Loading network settings…')}</p>${B('Refresh network settings','network-refresh',{class:'button-neutral'})}</section>`;
 const d=v.draft,locked=v.busy||networkActive()||!!v.recoveryError;
 return `<section class="card network-card" id="network-panel"><h2 id="network-heading" tabindex="-1">Network access</h2><p>Localhost HTTP always stays available on the Linux server and requires your management token. Choose separately how your other devices connect.</p>
 <fieldset ${locked?'disabled':''}><legend class="sr-only">Network connection settings</legend><label class="network-switch-row" for="network-lan"><span><strong>Allow access from my local network</strong><small>Use a browser on your PC, tablet or phone. Changes take effect after you test and confirm them.</small></span><input id="network-lan" data-network-input="lan" type="checkbox" role="switch" class="toggle" ${d.lan?'checked':''}></label></fieldset>
 <div class="network-urls">${networkUrlCard('Network URL',v.saved.lan?v.url:null,'Shown only after this app verifies its listener. '+(v.listener?.interface?'Selected interface: '+v.listener.interface+'.':''),v.saved.lan?(v.listener?.message||'Checking the network listener.'):'Local network access is disabled.')}${networkUrlCard('Localhost URL',v.localUrl,'Only in a browser running on the Linux server. On your phone or Windows PC, localhost means that device, not the server.')}</div>
 <fieldset ${locked?'disabled':''}><legend class="sr-only">Network security, address and ports</legend>
 <details class="network-section" data-network-detail="security" open><summary>Network connection security</summary><p>This choice applies to other devices. HTTPS allows only HTTPS on the selected network address; localhost HTTP stays available on the server.</p>
 <div class="network-protocols" role="radiogroup" aria-label="Network connection type">${['http','https'].map(s=>`<label class="network-protocol ${d.scheme===s?'selected':''}"><input type="radio" name="network-protocol" data-network-input="scheme" value="${s}" ${d.scheme===s?'checked':''} ${!d.lan?'disabled':''}><span><strong>${s.toUpperCase()}</strong><small>${s==='http'?'Unencrypted · trusted private network or VPN only':'Encrypted · trust certificate setup required'}</small></span></label>`).join('')}</div>
 <p class="network-note">HTTP sends your management token without encryption. Never use it on a public or shared network. For access away from home, use a trusted VPN such as Tailscale or WireGuard. Never forward this app’s port to the public internet, even with HTTPS.</p>
 ${d.lan&&d.scheme==='https'?'<p>First download and install the trust certificate below on each device you use. Then apply, open the proposed HTTPS address and confirm the connection there.</p>':''}</details>
 <details class="network-section" data-network-detail="ports" open><summary>Advanced: address and ports</summary><p>Usually you can leave these settings unchanged. They affect this app only, not your computer’s IP address, firewall, router or VPN.</p>${networkAddressField()}
 <div class="network-ports">${networkPort('http_port','HTTP / localhost port',8765)}${networkPort('https_port','Network HTTPS port',8766)}</div><p>The HTTP port is always used for localhost. It is also used on the selected network address only when you choose HTTP.</p></details></fieldset>
 <div class="actions">${B('Apply network settings','network-apply',{class:'button-primary',disabled:!networkCanApply()})}</div><p class="inline-status" id="network-message" role="status" aria-live="polite">${esc(networkMessage())}</p>
 ${networkTrustChange()?`<div class="callout warn"><p>The existing HTTPS trust cannot sign a certificate for this address. This change uses the proposed trust certificate. Existing clients may need to import it again; HTTPS verification stays enabled.</p><label><input type="checkbox" id="network-replace-trust" data-network-input="replace_trust" ${v.replaceTrust?'checked':''} ${locked?'disabled':''}> I understand and approve replacing the HTTPS trust certificate.</label></div>`:''}${networkTestPanel()}${networkCertificateGuide(locked)}</section>`;
}
function renderNetwork(){
 if(route()!=='advanced')return;const old=$('#network-panel');if(!old)return;
 if(activeTouchSelect&&old.contains(activeTouchSelect.button)){networkView.renderPending=true;updateNetworkButtons();return;}
 const opened=Object.fromEntries($$('details',old).map((x,i)=>[x.dataset.networkDetail||'guide-'+i,x.open]));
 const focus=old.contains(document.activeElement)?document.activeElement.id:'';
 const template=document.createElement('template');template.innerHTML=networkPanel();const next=template.content.firstElementChild;old.replaceWith(next);
 $$('details',next).forEach((el,i)=>{const key=el.dataset.networkDetail||'guide-'+i;if(key in opened)el.open=opened[key];});
 enhanceSelects(next);if(focus)document.getElementById(focus)?.focus({preventScroll:true});updateNetworkButtons();
}
function networkOutcome(t=networkView.transaction){
 const messages={preparing:'Preparing connection test. Current access stays available.',pending:'New connection ready for confirmation. Open the proposed address and confirm before the countdown ends.'};
 return {message:messages[t.phase]||t.message||'Checking the network operation.',error:['failed','expired'].includes(t.phase)};
}
function syncNetworkOutcome(){
 const t=networkView.transaction;if(!t.operation)return;
 const outcome=networkOutcome(t);networkView.message='';
 for(const [key,record] of actionFeedback){
   if(record.networkOperation===t.operation){record.message=outcome.message;record.error=outcome.error;syncActionFeedback(key);}
 }
}
async function refreshNetwork({display=true}={}){
 const session=csrfToken,value=await apiRequest('network-state');if(session!==csrfToken)return;
 const v=networkView,wasActive=networkActive(),wasDirty=networkDirty(),before=JSON.stringify([v.loaded,v.saved,v.addresses,v.transaction.phase,v.transaction.message,v.certificate,v.recoveryError,v.url,v.listener]);
 v.saved=value.config;v.url=value.url;v.listener=value.listener||{phase:value.url?'ready':'unavailable',message:value.url?'Network listener verified.':'Network listener unavailable.'};v.localUrl=value.local_url;v.addresses=value.addresses||[];v.certificate=value.certificate||{available:false};v.transaction=value.transaction||{phase:'idle'};v.recoveryError=value.recovery_error||'';v.observedAt=performance.now();v.loaded=true;v.readError='';
 syncNetworkOutcome();
 if(wasActive&&!networkActive())v.replaceTrust=false;
 if(networkActive()&&v.transaction.config)v.draft=networkValues(v.transaction.config);
 else if(!v.draft||wasActive||!wasDirty)v.draft=networkValues(v.saved);
 if(!v.draft.lan&&v.draft.address==='127.0.0.1'&&v.addresses.length)v.draft.address=v.addresses[0].address;
 const after=JSON.stringify([v.loaded,v.saved,v.addresses,v.transaction.phase,v.transaction.message,v.certificate,v.recoveryError,v.url,v.listener]);
 if(display&&before!==after)renderNetwork();else if(display)updateNetworkButtons();updateNetworkCountdown();
}
function updateNetworkButtons(){
 const v=networkView,button=$('[data-action="network-apply"]');if(button)button.disabled=!networkCanApply();
 const renew=$('[data-action="network-renew-prompt"]');if(renew)renew.disabled=v.busy||networkActive()||!!v.recoveryError||!v.certificate.renewable||networkDirty();
 const renewalHint=$('#network-renew-hint');if(renewalHint)renewalHint.textContent=networkRenewalMessage();
 const status=$('#network-message');if(status){status.textContent=networkMessage();status.classList.toggle('error',!!(v.error||v.recoveryError||networkValidation()||v.transaction.phase==='failed'));}
}
function editNetwork(el){
 const key=el.dataset.networkInput;if(!key||networkActive()||networkView.busy||!networkView.draft)return;
 if(key==='replace_trust')networkView.replaceTrust=el.checked;else networkView.draft[key]=key==='lan'?el.checked:el.value;networkView.message='';networkView.error='';
 if(['scheme','lan','address_mode','address'].includes(key))renderNetwork();else updateNetworkButtons();
}
function downloadNetworkCertificate(){const a=document.createElement('a');a.href='/download/proposed-trust-certificate.pem';a.download='usb-storage-watch-ca.crt';document.body.append(a);a.click();a.remove();}
async function networkCommand(action,id,value,context=null){
 if(action==='network-copy')return await copy(value);
 if(action==='network-renew-prompt'){
   confirmAction('Renew server certificate?','Generate a new server certificate using the existing trust authority. Your installed trust certificate remains valid.',async()=>{closeModal();const result=await networkCommand('network-renew',null,null,context);if(result)actionNotice(context,result.message,result.error);return result;});return {message:'Review certificate renewal, then confirm.'};
 }
 if(action==='network-refresh'){try{await refreshNetwork();return {message:'Network settings refreshed.'};}catch(e){networkView.error=errorMessage(e);renderNetwork();throw e;}}
 if(action==='network-step'){
   if(networkView.busy||networkActive())return;const el=document.getElementById('network-'+id);if(!el)return;
   const step=Number(value),current=Number(el.value);if(Math.abs(step)===1&&(!el.value||!Number.isInteger(current)||current<1024||current>65535)){networkView.error='Enter a whole port number from 1024 to 65535, or use Reset.';updateNetworkButtons();return;}
   el.value=String(Math.min(65535,Math.max(1024,Math.abs(step)===1?current+step:step)));editNetwork(el);return;
 }
 if(action==='network-download'&&networkView.certificate.available){downloadNetworkCertificate();return {message:'Certificate download requested. Follow the import instructions below.'};}
 if(networkView.busy)throw Error('A network settings request is still running. Wait for its result, then try again.');
 if(action==='network-apply'&&!networkCanApply()){updateNetworkButtons();return;}
 const method={'network-apply':'network-stage','network-confirm':'network-confirm','network-cancel':'network-cancel','network-certificate':'network-certificate','network-download':'network-certificate','network-renew':'network-renew'}[action];if(!method)return;
 const data=method==='network-stage'?{...networkView.draft,replace_trust:networkView.replaceTrust,http_port:Number(networkView.draft.http_port),https_port:Number(networkView.draft.https_port)}:['network-certificate','network-renew'].includes(method)?{}:{operation:networkView.transaction.operation};
 const v=networkView,session=csrfToken,previousOperation=v.transaction.operation;let outcome=null;
 v.busy=true;v.error='';v.message=method==='network-certificate'?'Preparing your certificate download…':method==='network-stage'?'Preparing connection test…':method==='network-renew'?'Preparing renewed certificate…':'Sending request…';renderNetwork();
 try{
   if(method==='network-stage'&&networkNeedsCertificate()&&!v.certificate.available){v.message='Preparing the HTTPS certificate and connection test…';updateNetworkButtons();v.certificate=await apiRequest('network-certificate',{data:{}});if(session!==csrfToken)return;}
   const result=await apiRequest(method,{data});if(session!==csrfToken)return;
   if(method==='network-certificate')v.certificate=result;else{v.transaction=result;v.observedAt=performance.now();if(context?.record)context.record.networkOperation=result.operation;}
   v.message='';await refreshNetwork({display:false});
   if(action==='network-download')downloadNetworkCertificate();
   outcome=method==='network-certificate'?{message:action==='network-download'?'Certificate download requested. Follow the import instructions below.':'Trust certificate ready.'}:networkOutcome();
 }catch(e){
   if(session!==csrfToken)return;
   const failure=errorMessage(e);try{await refreshNetwork({display:false});}catch(_){}
   if(v.transaction.operation===previousOperation||!v.transaction.operation)v.error=failure+' The request was not sent again.';
   v.message='';outcome={message:operationError(e),error:true};
 }finally{if(session===csrfToken){v.busy=false;renderNetwork();}}
 return outcome;
}
function updateNetworkCountdown(){const t=networkView.transaction;if(t.phase!=='pending')return;const text=$('#network-countdown');if(text)text.textContent=`${networkRemaining()} seconds left to confirm. If you do not confirm, the previous settings are kept automatically.`;const button=$('[data-action="network-confirm"]');if(button)button.disabled=networkView.busy||location.origin!==t.url||networkRemaining()===0;}
setInterval(updateNetworkCountdown,1000);
setInterval(async()=>{
 if(typeof csrfToken==='undefined'||!csrfToken||!['advanced','integrations'].includes(route())||networkReading||networkView.busy||apiBusy||routeLoading)return;
 networkReading=true;try{if(route()==='integrations')await loadIntegrationData();else await refreshNetwork();}catch(e){networkView.readError='Network status unavailable. '+errorMessage(e);networkView.url=null;networkView.listener={message:'Network listener verification is unavailable.'};renderNetwork();}finally{networkReading=false;}
},3000);
