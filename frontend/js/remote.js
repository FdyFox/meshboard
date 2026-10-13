// Repeater verwalten (Login, Status, Nachbarn, CLI) und Trace – eigenes Fenster über dem Knotendetail
import {$,esc,ago,dur,snrCls,NTYPE,toast} from './util.js';
import {S,actions,onRender,pathTxt} from './state.js';
import {api,run} from './api.js';

let cur=null;  // {key, info}
const isAdm=t=>t===2||t===3;
const fmt1=v=>v==null?'–':v.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1});
const busy=(b,on,txt)=>{if(!b)return;b.disabled=on;if(txt!=null)b.textContent=txt};

async function open(d){
  const key=d.key,n=S.nodes.get(key)||{},c=S.contacts.get(key);cur={key,info:null};
  $('#remoteDrawer').classList.add('show');
  const typ=(c||n).type,name=c?.name||n.name||key.slice(0,8);
  let info={};try{info=cur.info=await api('remote?key='+key,undefined,'GET')}catch{}
  if(cur?.key!==key)return;
  const adm=isAdm(typ)&&c;
  $('#remoteBody').innerHTML=`<div class="drawer-h"><h3>${esc(name)}</h3><button class="sm" data-act="closeRemote" title="Schließen (Esc)">✕</button></div>
    <div class="kv"><div>Typ</div><div>${NTYPE[typ??0]}</div><div>Schlüssel</div><div class="mono" style="word-break:break-all">${key}</div><div>Pfad</div><div class="mono">${c?esc(pathTxt(c)):'nicht im Gerät gespeichert'}</div></div>
    <h4>📡 Trace</h4>
    <div class="frm"><input id="trPath" class="mono" value="${esc(info.trace||'')}" placeholder="z. B. 5c,7a,${key.slice(0,2)},7a,5c" style="flex:1;min-width:0"><button id="btnTrace" ${S.connected?'':'disabled'}>Senden</button></div>
    <p class="muted small" style="margin:2px 0 0">${info.trace?'Hin und zurück über den bekannten Pfad.':'Kein Pfad bekannt – Hops (1-Byte-Hashes) mit Komma eintragen, hin und zurück.'} Nur Repeater leiten Traces weiter.</p>
    <div id="trOut"></div>
    ${!c&&isAdm(typ)?`<h4>🛠 Verwalten</h4><p class="muted">Zum Verwalten den Knoten erst im Gerät speichern.</p><button class="sm" data-act="addContact" data-key="${key}">＋ Im Gerät speichern</button>`:''}
    ${adm?`<h4>🛠 Anmelden</h4>
    <div class="frm"><input id="rmPw" type="password" placeholder="${info.remembered?'gespeichertes Passwort verwenden':'Admin-Passwort (leer = Gast)'}" autocomplete="off" style="flex:1;min-width:0"><button id="btnLogin" ${S.connected?'':'disabled'}>Anmelden</button></div>
    <label class="frm small"><input type="checkbox" id="rmRemember" ${info.remembered?'checked':''}> Passwort auf dem Server merken</label>
    <div class="small" id="rmLogin">${loginTxt(info.login)}</div>
    <h4>Status</h4><div class="frm"><button class="sm" id="btnRStatus" ${S.connected?'':'disabled'}>Status abfragen</button><button class="sm" id="btnRNb" ${S.connected?'':'disabled'}>Nachbarn abfragen</button></div>
    <div id="rmStatus"></div><div id="rmNb"></div>
    <h4>Konsole (CLI)</h4><div class="console" id="rmCli"></div>
    <div class="frm"><input id="rmCmd" class="mono" placeholder="Befehl, z. B. ver, clock, get radio, neighbors" style="flex:1;min-width:0" autocomplete="off"><button id="btnCmd" ${S.connected?'':'disabled'}>Senden</button></div>
    <div class="frm small">${['ver','clock','get name','get radio','get tx','neighbors','advert'].map(x=>`<button class="sm" data-act="cliPreset" data-cmd="${x}">${x}</button>`).join('')}</div>
    <p class="muted small">Befehle brauchen eine Admin-Anmeldung. Antworten kommen über Funk und erscheinen nach einigen Sekunden.</p>`:''}`;
  $('#btnTrace').onclick=trace;$('#trPath').onkeydown=e=>{if(e.key==='Enter')trace()};
  if(!adm)return;
  $('#btnLogin').onclick=login;$('#rmPw').onkeydown=e=>{if(e.key==='Enter')login()};
  $('#btnRStatus').onclick=status;$('#btnRNb').onclick=neighbours;
  $('#btnCmd').onclick=()=>cli($('#rmCmd').value);$('#rmCmd').onkeydown=e=>{if(e.key==='Enter')cli($('#rmCmd').value)};
  renderCli();
}
const loginTxt=l=>l?`<span class="snr-g">● angemeldet${l.admin?' als Admin':' als Gast'}</span> <span class="muted">vor ${ago(l.t)}</span>`:'<span class="muted">nicht angemeldet</span>';
const close=()=>{cur=null;$('#remoteDrawer').classList.remove('show')};

