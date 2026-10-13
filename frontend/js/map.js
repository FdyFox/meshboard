// Karte (Leaflet): Knoten, Nachbar-Linien, Paketpfade, eigene Position
import {$,$$,esc,ago,hav,hasPos,NTYPE,NLETTER,store,toast} from './util.js';
import {api} from './api.js';
import {S,nodesByHash,hopInfo,lastSeen,actions,ui,onRender,onShow,switchTab} from './state.js';
import {baseLayers,defaultBase} from './basemaps.js';
import {watchBtn} from './stats.js';

let map=null,markers=new Map(),selfMarker=null,neighLayer=null,pathLayer=null,animLayer=null,fitted=false;
function initMap(){
  if(map||typeof L==='undefined'){if(typeof L==='undefined')$('#map').innerHTML='<div class="empty">Leaflet konnte nicht geladen werden (offline?).</div>';return}
  map=L.map('map',{preferCanvas:false}).setView([49.38,6.95],9);
  const base=baseLayers(),saved=store.get('mcw.basemap',null);
  (base[saved]||defaultBase(base)).addTo(map);
  map.on('baselayerchange',e=>store.set('mcw.basemap',e.name));
  L.control.layers(base,null,{position:'topleft'}).addTo(map);
  L.control.scale({imperial:false}).addTo(map);
  neighLayer=L.layerGroup().addTo(map);pathLayer=L.layerGroup().addTo(map);animLayer=L.layerGroup().addTo(map);
}
function icon(n,old){return L.divIcon({className:'',html:`<div class="mk mk-${n.type??0}${old?' old':''}">${NLETTER[n.type??0]}</div>`,iconSize:[22,22],iconAnchor:[11,11],popupAnchor:[0,-10]})}
function popupHtml(n){
  const ct=S.contacts.get(n.key),dist=hasPos(S.self)?hav(S.self.lat,S.self.lon,n.lat,n.lon):null;
  const nb=[...S.neighbors.entries()].find(([h])=>n.key.startsWith(h));
  return `<b>${esc(n.name||'?')}</b><br>${NTYPE[n.type??0]} · <span class="mono">${n.key.slice(0,12)}</span><br>`+
   (n.heard?`Zuletzt gehört: vor ${ago(n.heard)}<br>`:'')+(n.advTs?`Advert: ${new Date(n.advTs*1000).toLocaleString('de-DE')}<br>`:'')+
   (n.snr!=null?`SNR ${n.snr.toFixed(1)} dB · RSSI ${n.rssi} dBm · ${n.hops===0?'direkt':n.hops+' Hops'}<br>`:'')+
   (nb?`<b>Direkter Nachbar</b> (${nb[1].n}× gehört, Ø SNR ${(nb[1].snrSum/nb[1].n).toFixed(1)})<br>`:'')+
   (dist!=null?`Entfernung: ${dist.toFixed(1)} km<br>`:'')+
   `${n.lat.toFixed(5)}, ${n.lon.toFixed(5)}<br>`+
   watchBtn(n.key,'')+' '+(ct?.saved?(ct.type===1||ct.type===3?`<button class="sm" data-act="openChat" data-key="${n.key}">💬 Chat</button> `:'')+`<button class="sm" data-act="remote" data-key="${n.key}">${ct.type===2||ct.type===3?'🛠 Verwalten':'📡 Trace'}</button>`:
    `<button class="sm" data-act="addContact" data-key="${n.key}"${S.connected?'':' disabled'}>＋ Im Gerät speichern</button>`);
}
let mapT=null;export function renderMapSoon(){if(!mapT)mapT=setTimeout(()=>{mapT=null;renderMap()},800)}
function renderMap(){
  if(!map)return;
  const types=new Set($$('.mf').filter(x=>x.checked).map(x=>+x.dataset.t)),age=+$('#mAge').value,labels=$('#mLabels').checked;
  const seen=new Set();let cnt=0;
  for(const n of S.nodes.values()){
    if(!hasPos(n)||!types.has(n.type??0))continue;
    const ls=lastSeen(n);if(age&&ls&&Date.now()-ls>age*1000)continue;if(age&&!ls)continue;
    const old=ls&&Date.now()-ls>86400000;seen.add(n.key);cnt++;
    let m=markers.get(n.key);
    if(!m){m=L.marker([n.lat,n.lon],{icon:icon(n,old)}).addTo(map);m.bindPopup('');m.on('popupopen',()=>m.setPopupContent(popupHtml(S.nodes.get(n.key)||n)));markers.set(n.key,m)}
    else{m.setLatLng([n.lat,n.lon]);m.setIcon(icon(n,old));if(m.isPopupOpen())m.setPopupContent(popupHtml(n))}
    m.unbindTooltip();if(labels)m.bindTooltip(esc(n.name||n.key.slice(0,6)),{permanent:true,direction:'right',offset:[10,0],className:'lbl'});
  }
  for(const [k,m] of markers)if(!seen.has(k)){m.remove();markers.delete(k)}
  // eigene Position
  if(hasPos(S.self)){const ll=[S.self.lat,S.self.lon];if(!selfMarker)selfMarker=L.marker(ll,{icon:L.divIcon({className:'',html:'<div class="mk mk-self">ICH</div>',iconSize:[26,26],iconAnchor:[13,13]}),zIndexOffset:1000}).addTo(map).bindTooltip('Eigene Position: '+esc(S.self.name));else selfMarker.setLatLng(ll)}
  else if(selfMarker){selfMarker.remove();selfMarker=null}
  // Nachbar-Linien
  neighLayer.clearLayers();let nl=0;
  if($('#mNeigh').checked&&hasPos(S.self)){
    for(const [h,e] of S.neighbors){const l=nodesByHash(h).filter(hasPos);if(l.length!==1)continue;const n=l[0];const avg=e.snrSum/e.n;
      L.polyline([[S.self.lat,S.self.lon],[n.lat,n.lon]],{color:avg>=5?'#2da44e':avg>=-5?'#d29922':'#cf222e',weight:3,opacity:.75}).bindTooltip(`${esc(n.name)}: Ø SNR ${avg.toFixed(1)} dB (${e.n}×)`).addTo(neighLayer);nl++}
  }
  $('#mapInfo').textContent=`${cnt} Knoten mit Position · ${nl} Nachbar-Linien`+(hasPos(S.self)?'':' · eigene Position unbekannt');
  if(!fitted&&(cnt||selfMarker)){fitAll();centerMe();fitted=true}
}
// Beim Aufrufen der Karte: eigene Position in die Mitte (Zoom bleibt, beim ersten Mal passend zu allen Knoten)
function centerMe(){if(map&&hasPos(S.self))map.setView([S.self.lat,S.self.lon],map.getZoom()||10)}
function fitAll(){if(!map)return;const pts=[...markers.values()].map(m=>m.getLatLng());if(selfMarker)pts.push(selfMarker.getLatLng());if(pts.length)map.fitBounds(L.latLngBounds(pts).pad(.15),{maxZoom:13})}
function showPathOnMap(id){
  const p=S.packets.find(x=>x.id===id)||(S.extraPkt?.id===id&&S.extraPkt);if(!p)return;switchTab('map');
  setTimeout(()=>{
    if(!map)return;
    pathLayer.clearLayers();const pts=[],labels=[];let unres=0;
    if(p.ptype===4&&hasPos(p.dec)){pts.push([p.dec.lat,p.dec.lon]);labels.push('Start: '+(p.dec.name||'?'))}
    p.path.forEach((h,i)=>{const x=hopInfo(p,i),n=x.key&&S.nodes.get(x.key);  // Zuordnung mehrdeutiger Hops macht der Server
      if(hasPos(n)){pts.push([n.lat,n.lon]);labels.push(`Hop ${i+1}: ${n.name} (${h})${x.guess?' – vermutet':''}`)}else unres++});
    if(hasPos(S.self)){pts.push([S.self.lat,S.self.lon]);labels.push('Empfänger (ich)')}
    if(pts.length<2){toast('Für diesen Pfad sind zu wenige Positionen bekannt'+(unres?` (${unres} Hops unbekannt)`:''),'err');return}
    L.polyline(pts,{color:'#bf3989',weight:4,dashArray:'8 6'}).addTo(pathLayer);
    pts.forEach((pt,i)=>L.circleMarker(pt,{radius:6,color:'#bf3989',fillOpacity:1}).bindTooltip(esc(labels[i]),{permanent:i===0||i===pts.length-1,direction:'top'}).addTo(pathLayer));
    map.fitBounds(L.latLngBounds(pts).pad(.2));
    if(unres)toast(unres+' Hop(s) ohne bekannte Position übersprungen');
  },60);
}
// ---------- Pakete animieren (live und Wiedergabe) ----------
const ACOL={4:'#2da44e',5:'#58a6ff',2:'#bf3989'};  // Advert, Kanal, Direkt; sonst grau
let animN=0;
function animate(pts,ptype,ms=1800){
  if(!map||animN>=60)return;animN++;
  const l=L.polyline(pts,{color:ACOL[ptype]||'#8b98a5',weight:3,className:'pktAnim',interactive:false}).addTo(animLayer);
  const el=l.getElement();if(el){el.setAttribute('pathLength','100');el.style.animationDuration=ms+'ms'}
  setTimeout(()=>{animLayer.removeLayer(l);animN--},ms);
}
// Weg eines Pakets: Absender (Advert) → Hops mit Position (Zuordnung vom Server) → ich
function packetPoints(p){const pts=[];if(p.ptype===4&&hasPos(p.dec))pts.push([p.dec.lat,p.dec.lon]);
  p.path.forEach((h,i)=>{const x=hopInfo(p,i),n=x.key&&S.nodes.get(x.key);if(hasPos(n))pts.push([n.lat,n.lon])});
  if(hasPos(S.self))pts.push([S.self.lat,S.self.lon]);return pts}
