// Chat: Kanäle und Direktnachrichten
import {$,esc,dtfmt,snrCls,enc,chTitle,NTYPE,store,toast,linkify} from './util.js';
import {S,findContactByPrefix,findChan,chanRegion,chanId,pathTxt,actions,ui,onRender,renderSoon} from './state.js';
import {run} from './api.js';

export function convTitle(conv){if(conv.startsWith('room:'))return chTitle(conv.slice(5));if(conv.startsWith('ch:')){const ch=findChan(conv.slice(3));return chTitle(ch?ch.name:conv.slice(3))}const c=findContactByPrefix(conv.slice(2));return c?c.name:conv.slice(2)}
const modeIcon=conv=>{if(conv.startsWith('room:'))return '';const m=notifyMode(conv);return m==='off'?'<span class="muted" title="Benachrichtigung aus">🔕</span>':m==='mention'?'<span class="muted mono" title="Benachrichtigung nur bei Erwähnung">@</span>':''};
const modeSelect=conv=>{const m=notifyMode(conv);return `<label class="muted" for="notifySel">Benachrichtigung</label><select id="notifySel" title="Wann neue Nachrichten als ungelesen markiert und gemeldet werden">${[['all','Alle Nachrichten'],['mention','Nur Erwähnungen'],['off','Aus']].map(([v,l])=>`<option value="${v}"${v===m?' selected':''}>${l}</option>`).join('')}</select>`};
const lastMsgT=c=>{const a=S.msgs[c];return a&&a.length?a[a.length-1].rx:0};
function maxLen(){if(!S.active)return S.maxTxt;if(S.active.startsWith('ch:'))return S.maxTxt-enc.encode(S.self?.name||'').length-2;return S.maxTxt}
function knownRegionNames(){const n=new Set();if(S.scope&&S.scope.name)n.add(S.scope.name);S.regions.forEach(r=>n.add(r));return [...n]}

// Nachricht vom Server (neu oder aktualisiert)
// Benachrichtigungs-Einstellung: Kanäle über Name+Schlüssel (überlebt ein Umsortieren am Gerät), Kontakte über die Unterhaltung
export const notifyKey=conv=>conv.startsWith('ch:')?'chan:'+chanId(findChan(conv.slice(3))):conv;
export const notifyMode=conv=>conv.startsWith('room:')?'off':S.settings.notify?.[notifyKey(conv)]||'all';
const mentionsMe=m=>{const n=S.self?.name;return !!n&&(m.text||'').toLowerCase().includes('@['+n.toLowerCase()+']')};
const markRead=conv=>{delete S.unread[conv];delete S.alert[conv]};
function counts(conv,m){const mode=notifyMode(conv);return mode==='all'||(mode==='mention'&&mentionsMe(m))}
export function onMsg(conv,m,isNew){
  const arr=S.msgs[conv]||(S.msgs[conv]=[]);
  const i=arr.findIndex(x=>x.id===m.id);
  if(i>=0)arr[i]=m;else{arr.push(m);if(arr.length>500)arr.splice(0,arr.length-500)}
  if(isNew&&i<0&&m.dir==='in'&&!m.cli&&!(ui.tab==='chat'&&S.active===conv&&!document.hidden)){  // CLI-Antworten zeigt die Konsole
    S.unread[conv]=(S.unread[conv]||0)+1;
    if(counts(conv,m)){S.alert[conv]=(S.alert[conv]||0)+1;notify(conv,m)}}
  renderSoon();
}
function notify(conv,m){
  if(!$('#setNotify').checked||!document.hidden||!('Notification' in window)||Notification.permission!=='granted')return;
  try{new Notification(convTitle(conv),{body:m.from+': '+m.text,tag:conv})}catch{}
}
async function sendMsg(){
  const text=$('#msgIn').value.trim();if(!text||!S.active||!S.connected)return;
  if(enc.encode(text).length>maxLen())return toast('Nachricht zu lang','err');
  $('#msgIn').value='';updateLen();
  if(!await run('messages/send',{conv:S.active,text}))$('#msgIn').value=text;
}

