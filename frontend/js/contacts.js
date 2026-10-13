// Kontakte: gespeicherte Kontakte und gehörte Knoten
import {$,esc,ago,snrCls,hav,hasPos,NTYPE} from './util.js';
import {S,lastSeen,pathTxt,actions,onRender} from './state.js';
import {run} from './api.js';

export function renderContacts(){
  const q=$('#cSearch').value.trim().toLowerCase(),t=$('#cType').value,heard=$('#cHeard').checked,on=S.connected?'':' disabled';
  let list=[...S.nodes.values()].filter(n=>S.contacts.has(n.key)||heard);
  for(const c of S.contacts.values())if(!S.nodes.has(c.key))list.push({key:c.key,name:c.name,type:c.type});
  list=list.filter(n=>(!t||String(n.type)===t)&&(!q||(n.name||'').toLowerCase().includes(q)||n.key.startsWith(q))).sort((a,b)=>lastSeen(b)-lastSeen(a));
  $('#ctable').innerHTML=list.map(n=>{const c=S.contacts.get(n.key);
    const dist=hasPos(n)&&hasPos(S.self)?hav(S.self.lat,S.self.lon,n.lat,n.lon).toFixed(1)+' km':'–';
    let act='';
    if(c){if(c.type===1||c.type===3)act+=`<button class="sm" data-act="openChat" data-key="${n.key}">💬</button> `;
      if(!c.saved)act+=`<button class="sm" data-act="addContact" data-key="${n.key}" title="Im Gerät speichern"${on}>＋</button> `;
      else act+=`<button class="sm" data-act="resetPath" data-key="${n.key}" title="Pfad zurücksetzen"${on}>↺</button> <button class="sm" data-act="shareContact" data-key="${n.key}" title="Per Zero-Hop teilen"${on}>⇪</button> <button class="sm danger" data-act="removeContact" data-key="${n.key}" title="Löschen"${on}>🗑</button> `}
    if(c)act+=`<button class="sm" data-act="remote" data-key="${n.key}" title="${c.type===2||c.type===3?'Verwalten (Login, Status, Nachbarn, CLI) und Trace':'Trace'}">${c.type===2||c.type===3?'🛠':'📡'}</button> `;
    if(hasPos(n))act+=`<button class="sm" data-act="zoomTo" data-key="${n.key}">🗺</button>`;
    return `<tr><td>${esc(n.name||'?')}${c&&!c.saved?' <span class="muted">(neu)</span>':''}${!c?' <span class="muted">(gehört)</span>':''}</td><td>${NTYPE[n.type??0]}</td><td class="mono">${n.key.slice(0,12)}</td><td>${ago(lastSeen(n))}</td><td class="mono">${c?pathTxt(c):'–'}</td><td class="mono ${snrCls(n.snr)}">${n.snr!=null?n.snr.toFixed(1):'–'}</td><td>${dist}</td><td style="white-space:nowrap">${act}</td></tr>`}).join('')||'<tr><td colspan="8" class="muted">Keine Einträge</td></tr>';
}

export function initContacts(){
  $('#cSearch').oninput=renderContacts;['#cType','#cHeard'].forEach(s=>$(s).onchange=renderContacts);
  $('#btnReloadC').onclick=async()=>{const r=await run('contacts/reload');if(r)$('#btnReloadC').blur()};
  actions.resetPath=d=>run('contacts/'+d.key+'/reset-path',undefined,'Pfad zurückgesetzt – nächste Nachricht wird geflutet');
  actions.shareContact=d=>run('contacts/'+d.key+'/share',undefined,'Kontakt per Zero-Hop geteilt');
  actions.addContact=d=>run('contacts/'+d.key+'/add',undefined,'Im Gerät gespeichert');
  actions.removeContact=d=>{const c=S.contacts.get(d.key);if(confirm('Kontakt „'+(c?.name||d.key.slice(0,8))+'“ vom Gerät löschen?'))run('contacts/'+d.key,undefined,'Gelöscht','DELETE')};
  onRender('contacts',renderContacts);
}