// Live: nur auf der Karte und nicht während eine Wiedergabe läuft; Zähler zeigt, ob etwas ankommt
const live={n:0,skip:0};
export function animatePacket(p){if(!map||ui.tab!=='map'||!$('#mAnim').checked||RP.playing||p.ptype===9||document.hidden)return;
  const pts=packetPoints(p);if(pts.length>=2){animate(pts,p.ptype);live.n++}else live.skip++;
  $('#animInfo').textContent=`${live.n} animiert`+(live.skip?` · ${live.skip} ohne bekannten Weg`:'')+(hasPos(S.self)?'':' · eigene Position fehlt')}
// Wiedergabe: Wege vom Server (GET /api/packets/replay), Zeit läuft mit der gewählten Geschwindigkeit
const RP={data:null,on:false,playing:false,t:0,i:0,last:0};
async function loadReplay(){
  stopRP();RP.data=null;$('#rpInfo').textContent='lade…';
  try{RP.data=await api('packets/replay?hours='+$('#rpRange').value,undefined,'GET')}catch(e){$('#rpInfo').textContent=e.message;return}
  const n=RP.data.items.length;$('#rpInfo').textContent=n?`${n.toLocaleString('de-DE')} Wege`+(RP.data.truncated?' (gekürzt)':''):'keine Wege mit bekannten Positionen';
  seekRP(RP.data.since);
}
function seekRP(t){const it=RP.data.items;let lo=0,hi=it.length;while(lo<hi){const m=(lo+hi)>>1;if(it[m][0]<t)lo=m+1;else hi=m}RP.t=t;RP.i=lo;clockRP()}
function frameRP(now){
  if(!RP.playing||!RP.data)return;const end=RP.t+(now-RP.last)*+$('#rpSpeed').value,it=RP.data.items;RP.last=now;let n=0;
  while(RP.i<it.length&&it[RP.i][0]<=end){if(n++<15)animate(it[RP.i][2],it[RP.i][1],1500);RP.i++}
  RP.t=Math.min(end,RP.data.until);clockRP();if(RP.t>=RP.data.until)stopRP();else requestAnimationFrame(frameRP);
}
function playRP(){if(!RP.data||!RP.data.items.length)return;if(RP.t>=RP.data.until)seekRP(RP.data.since);RP.playing=true;RP.last=performance.now();$('#rpPlay').textContent='⏸';requestAnimationFrame(frameRP)}
function stopRP(){RP.playing=false;$('#rpPlay').textContent='⏵'}
function clockRP(){const d=RP.data;if(!d)return;$('#rpPos').value=Math.round((RP.t-d.since)/Math.max(1,d.until-d.since)*1000);
  $('#rpClock').textContent=new Date(RP.t).toLocaleString('de-DE',{weekday:'short',hour:'2-digit',minute:'2-digit'})}
