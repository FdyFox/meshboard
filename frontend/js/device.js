// Gerät: Verbindung, Infos, Statistik, Einstellungen, Region, Protokoll-Log; Kopfzeile
import {$,esc,dur,ago,hasPos,toast,chTitle,enc} from './util.js';
import {ackText} from './chat.js';
import {S,ui,onRender,actions,switchTab} from './state.js';
import {run,api} from './api.js';

const TR={tcp:'TCP / WiFi',serial:'USB / Seriell',ble:'Bluetooth LE'};
const PH={tcp:'192.168.1.50:5000',serial:'/dev/ttyUSB0',ble:'Adresse (leer = erstes MeshCore-Gerät)'};
const kv=a=>a.filter(x=>x[1]!=null&&x[1]!=='').map(([k,v])=>`<div>${k}</div><div>${v}</div>`).join('');
let connFormSet=false;
// „Verbinden“ nur, wenn es etwas bewirkt: getrennt, oder eine andere Node im Formular („Wechseln“)
function updConnBtn(){
  const st=S.status,t=st.target,b=$('#btnConnSet');
  const same=!!t&&$('#connType').value===t.transport&&$('#connAddr').value.trim()===t.address;
  const busy=S.connected||!!st.connecting;
  b.disabled=!!st.connecting||(busy&&same);
  b.textContent=busy&&!same?'Wechseln':'Verbinden';
  b.title=b.disabled?(st.connecting?'Verbindung wird aufgebaut':'Mit dieser Node bereits verbunden'):busy?'Zur eingetragenen Node wechseln':'Mit der eingetragenen Node verbinden';
}