export function renderChat(){
  if(ui.tab==='chat'&&S.active&&S.unread[S.active]&&!document.hidden)markRead(S.active);
  const q=$('#chatSearch').value.trim().toLowerCase();let h='';
  h+='<h4>Kanäle</h4>';
  S.channels.filter(c=>!q||c.name.toLowerCase().includes(q)).forEach(c=>{const id='ch:'+c.idx;const rg=chanRegion(c);h+=item(id,chTitle(c.name),'',null,rg?(rg==='-'?'ohne':'#'+rg):'')});
  if(!S.channels.length)h+='<div class="muted" style="padding:4px 12px;font-size:12px">'+(S.connected?'keine':'nicht verbunden')+'</div>';
  const rooms=[...S.rooms.values()].filter(r=>!q||r.name.toLowerCase().includes(q)).sort((a,b)=>(b.last||0)-(a.last||0));
  if(rooms.length){h+='<h4 title="Hashtag-Räume, die im Netz gehört wurden, aber nicht auf dem Gerät eingerichtet sind">Gehörte Räume ('+rooms.length+')</h4>';
    rooms.forEach(r=>{h+=item('room:'+r.name,chTitle(r.name),'👂',null,'')})}
  const cs=[...S.contacts.values()].filter(c=>(c.type===1||c.type===3)&&(!q||c.name.toLowerCase().includes(q))).sort((a,b)=>{const la=lastMsgT('c:'+a.key.slice(0,12)),lb=lastMsgT('c:'+b.key.slice(0,12));return lb-la||a.name.localeCompare(b.name)});
  h+='<h4>Kontakte ('+cs.length+')</h4>';
  cs.forEach(c=>{h+=item('c:'+c.key.slice(0,12),c.name,c.type===3?'🏠':'',c)});
  $('#chatlist').innerHTML=h;
  function item(id,name,icon,c,tag,extra=''){const u=S.unread[id];return `<div class="citem${S.active===id?' active':''}" data-conv="${id}">${icon?`<span>${icon}</span>`:''}<span class="nm">${esc(name)}</span>${tag?`<span class="hash" title="Region">${esc(tag)}</span>`:''}${extra}${c&&!c.flood?`<span class="muted mono" title="Pfad">${c.hops.length}h</span>`:''}${modeIcon(id)}${u?`<span class="badge${S.alert[id]?'':' quiet'}" title="${u} ungelesen${S.alert[id]?'':' – ohne Benachrichtigung'}">${u}</span>`:''}</div>`}
  renderConv();updateBadge();
}
function renderConv(){
  const conv=S.active,box=$('#msgs');
  if(!conv){$('#chathead').innerHTML='<span class="muted">Kanal oder Kontakt wählen</span>';box.innerHTML='<div class="empty">💬</div>';updateCompose();return}
  if(ui.tab==='chat'&&S.unread[conv]){markRead(conv);updateBadge()}
  let head=`<span class="t">${esc(convTitle(conv))}</span>`;
  if(conv.startsWith('room:')){const r=S.rooms.get(conv.slice(5));const n=esc(conv.slice(5));
    head+=`<span class="muted">gehört, nicht abonniert${r?' · '+r.count+' Pakete':''}</span><span class="spacer"></span><button class="sm" data-act="subscribeRoom" data-name="${n}" ${S.connected?'':'disabled'} title="Raum auf dem Gerät einrichten – dann auch schreiben">＋ Abonnieren</button><button class="sm danger" data-act="forgetRoom" data-name="${n}">Vergessen</button>`}
  else if(conv.startsWith('c:')){const c=findContactByPrefix(conv.slice(2));head+=c?`<span class="muted">${NTYPE[c.type]} · Pfad: ${pathTxt(c)}</span><span class="spacer"></span>${modeSelect(conv)}<button class="sm" data-act="resetPath" data-key="${c.key}" ${S.connected?'':'disabled'}>Pfad zurücksetzen</button>`:`<span class="spacer"></span>${modeSelect(conv)}`}
  else{const ch=findChan(conv.slice(3));const cur=chanRegion(ch);
    const names=new Set(knownRegionNames());if(cur&&cur!=='-')names.add(cur);
    let opts=`<option value="">Standard (${S.scope&&S.scope.name?'#'+esc(S.scope.name):'keine Region'})</option><option value="-">Ohne Region (ungefiltert)</option>`;
    [...names].sort().forEach(n=>opts+=`<option value="${esc(n)}">#${esc(n)}</option>`);opts+='<option value="+">Andere Region…</option>';
    const ar=S.settings.autoReply?.[notifyKey(conv)];
    head+=`<span class="muted">Gruppenkanal</span><span class="spacer"></span>${modeSelect(conv)}<label class="muted" for="chRegion">Region</label><select id="chRegion">${opts}</select><button class="sm${ar?.on?' on':''}" data-act="autoBox" title="Automatisch auf Auslösewörter antworten">🤖 ${ar?.on?'an':'aus'}</button>`;
  }
  $('#chathead').innerHTML=head;
  if(autoOpen&&autoOpen!==conv){autoOpen=null;$('#autoWrap').innerHTML=''}  // Formular nur beim Öffnen zeichnen (sonst gehen Eingaben verloren)
  const ns=$('#notifySel');
  if(ns)ns.onchange=async()=>{const key=notifyKey(conv),prev=notifyMode(conv);
    if(!await run('settings/notify?key='+encodeURIComponent(key),{value:ns.value},null,'PUT'))ns.value=prev;
    else if(ns.value==='off')delete S.alert[conv]};
  const sel=$('#chRegion');
  if(sel){const ch=findChan(conv.slice(3)),cur=chanRegion(ch);sel.value=cur||'';
    sel.onchange=async()=>{let v=sel.value;if(v==='+'){v=(prompt('Regionsname (ohne #):')||'').trim().replace(/^#/,'');if(!v){sel.value=cur||'';return}}
      const r=await run('channels/'+ch.idx+'/region',{value:v},null,'PUT');
      if(r)toast(chTitle(ch.name)+': '+(v==='-'?'ohne Region':v?'Region #'+v:'Standard-Region des Geräts'),'ok');else sel.value=cur||''}}
  const arr=S.msgs[conv]||[];
  const atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<60;
  box.innerHTML=arr.length?arr.map(m=>{
    const meta=m.dir==='in'?`<span class="from">${esc(m.from)}</span> · ${dtfmt(m.ts||m.rx)}${m.snr!=null?` · <span class="${snrCls(m.snr)}">SNR ${m.snr.toFixed(1)}</span>`:''}${m.hops!=null?' · '+(m.hops==='direkt'?'direkt':m.hops+' Hops'):''}${m.hashBytes?` · <span class="hash" title="Pfad-Hash-Größe">${m.hashBytes}B</span>`:''}${m.region?(m.region==='-'?' · <span class="hash" title="Region">ohne Region</span>':` · <span class="hash known" title="Region">#${esc(m.region)}</span>`):m.regionCode?` · <span class="hash" title="Unbekannte Region – Namen unter Gerät › Region & Routing eintragen">Region ?${m.regionCode}</span>`:''}${replyBtns(conv,m)}`:dtfmt(m.rx);
    let st='',cls='';if(m.dir==='out'){const ch=conv.startsWith('ch:'),rg=ch&&m.region?(m.region==='-'?' (ohne Region)':' (#'+esc(m.region)+')'):'';
      st={sending:'⏳ sende…',sent:ch?'✓ gesendet'+rg:'↗ '+(m.flood?'Flood':'Direkt')+', warte auf ACK…',ok:'✓✓ zugestellt'+(m.rtt?' ('+(m.rtt/1000).toFixed(1)+' s)':''),noack:ch?'kein Repeater gehört':'⚠ keine Bestätigung',fail:'✗ Fehler: '+esc(m.err||'')}[m.status]||'';
      if(m.auto)st='<span title="Automatische Antwort">🤖</span> '+st;
      if(m.repeats&&m.status!=='sending'&&m.status!=='fail')st=repTag(m)+(ch?(m.status==='sent'?'':' · '+st)+rg:' · '+st);
      cls=m.status==='ok'?'ok':m.status==='fail'||(m.status==='noack'&&!ch)?'fail':'';
      if(m.status==='noack'||m.status==='fail')st+=` <button class="sm" data-act="retry" data-conv="${conv}" data-id="${m.id}">↻ erneut</button>`}
    return `<div class="msg ${m.dir}" data-mid="${m.id}"><div class="meta">${meta}</div><div class="txt${m.cli?' mono':''}">${linkify(m.text)}</div>${st?`<div class="st ${cls}">${st}</div>`:''}</div>`}).join(''):'<div class="empty">Noch keine Nachrichten</div>';
  if(atBottom||arr.length<30)box.scrollTop=box.scrollHeight;
  updateCompose();
}
// Rückmeldung: grauer Haken = gesendet, noch kein Repeater gehört; grün mit Zahl = so viele Repeater haben weitergeleitet
const repLine=r=>(r.name||(r.h?r.h:'Repeater'))+(r.h&&r.name?' ('+r.h+')':'')+' · SNR '+r.snr.toFixed(1)+' · '+r.hops+' Hop'+(r.hops===1?'':'s');
function repTag(m){const n=m.repeats.length;
  return n?`<span class="rep ok" data-act="repeats" title="${esc(n+' Repeater gehört:\n'+m.repeats.map(repLine).join('\n'))}">✓ ${n}</span>`:'<span class="rep" title="Gesendet – noch kein Repeater gehört">✓</span>'}
// Auto-Antwort pro Kanal: Auslösewörter, eigene Vorlage (leer = Schnellantwort), Sperrzeit je Absender
let autoOpen=null;
function autoForm(conv,r={}){r=r||{};const cd=r.cooldown||300;
  return `<div class="autobox" id="autoBox"><label><input type="checkbox" id="arOn"${r.on?' checked':''}> Auto-Antwort in diesem Kanal</label>
    <input id="arWords" placeholder="Auslösewörter mit Komma, z. B. test, !ping" value="${esc((r.words||[]).join(', '))}">
    <input id="arTpl" placeholder="Antwort-Vorlage (leer = Schnellantwort-Vorlage)" value="${esc(r.tpl||'')}" maxlength="150">
    <label>Sperrzeit je Absender <select id="arCd">${[[60,'1 min'],[300,'5 min'],[900,'15 min'],[3600,'1 h'],[21600,'6 h']].map(([v,l])=>`<option value="${v}"${v==cd?' selected':''}>${l}</option>`).join('')}</select></label>
    <span><button class="sm" data-act="autoSave">Speichern</button> <button class="sm" data-act="autoBox">Schließen</button></span>
    <p class="muted small">Antwortet der Server, auch ohne offenen Browser: nur auf ganze Wörter, nicht auf Nachrichten an andere (@[Name]), nicht auf ältere als 10 Minuten, höchstens eine Antwort alle 10 s pro Kanal. Platzhalter wie bei der Schnellantwort.</p></div>`}
function replyBtns(conv,m){
  if(m.dir!=='in'||conv.startsWith('room:'))return '';
  let h=` <button class="sm rbtn" title="Antworten (@${esc(m.from)})" data-reply="${esc(m.from)}">↩</button>`;
  h+=` <button class="sm rbtn" title="Schnellantwort senden (Vorlage unter Gerät › App)" data-ack="${m.id}"${S.connected?'':' disabled'}>✓</button>`;
  if(conv.startsWith('ch:')){const c=[...S.contacts.values()].find(c=>c.name===m.from&&(c.type===1||c.type===3));if(c)h+=` <button class="sm rbtn" title="Direktnachricht an ${esc(m.from)}" data-dm="${c.key}">✉</button>`}
  return h;
}
export function updateCompose(){const room=!!S.active?.startsWith('room:'),on=S.connected&&!!S.active&&!room;$('#msgIn').disabled=!on;$('#btnSend').disabled=!on;
  $('#msgIn').placeholder=room?'Zum Schreiben den Raum abonnieren':'Nachricht…';updateLen()}
function updateLen(){const n=enc.encode($('#msgIn').value).length,mx=maxLen();$('#msgLen').textContent=n?n+'/'+mx:'';$('#msgLen').style.color=n>mx?'var(--err)':''}
export function updateBadge(){const n=Object.values(S.alert).reduce((a,b)=>a+b,0);const b=$('#unreadBadge');b.style.display=n?'':'none';b.textContent=n}

export function initChat(){
  $('#chatlist').addEventListener('click',e=>{const it=e.target.closest('.citem');if(!it)return;S.active=it.dataset.conv;markRead(S.active);renderChat();$('#msgIn').focus()});
  $('#chatSearch').oninput=renderChat;
  $('#msgs').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
    if(b.dataset.ack){b.disabled=true;run('messages/ack',{conv:S.active,id:b.dataset.ack}).finally(()=>{b.disabled=false})}  // Vorlage füllt der Server
    else if(b.dataset.reply!=null){const inp=$('#msgIn');const tag=S.active.startsWith('ch:')?'@['+b.dataset.reply+'] ':'';if(tag&&!inp.value.startsWith(tag))inp.value=tag+inp.value.replace(/^@\[[^\]]*\]\s*/,'');inp.focus();inp.setSelectionRange(inp.value.length,inp.value.length);updateLen()}
    else if(b.dataset.dm){actions.openChat({key:b.dataset.dm});setTimeout(()=>$('#msgIn').focus(),50)}});
  $('#msgIn').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg()}});$('#msgIn').oninput=updateLen;$('#btnSend').onclick=sendMsg;
  $('#setNotify').checked=store.get('mcw.notify',false);
  $('#setNotify').onchange=async e=>{if(e.target.checked&&'Notification' in window&&Notification.permission!=='granted'){const p=await Notification.requestPermission();if(p!=='granted')e.target.checked=false}store.set('mcw.notify',e.target.checked)};
  actions.repeats=(d,el)=>toast(el.title,'ok');
  actions.autoBox=()=>{autoOpen=autoOpen===S.active?null:S.active;$('#autoWrap').innerHTML=autoOpen?autoForm(autoOpen,S.settings.autoReply?.[notifyKey(autoOpen)]):''};
  actions.autoSave=async()=>{const conv=S.active,words=$('#arWords').value;
    if(await run('settings/auto-reply?key='+encodeURIComponent(notifyKey(conv)),{on:$('#arOn').checked,words,tpl:$('#arTpl').value,cooldown:+$('#arCd').value},'Auto-Antwort gespeichert','PUT')){autoOpen=null;$('#autoWrap').innerHTML=''}};
  actions.retry=d=>run('messages/retry',{conv:d.conv,id:d.id});
  actions.subscribeRoom=d=>run('rooms/'+encodeURIComponent(d.name)+'/subscribe',undefined,chTitle(d.name)+' auf dem Gerät eingerichtet');
  actions.forgetRoom=d=>{if(confirm(chTitle(d.name)+' vergessen? Der mitgelesene Verlauf wird gelöscht.'))run('rooms/'+encodeURIComponent(d.name),undefined,null,'DELETE')};
  $('#roomProbe').addEventListener('keydown',async e=>{if(e.key!=='Enter')return;const n=e.target.value.trim().replace(/^#/,'');if(!n)return;
    const r=await run('rooms/probe',{value:n});if(!r)return;e.target.value='';
    toast(r.found?chTitle(n)+': '+r.found+' Paket(e) entschlüsselt':chTitle(n)+': noch nichts gehört – wird ab jetzt beobachtet',r.found?'ok':'')});
  onRender('chat',renderChat);
  onRender(null,updateBadge);
}