function closeRP(){stopRP();RP.on=false;$('#replayBar').hidden=true;animLayer&&animLayer.clearLayers()}

function zoomTo(key){const n=S.nodes.get(key);switchTab('map');setTimeout(()=>{if(!map||!hasPos(n))return;map.setView([n.lat,n.lon],14);const m=markers.get(key);if(m)m.openPopup()},80)}

export function initMapTab(){
  $$('.mf').forEach(x=>x.onchange=renderMap);['#mLabels','#mNeigh','#mAge'].forEach(s=>$(s).onchange=renderMap);
  $('#btnFit').onclick=fitAll;$('#btnClrPath').onclick=()=>pathLayer&&pathLayer.clearLayers();
  actions.pathOnMap=d=>showPathOnMap(+d.id);
  $('#mAnim').checked=store.get('mcw.mapAnim',false);if($('#mAnim').checked)$('#animInfo').textContent='warte auf Pakete…';$('#mAnim').onchange=e=>{store.set('mcw.mapAnim',e.target.checked);live.n=live.skip=0;$('#animInfo').textContent=e.target.checked?'warte auf Pakete…':''};
  $('#btnReplay').onclick=()=>{RP.on=true;$('#replayBar').hidden=false;loadReplay()};
  $('#rpPlay').onclick=()=>RP.playing?stopRP():playRP();$('#rpRange').onchange=loadReplay;$('#rpClose').onclick=closeRP;
  $('#rpPos').oninput=e=>{const d=RP.data;if(d)seekRP(d.since+(d.until-d.since)*e.target.value/1000)};
  actions.zoomTo=d=>zoomTo(d.key);
  onShow('map',()=>{initMap();setTimeout(()=>{if(!map)return;map.invalidateSize();if(fitted)centerMe();renderMap()},30)});
  onRender('map',renderMapSoon);
}