export function renderDevice(){
  const s=S.self,d=S.dev,r=S.radio,st=S.status;
  const state=S.connected?'<b>verbunden</b>':st.connecting?'verbinde…':st.want&&st.target?'getrennt – neuer Versuch folgt':'getrennt';
  $('#kvConn').innerHTML=kv([['Status',state],['Node',st.target?esc(TR[st.target.transport]+' '+st.target.address):'<span class="muted">nicht konfiguriert</span>'],['Fehler',st.error&&!S.connected?'<span style="color:var(--err)">'+esc(st.error)+'</span>':null]]);
  if(!connFormSet&&st.target){$('#connType').value=st.target.transport;$('#connAddr').value=st.target.address;connFormSet=true}
  $('#connAddr').placeholder=PH[$('#connType').value];
  updConnBtn();
  $('#kvInfo').innerHTML=s?kv([['Name',esc(s.name)],['Verbindung',esc(st.label||'')],['Firmware',esc(d?.version||'v'+d?.fw)+(d?.build?' ('+esc(d.build)+')':'')],['Hardware',esc(d?.model)],['Public Key','<span class="mono" style="word-break:break-all">'+s.key+'</span>'],['Position',hasPos(s)?s.lat.toFixed(5)+', '+s.lon.toFixed(5):'nicht gesetzt'],['Kontakte',S.contacts.size+(d?.maxContacts?' / '+d.maxContacts:'')],['Kanäle',S.channels.length+(d?.maxChannels?' / '+d.maxChannels:'')]]):'<div class="muted">nicht verbunden</div><div></div>';
  $('#kvStats').innerHTML=s?kv([['Frequenz',s.freq.toFixed(3)+' MHz'],['Bandbreite',s.bw+' kHz'],['SF / CR','SF'+s.sf+' / 4:'+s.cr],['TX-Leistung',s.tx+' dBm (max '+s.maxTx+')'],['Batterie',r.batt?(r.batt/1000).toFixed(2)+' V':null],['Speicher',r.total?r.used+' / '+r.total+' kB':null],['Laufzeit',r.uptime!=null?dur(r.uptime):null],['Rauschpegel',r.noise!=null?r.noise+' dBm':null],['Letzt. RSSI/SNR',r.lastRssi!=null?r.lastRssi+' dBm / '+r.lastSnr.toFixed(1)+' dB':null],['Airtime TX / RX',r.txAir!=null?dur(r.txAir)+' / '+dur(r.rxAir):null],['Pakete RX / TX',r.recv!=null?r.recv+' / '+r.sent:null],['RX Flood / Direkt',r.rFlood!=null?r.rFlood+' / '+r.rDirect:null],['TX Flood / Direkt',r.sFlood!=null?r.sFlood+' / '+r.sDirect:null],['RX-Fehler',r.rErr]]):'';
  const hm=d?.pathHashMode;
  $('#kvRegion').innerHTML=s?kv([['Region',S.scope==null?'<span class="muted">nicht unterstützt</span>':S.scope.name?'<b>#'+esc(S.scope.name)+'</b>':'keine (ungefiltert)'],['Pfad-Hash',hm!=null?(hm+1)+' Byte':'<span class="muted">unbekannt</span>'],['Erkannte Regionen',S.regions.length?S.regions.map(r=>'#'+esc(r)).join(', '):'–']]):'';
  if(s&&document.activeElement!==$('#setHashMode')&&hm!=null)$('#setHashMode').value=hm;
  if(s){if(document.activeElement!==$('#setName'))$('#setName').value=s.name;$('#setTx').placeholder='TX dBm ('+s.tx+')';$('#setLocAdv').checked=!!s.locPolicy;$('#setAutoAdd').checked=!(s.manualAdd&1);
    if(hasPos(s)&&!$('#setLat').value){$('#setLat').value=s.lat.toFixed(5);$('#setLon').value=s.lon.toFixed(5)}}
  if(document.activeElement!==$('#extraRegions'))$('#extraRegions').value=S.settings.extraRegions||'';
  if(document.activeElement!==$('#setAck'))$('#setAck').value=S.settings.ackTemplate||'';
  ackPreview();
  $('#logOn').checked=S.logOn;
  renderNet();renderLog();
}
// Gehörte Regionen und Kanäle/Räume
function renderNet(){
  const tbl=(head,rows)=>rows.length?`<table><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`:'<div class="muted" style="font-size:12px">noch nichts gehört</div>';
  const rg=Object.entries(S.regionStats).sort((a,b)=>b[1].count-a[1].count).map(([n,e])=>{
    const src=n==='?'?'<span class="muted">unbekannt</span>':'<span class="hash known">#'+esc(n)+'</span>'+(S.regions.includes(n)?'':` <span class="muted" title="aus der eingebauten Namensliste erkannt">Liste</span> <button class="sm" data-act="saveRegion" data-name="${esc(n)}" title="Als bekannte Region speichern (Gerät › Weitere Regionen)">Speichern</button>`);
    return `<tr><td>${src}</td><td class="mono">${e.count}</td><td>${ago(e.last)}</td><td class="wrap muted">${esc(e.nodes.join(', '))}</td></tr>`});
  $('#netRegions').innerHTML=tbl(['Region','Pakete','zuletzt','gehört von'],rg);
  const onDev=h=>S.channels.some(c=>c.hash===h);
  const ch=Object.values(S.chanStats).sort((a,b)=>b.count-a.count).map(e=>{
    const room=e.name&&S.rooms.has(e.name);
    const nm=e.name?esc(chTitle(e.name))+(onDev(e.hash)&&!room?' <span class="muted">Gerät</span>':room?` <button class="sm" data-act="openRoom" data-name="${esc(e.name)}">👂 lesen</button>`:''):'<span class="muted">unbekannt</span>';
    return `<tr><td class="mono">${e.hash}</td><td>${nm}</td><td class="mono">${e.count}</td><td>${ago(e.last)}</td></tr>`});
  $('#netChans').innerHTML=tbl(['Hash','Kanal / Raum','Pakete','zuletzt'],ch);
  $('#netWatch').innerHTML=S.watchRooms.length?'<span class="muted">Beobachtete Räume:</span> '+S.watchRooms.map(n=>`<span class="hash">${esc(chTitle(n))} <a href="#" data-act="forgetRoom" data-name="${esc(n)}" title="nicht mehr beobachten">✕</a></span>`).join(' '):'';
}
// Vorschau der Schnellantwort mit Beispielwerten (Vorlage aus dem Eingabefeld, noch ungespeichert)
const ACK_SAMPLE={from:'Alice',hops:3,path:['e6c4','0741','78df'],km:48.2,segs:4,noloc:0,snr:5.25,region:'saarland',ts:Date.now()-2400,rx:Date.now()};
function ackPreview(){
  const tpl=$('#setAck').value.trim()||S.settings.ackDefault||'';
  const t=ackText(ACK_SAMPLE,false,tpl),n=enc.encode(t).length;
  $('#ackPrev').textContent=t;$('#ackLen').textContent=n+' Byte';$('#ackLen').style.color=n>S.maxTxt?'var(--err)':'';
}
export function renderLog(){if(ui.tab!=='device')return;
  $('#rawlog').textContent=S.log.length?S.log.slice().reverse().join('\n'):S.logOn?'Warte auf Daten …':'Aus. „aufzeichnen“ anhaken, um die rohe Kommunikation zwischen Server und Node mitzuschneiden (TX = Befehl an die Node, RX = Antwort/Meldung, Bytes als Hex; die letzten 300 Zeilen, nur im Speicher).'}
