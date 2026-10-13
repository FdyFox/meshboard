// Karte (Leaflet): Knoten, Nachbar-Linien, Paketpfade, eigene Position
import {$,$$,esc,ago,hav,hasPos,NTYPE,NLETTER,store,toast} from './util.js';
import {S,nodesByHash,lastSeen,actions,onRender,onShow,switchTab} from './state.js';
import {baseLayers,defaultBase} from './basemaps.js';

let map=null,markers=new Map(),selfMarker=null,neighLayer=null,pathLayer=null,fitted=false;
function initMap(){
  if(map||typeof L==='undefined'){if(typeof L==='undefined')$('#map').innerHTML='<div class="empty">Leaflet konnte nicht geladen werden (offline?).</div>';return}
  map=L.map('map',{preferCanvas:false}).setView([49.38,6.95],9);
  const base=baseLayers(),saved=store.get('mcw.basemap',null);
  (base[saved]||defaultBase(base)).addTo(map);
  map.on('baselayerchange',e=>store.set('mcw.basemap',e.name));
  L.control.layers(base,null,{position:'topleft'}).addTo(map);
  L.control.scale({imperial:false}).addTo(map);
  neighLayer=L.layerGroup().addTo(map);pathLayer=L.layerGroup().addTo(map);
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
   (ct?(ct.type===1||ct.type===3?`<button class="sm" data-act="openChat" data-key="${n.key}">💬 Chat</button> `:'')+'<span class="muted">im Gerät gespeichert</span>':'<span class="muted">nicht in Kontakten</span>');
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
    else{m.setLatLng([n.lat,n.lon]);m.setIcon(icon(n,old))}
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
  if(!fitted&&cnt){fitAll();fitted=true}
}
function fitAll(){if(!map)return;const pts=[...markers.values()].map(m=>m.getLatLng());if(selfMarker)pts.push(selfMarker.getLatLng());if(pts.length)map.fitBounds(L.latLngBounds(pts).pad(.15),{maxZoom:13})}
function showPathOnMap(id){
  const p=S.packets.find(x=>x.id===id);if(!p)return;switchTab('map');
  setTimeout(()=>{
    if(!map)return;
    pathLayer.clearLayers();const pts=[],labels=[];let unres=0;
    if(p.ptype===4&&hasPos(p.dec)){pts.push([p.dec.lat,p.dec.lon]);labels.push('Start: '+(p.dec.name||'?'))}
    p.path.forEach((h,i)=>{const l=nodesByHash(h).filter(hasPos);let n=null;
      if(l.length===1)n=l[0];else if(l.length>1&&pts.length){const last=pts[pts.length-1];n=l.sort((a,b)=>hav(last[0],last[1],a.lat,a.lon)-hav(last[0],last[1],b.lat,b.lon))[0]}
      if(n){pts.push([n.lat,n.lon]);labels.push(`Hop ${i+1}: ${n.name} (${h})${l.length>1?' – mehrdeutig':''}`)}else unres++});
    if(hasPos(S.self)){pts.push([S.self.lat,S.self.lon]);labels.push('Empfänger (ich)')}
    if(pts.length<2){toast('Für diesen Pfad sind zu wenige Positionen bekannt'+(unres?` (${unres} Hops unbekannt)`:''),'err');return}
    L.polyline(pts,{color:'#bf3989',weight:4,dashArray:'8 6'}).addTo(pathLayer);
    pts.forEach((pt,i)=>L.circleMarker(pt,{radius:6,color:'#bf3989',fillOpacity:1}).bindTooltip(esc(labels[i]),{permanent:i===0||i===pts.length-1,direction:'top'}).addTo(pathLayer));
    map.fitBounds(L.latLngBounds(pts).pad(.2));
    if(unres)toast(unres+' Hop(s) ohne bekannte Position übersprungen');
  },60);
}
function zoomTo(key){const n=S.nodes.get(key);switchTab('map');setTimeout(()=>{if(!map||!hasPos(n))return;map.setView([n.lat,n.lon],14);const m=markers.get(key);if(m)m.openPopup()},80)}

export function initMapTab(){
  $$('.mf').forEach(x=>x.onchange=renderMap);['#mLabels','#mNeigh','#mAge'].forEach(s=>$(s).onchange=renderMap);
  $('#btnFit').onclick=fitAll;$('#btnClrPath').onclick=()=>pathLayer&&pathLayer.clearLayers();
  actions.pathOnMap=d=>showPathOnMap(+d.id);
  actions.zoomTo=d=>zoomTo(d.key);
  onShow('map',()=>{initMap();setTimeout(()=>{map&&map.invalidateSize();renderMap()},30)});
  onRender('map',renderMapSoon);
}