async function trace(){
  const b=$('#btnTrace'),p=$('#trPath').value.trim();if(!p)return toast('Pfad eintragen','err');
  busy(b,true,'läuft…');$('#trOut').innerHTML='';
  try{const r=await api('trace',{value:p});if(!cur)return;
    const nm=h=>h.name?esc(h.name)+(h.guess?'?':''):'<span class="muted">unbekannt</span>';
    const rows=r.hops.map((h,i)=>`<tr><td>${i?nm(r.hops[i-1]):'ich'} → ${nm(h)} <span class="mono muted">${h.hash}</span></td><td class="mono ${snrCls(h.snr)}">${h.snr==null?'–':fmt1(h.snr)+' dB'}</td></tr>`);
    if(r.final!=null)rows.push(`<tr><td>${nm(r.hops[r.hops.length-1])} → ich</td><td class="mono ${snrCls(r.final)}">${fmt1(r.final)} dB</td></tr>`);
    $('#trOut').innerHTML=`<div class="tblwrap"><table><thead><tr><th>Abschnitt</th><th>SNR beim Empfänger</th></tr></thead><tbody>${rows.join('')}</tbody></table></div><p class="muted small">Antwort nach ${fmt1(r.ms/1000)} s · ? = vermutet (mehrdeutiger Hash)</p>`;
  }catch(e){$('#trOut').innerHTML=`<p class="snr-r small">${esc(e.message)}</p>`}
  finally{busy(b,!S.connected,'Senden')}
}
async function login(){
  const b=$('#btnLogin'),pw=$('#rmPw').value;busy(b,true,'…');
  try{const l=await api('remote/login',{key:cur.key,password:pw||(cur.info?.remembered?null:''),remember:$('#rmRemember').checked});
    if(!cur)return;$('#rmLogin').innerHTML=loginTxt(l);$('#rmPw').value='';toast('Angemeldet'+(l.admin?' (Admin)':' (Gast)'),'ok');
    cur.info.remembered=l.remembered;$('#rmPw').placeholder=l.remembered?'gespeichertes Passwort verwenden':'Admin-Passwort (leer = Gast)'}
  catch(e){toast(e.message,'err')}finally{busy(b,!S.connected,'Anmelden')}
}
async function status(){
  const b=$('#btnRStatus');busy(b,true,'frage ab…');
  try{const s=await api('remote/status',{key:cur.key});if(!cur)return;
    const kv=[['Batterie',(s.batt/1000).toFixed(2)+' V'],['Laufzeit',dur(s.uptime)],['Rauschpegel',s.noise+' dBm'],['Letzter Empfang',s.lastRssi+' dBm / '+fmt1(s.lastSnr)+' dB'],
      ['Sendezeit TX / RX',dur(s.airtime)+' / '+dur(s.rxAirtime)],['Empfangen',s.recv+' (Flood '+s.recvFlood+' / Direkt '+s.recvDirect+')'],['Gesendet',s.sent+' (Flood '+s.sentFlood+' / Direkt '+s.sentDirect+')'],
      ['Duplikate Flood / Direkt',s.floodDups+' / '+s.directDups],['Sendewarteschlange',s.txQueue],['Warteschlange voll',s.fullEvents],['Empfangsfehler',s.recvErrors??'–']];
    $('#rmStatus').innerHTML=`<div class="kv">${kv.map(([k,v])=>`<div>${k}</div><div class="mono">${v}</div>`).join('')}</div><p class="muted small">Stand ${new Date(s.t).toLocaleTimeString('de-DE')}</p>`}
  catch(e){toast(e.message,'err')}finally{busy(b,!S.connected,'Status abfragen')}
}
async function neighbours(){
  const b=$('#btnRNb');busy(b,true,'frage ab…');
  try{const l=await api('remote/neighbours',{key:cur.key});if(!cur)return;
    $('#rmNb').innerHTML=l.length?`<div class="tblwrap"><table><thead><tr><th>Nachbar</th><th>SNR</th><th>gehört</th><th>Entfernung</th></tr></thead><tbody>${l.map(n=>`<tr${n.key?` class="click" data-act="nodeDetail" data-key="${n.key}"`:''}><td>${n.name?esc(n.name):'<span class="muted">unbekannt</span>'} <span class="mono muted">${n.hash}</span></td><td class="mono ${snrCls(n.snr)}">${fmt1(n.snr)}</td><td>vor ${dur(n.secsAgo)}</td><td class="mono">${n.km!=null?fmt1(n.km)+' km':'–'}</td></tr>`).join('')}</tbody></table></div><p class="muted small">Stationen, die dieser Repeater direkt hört, mit SNR an seiner Antenne.</p>`:'<p class="muted">Keine Nachbarn gemeldet.</p>'}
  catch(e){toast(e.message,'err')}finally{busy(b,!S.connected,'Nachbarn abfragen')}
}
async function cli(cmd){cmd=(cmd||'').trim();if(!cmd||!cur)return;if(await run('remote/cli',{key:cur.key,cmd}))$('#rmCmd').value=''}
// Konsole: CLI-Befehle und Antworten aus der Unterhaltung des Repeaters
function renderCli(){
  const el=$('#rmCli');if(!el||!cur)return;
  const arr=(S.msgs['c:'+cur.key.slice(0,12)]||[]).filter(m=>m.cli).slice(-60);
  const atBottom=el.scrollHeight-el.scrollTop-el.clientHeight<30;
  el.innerHTML=arr.length?arr.map(m=>`<div class="${m.dir}"><span class="muted">${new Date(m.rx||m.ts).toLocaleTimeString('de-DE')}</span> ${m.dir==='out'?'&gt; ':''}${esc(m.text)}${m.status==='fail'?' <span class="snr-r">✗ '+esc(m.err||'')+'</span>':''}</div>`).join(''):'<div class="muted">Noch keine Befehle.</div>';
  if(atBottom)el.scrollTop=el.scrollHeight;
}

export function initRemote(){
  actions.remote=open;actions.closeRemote=close;actions.cliPreset=d=>cli(d.cmd);
  $('#remoteDrawer').addEventListener('click',e=>{if(e.target.id==='remoteDrawer')close()});
  // Esc schließt zuerst dieses Fenster, nicht das Knotendetail darunter
  addEventListener('keydown',e=>{if(e.key==='Escape'&&cur){e.stopImmediatePropagation();close()}},true);
  onRender(null,renderCli);
}