export function updateHeader(){
  const st=S.status;
  $('#dot').classList.toggle('on',S.connected);$('#dot').classList.toggle('wait',!S.connected&&!!st.connecting);
  if(!S.connected||!S.self){$('#devinfo').innerHTML='<span>'+(st.connecting?'verbinde…':'nicht verbunden')+'</span>';return}
  const s=S.self,r=S.radio;
  $('#devinfo').innerHTML=`<span><b>${esc(s.name)}</b></span><span>${s.freq.toFixed(3)} MHz · BW${s.bw} · SF${s.sf}</span>${r.batt?`<span>🔋 ${(r.batt/1000).toFixed(2)} V</span>`:''}${r.noise!=null?`<span>Rauschen ${r.noise} dBm</span>`:''}<span class="muted">${esc(st.label||'')}</span>`;
}
export function setEnabled(){
  const on=S.connected;
  ['#btnDisc','#btnAdv0','#btnAdvF','#btnReloadC','#btnStats','#btnSetName','#btnSetPos','#btnSetTx','#setLocAdv','#setAutoAdd','#btnTime','#btnSync','#btnReboot','#btnSetRegion','#btnClrRegion','#setHashMode','#btnSetHash'].forEach(s=>$(s).disabled=!on);
  $('#btnDisc').disabled=!on&&!S.status.connecting&&!S.status.want;
  $('#btnConn').disabled=on||!!S.status.connecting||!S.status.target;
}

async function scan(){
  const t=$('#connType').value,dl=$('#connList');
  if(t==='tcp')return toast('Für TCP die IP-Adresse der Node eintragen (Standard-Port 5000)');
  const b=$('#btnConnScan');b.disabled=true;b.textContent=t==='ble'?'Suche (5 s)…':'Suche…';
  try{
    const l=t==='serial'?await api('serial-ports',undefined,'GET'):await api('ble-scan');
    dl.innerHTML=l.map(x=>t==='serial'?`<option value="${esc(x.device)}">${esc(x.description)}</option>`:`<option value="${esc(x.address)}">${esc(x.name)}</option>`).join('');
    if(l.length===1)$('#connAddr').value=t==='serial'?l[0].device:l[0].address;
    toast(l.length?l.length+' gefunden – Adresse auswählen':'Nichts gefunden',l.length?'ok':'err');
  }catch(e){toast(e.message,'err')}
  finally{b.disabled=false;b.textContent='Suchen'}
}

export function initDevice(){
  $('#btnConn').onclick=()=>run('connect');
  $('#btnDisc').onclick=()=>run('disconnect');
  $('#connType').onchange=()=>{$('#connAddr').placeholder=PH[$('#connType').value];$('#connList').innerHTML='';updConnBtn()};
  $('#connAddr').addEventListener('input',updConnBtn);
  $('#btnConnScan').onclick=scan;
  $('#btnConnSet').onclick=()=>{const t=$('#connType').value,a=$('#connAddr').value.trim();if(t!=='ble'&&!a)return toast('Adresse eintragen','err');run('connect',{transport:t,address:a})};
  const adv=flood=>run('advert',{flood},(flood?'Flood':'Zero-Hop')+'-Advert gesendet');
  $('#btnAdv0').onclick=()=>adv(false);$('#btnAdvF').onclick=()=>adv(true);
  $('#btnStats').onclick=()=>run('device/stats');
  $('#btnSetName').onclick=()=>{const n=$('#setName').value.trim();if(n)run('device/name',{value:n},'Name gesetzt – Advert senden, damit andere ihn sehen')};
  $('#btnSetPos').onclick=async()=>{const lat=parseFloat($('#setLat').value.replace(',','.')),lon=parseFloat($('#setLon').value.replace(',','.'));
    if(!(Math.abs(lat)<=90&&Math.abs(lon)<=180))return toast('Ungültige Koordinaten','err');
    if(await run('device/position',{lat,lon}))toast('Position gesetzt'+(S.self?.locPolicy?' – mit dem nächsten Advert sichtbar':' – Hinweis: „Standort in Adverts mitsenden“ ist aus'),'ok')};
  $('#btnSetTx').onclick=()=>{const v=parseInt($('#setTx').value,10);if(!isNaN(v))run('device/tx',{value:v},'TX-Leistung: '+v+' dBm')};
  $('#setLocAdv').onchange=async e=>{if(!await run('device/other',{locAdv:e.target.checked},'Gespeichert'))renderDevice()};
  $('#setAutoAdd').onchange=async e=>{if(!await run('device/other',{autoAdd:e.target.checked},'Gespeichert'))renderDevice()};
  $('#btnSetAck').onclick=()=>run('settings/ack-template',{value:$('#setAck').value},'Vorlage gespeichert','PUT');
  $('#btnResetAck').onclick=()=>{$('#setAck').value=S.settings.ackDefault||'';ackPreview()};
  $('#setAck').oninput=ackPreview;
  $('#setAck').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('#btnSetAck').click()}});  // einzeilig: Enter speichert
  $('#btnTime').onclick=()=>run('device/time',undefined,'Uhrzeit gesetzt');
  $('#btnSync').onclick=()=>run('messages/sync');
  $('#btnSetRegion').onclick=()=>{const n=$('#setRegion').value.trim().replace(/^#/,'');if(!n)return toast('Regionsnamen eingeben','err');run('region',{value:n},'Region #'+n+' gesetzt')};
  $('#btnClrRegion').onclick=()=>{if(confirm('Region entfernen? Flood-Pakete werden dann ungefiltert gesendet.'))run('region',{value:''},'Region entfernt – Flood ohne Regionsfilter')};
  $('#btnSetHash').onclick=()=>{const m=+$('#setHashMode').value;if(m>0&&!confirm((m+1)+'-Byte-Pfad-Hashes setzen? Repeater mit älterer Firmware können solche Pakete eventuell nicht weiterleiten.'))return;run('hash-mode',{value:m},'Pfad-Hash-Größe: '+(m+1)+' Byte')};
  $('#extraRegions').onchange=()=>run('settings/extra-regions',{value:$('#extraRegions').value},null,'PUT');
  $('#btnReboot').onclick=()=>{if(confirm('Gerät neu starten?'))run('device/reboot',undefined,'Neustart ausgelöst')};
  $('#btnWipe').onclick=()=>{if(confirm('Auf dem Server gespeicherte Knoten, Chatverläufe, gehörte Räume, Paketverlauf und Gerätewerte löschen? Die Statistik beginnt dann von vorn. Auf dem Gerät wird nichts gelöscht.'))run('wipe',undefined,'Gespeicherte Daten gelöscht')};
  $('#logOn').onchange=e=>{S.logOn=e.target.checked;if(!S.logOn)S.log=[];run('log',{on:S.logOn});renderLog()};
  actions.saveRegion=d=>run('regions/save',{value:d.name},'#'+d.name+' gespeichert');
  actions.openRoom=d=>{S.active='room:'+d.name;switchTab('chat')};
  onRender('device',renderDevice);
  onRender(null,updateHeader);
  onRender(null,setEnabled);
}
