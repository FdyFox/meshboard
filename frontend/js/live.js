// Live-Traffic: Pakettabelle, Detailansicht, Statistik
import {$,$$,esc,tfmt,snrCls,hasPos,hav,PT,ROUTES,NTYPE,hexSpaced,chTitle,toast} from './util.js';
import {S,MAX_PKTS,MAX_ROWS,nodeName,hopInfo,hopTitle,actions,ui,onRender} from './state.js';
import {api,run,downloadUrl} from './api.js';

export function pktInfo(p){
  const d=p.dec||{};
  switch(p.ptype){
    case 4:{const self=S.self&&d.key===S.self.key;let s=(self?'⟲ Eigenes Advert: ':'')+'<b>'+esc(d.name||'(ohne Name)')+'</b> · '+NTYPE[d.ntype??0]+(hasPos(d)?' · 📍':'');
      if(d.key)s+=' <span class="muted mono">'+d.key.slice(0,8)+'</span>';return s}
    case 3:return 'ACK '+(d.ack||'');
    case 0:case 1:case 2:case 8:{if(!d.dst)return '';const dn=nodeName(d.dst),sn=nodeName(d.src);return `${esc(sn||d.src)} → ${esc(dn||d.dst)}`}
    case 7:{const n=d.srcKey&&S.nodes.get(d.srcKey);return `Anon von ${esc(n?n.name:(d.srcKey||'').slice(0,8))} → ${esc(nodeName(d.dst)||d.dst)}`}
    case 5:case 6:return d.chName?'Kanal <b>'+esc(chTitle(d.chName))+'</b>'+(d.room?' <span class="muted">(gehört, nicht abonniert)</span>':''):'Kanal-Hash '+(d.ch||'?')+' (unbekannt)';
    case 9:return 'Trace '+(d.tag||'');
  }
  return '';
}
function passFilter(p){
  const t=$('#fType').value,r=$('#fRoute').value,q=$('#fText').value.trim().toLowerCase();
  if(t&&PT[p.ptype]!==t)return false;if(r&&ROUTES[p.route]!==r)return false;
  if(q){const s=(pktInfo(p)+' '+p.path.join(' ')+' '+(p.dec.key||'')+' '+(p.dec.name||'')).toLowerCase();if(!s.includes(q))return false}
  return true;
}
function pathHtml(p){
  if(p.ptype===9)return '<span class="muted">Trace</span>';
  if(!p.hopCount)return '<span class="muted">0</span>'+(p.hs>1?` <span class="muted mono">${p.hs}B</span>`:'');
  return p.path.map((h,i)=>{const x=hopInfo(p,i);return `<span class="hash${x.name?' known':''}${x.guess?' guess':''}" title="${esc(hopTitle(x))}">${h}</span>`}).join('')+` <span class="muted mono" title="Pfad-Hash-Größe">${p.hs}B</span>`;
}
const tcHex=p=>p.tc[0].toString(16).padStart(4,'0');
function rowHtml(p){
  const ty=PT[p.ptype];
  return `<td class="mono">${tfmt(p.t)}</td><td><span class="pt pt-${ty}">${ty}</span></td><td class="mono">${ROUTES[p.route]}${p.region?' <span class="hash known">#'+esc(p.region)+'</span>':p.tc?' <span class="hash" title="unbekannte Region">?'+tcHex(p)+'</span>':''}</td><td>${pathHtml(p)}</td><td class="mono ${snrCls(p.snr)}">${p.snr.toFixed(1)}</td><td class="mono">${p.rssi}</td><td class="mono">${p.len}</td><td>${pktInfo(p)}</td>`;
}
function prependRow(p){
  const tb=$('#pkts'),tr=document.createElement('tr');tr.dataset.id=p.id;tr.innerHTML=rowHtml(p);tb.prepend(tr);
  while(tb.children.length>MAX_ROWS)tb.lastChild.remove();$('#liveEmpty').style.display='none';
}
export function renderLive(){
  const tb=$('#pkts');const list=S.packets.filter(passFilter).slice(-MAX_ROWS).reverse();
  tb.innerHTML=list.map(p=>`<tr data-id="${p.id}"${S.selPkt===p.id?' class="sel"':''}>${rowHtml(p)}</tr>`).join('');
  $('#liveEmpty').style.display=S.packets.length?'none':'';
}
// Neues Paket vom Server (Knoten, Nachbarn und Statistik hat der Server bereits aktualisiert)
export function addPacket(p){
  const last=S.packets[S.packets.length-1];if(last&&p.id<=last.id)return;
  S.packets.push(p);if(S.packets.length>MAX_PKTS)S.packets.splice(0,S.packets.length-MAX_PKTS);
  S.stats.total++;const ty=PT[p.ptype];S.stats.byType[ty]=(S.stats.byType[ty]||0)+1;
  const m=Math.floor(p.t/60000);S.minutes.set(m,(S.minutes.get(m)||0)+1);for(const k of S.minutes.keys())if(k<m-60)S.minutes.delete(k);
  if(!S.paused&&passFilter(p))prependRow(p);
  renderStatsSoon();
}
export async function showDetail(id){
  let p=S.packets.find(x=>x.id===id);
  if(!p){try{p=S.extraPkt=await api('packets/'+id,undefined,'GET')}catch(e){toast(e.message,'err');return}}  // Direktlink auf ein älteres Paket
  S.selPkt=id;history.replaceState(null,'','#live/'+id);
  $$('#pkts tr').forEach(tr=>tr.classList.toggle('sel',+tr.dataset.id===id));
  const d=p.dec||{},kv=[['Zeit',new Date(p.t).toLocaleString('de-DE')],['Typ',PT[p.ptype]+' (v'+(p.ver+1)+')'],['Route',ROUTES[p.route]],['SNR / RSSI',p.snr.toFixed(2)+' dB / '+p.rssi+' dBm'],['Größe',p.len+' Byte'],['Hash-Größe',p.hs+' Byte']];
  if(p.tc)kv.push(['Region',p.region?'#'+esc(p.region):'unbekannt (Code '+tcHex(p)+')']);
  if(p.hopCount&&p.ptype!==9)kv.push(['Pfad',p.path.map((h,i)=>{const x=hopInfo(p,i);return h+(x.name?' ('+esc(x.name)+(x.guess?'?':'')+')':'')}).join('<br>')+(p.res?.some(r=>r[1]>1)?'<br><span class="muted small">? = vermutet: mehrere Knoten mit diesem Hash, gewählt nach Lage</span>':'')]);
  if(d.name)kv.push(['Name',esc(d.name)]);if(d.key)kv.push(['Public Key','<span class="mono">'+d.key+'</span>']);
  if(d.ntype!=null)kv.push(['Knotentyp',NTYPE[d.ntype]]);if(hasPos(d))kv.push(['Position',d.lat.toFixed(5)+', '+d.lon.toFixed(5)+(hasPos(S.self)?' ('+hav(S.self.lat,S.self.lon,d.lat,d.lon).toFixed(1)+' km)':'')]);
  if(d.ts)kv.push(['Advert-Zeit',new Date(d.ts*1000).toLocaleString('de-DE')]);
  if(d.dst)kv.push(['Ziel-Hash',d.dst+(nodeName(d.dst)?' ('+esc(nodeName(d.dst))+')':'')]);if(d.src)kv.push(['Quell-Hash',d.src+(nodeName(d.src)?' ('+esc(nodeName(d.src))+')':'')]);
  if(d.ch)kv.push(['Kanal-Hash',d.ch+(d.chName?' ('+esc(chTitle(d.chName))+')':'')]);if(d.ack)kv.push(['ACK',d.ack]);
  const canMap=(p.hopCount&&p.ptype!==9)||hasPos(d);
  $('#detail').innerHTML=`<h3>Paket #${p.id} <button class="sm" style="float:right" data-act="closeDetail">✕</button></h3><div class="kv">${kv.map(([k,v])=>`<div>${k}</div><div>${v}</div>`).join('')}</div>
   <div class="row">${canMap?`<button class="blue sm" data-act="pathOnMap" data-id="${p.id}">🗺 Pfad auf Karte</button>`:''}<button class="sm" data-act="copyPktLink" data-id="${p.id}" title="Direktlink auf dieses Paket kopieren">🔗 Link</button></div>
   <h4 class="muted" style="margin:12px 0 4px;font-size:12px">Rohdaten</h4><div class="hex" id="pktHex">${hexSpaced(p.raw)}</div><div id="pktLegend"></div>`;
  $('#detail').classList.add('show');
  bytesView(p);
}
// Rohdaten farbig nach Abschnitten (Aufteilung liefert der Server)
async function bytesView(p){
  let segs;try{segs=await api('packets/layout?raw='+p.raw,undefined,'GET')}catch{return}
  if(S.selPkt!==p.id||!$('#pktHex'))return;
  const hx=i=>p.raw.slice(2*i,2*i+2),sg=(i,s)=>`sg${s[0].startsWith('Hop ')?'h':i%6}`;
  $('#pktHex').innerHTML=segs.map((s,i)=>`<span class="seg ${sg(i,s)}" data-i="${i}" title="${esc(s[0])} · ${s[2]-s[1]} Byte">${[...Array(s[2]-s[1])].map((_,k)=>hx(s[1]+k)).join(' ')}</span>`).join(' ');
  $('#pktLegend').innerHTML='<div class="seglg">'+segs.map((s,i)=>`<div data-i="${i}"><i class="seg ${sg(i,s)}"></i>${esc(s[0])} <span class="muted">${s[2]-s[1]} B</span></div>`).join('')+'</div>';
  const hl=(i,on)=>$$(`#detail [data-i="${i}"]`).forEach(e=>e.classList.toggle('on',on));
  $$('#detail [data-i]').forEach(e=>{e.onpointerenter=()=>hl(e.dataset.i,true);e.onpointerleave=()=>hl(e.dataset.i,false)});
}
// Statistik
let statT=null;function renderStatsSoon(){if(!statT)statT=setTimeout(()=>{statT=null;renderStats()},500)}
export function renderStats(){
  const st=S.stats,recent=S.packets.slice(-50),avg=recent.length?recent.reduce((a,p)=>a+p.snr,0)/recent.length:null;
  const m=Math.floor(Date.now()/60000),last=(S.minutes.get(m)||0)+(S.minutes.get(m-1)||0);
  const types=Object.entries(st.byType).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<span class="pt pt-${k}">${k}</span> ${v}`).join(' ');
  $('#statsbar').innerHTML=`<span>Pakete <b>${st.total}</b></span><span>~<b>${(last/2).toFixed(1)}</b>/min</span><span>Ø SNR (50) <b class="${snrCls(avg)}">${avg==null?'–':avg.toFixed(1)}</b></span><span>Nachbarn <b>${S.neighbors.size}</b></span><canvas id="spark" width="240" height="34" title="Pakete pro Minute (60 min)"></canvas><span>${types}</span>`;
  drawSpark();
}
export function drawSpark(){
  const c=$('#spark');if(!c)return;const g=c.getContext('2d'),m=Math.floor(Date.now()/60000),vals=[];for(let i=59;i>=0;i--)vals.push(S.minutes.get(m-i)||0);
  const mx=Math.max(1,...vals),w=c.width/60;g.clearRect(0,0,c.width,c.height);
  g.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--accent');vals.forEach((v,i)=>{const h=Math.max(v?2:0,v/mx*(c.height-2));g.fillRect(i*w,c.height-h,w-1,h)});
}

export function initLive(){
  PT.forEach(t=>{if(!/^T1/.test(t)){const o=document.createElement('option');o.textContent=t;$('#fType').appendChild(o)}});
  ['#fType','#fRoute'].forEach(s=>$(s).onchange=renderLive);$('#fText').oninput=renderLive;
  $('#btnPause').onclick=()=>{S.paused=!S.paused;$('#btnPause').textContent=S.paused?'▶ Weiter':'⏸ Pause';if(!S.paused)renderLive()};
  $('#btnClear').onclick=()=>run('packets/clear');
  $('#btnCsv').onclick=()=>{location.href=downloadUrl('packets/export?fmt=csv')};
  $('#btnJson').onclick=()=>{location.href=downloadUrl('packets/export?fmt=json')};
  $('#pkts').addEventListener('click',e=>{const tr=e.target.closest('tr');if(tr)showDetail(+tr.dataset.id)});
  actions.closeDetail=()=>{$('#detail').classList.remove('show');S.selPkt=null;history.replaceState(null,'','#live')};
  actions.copyPktLink=d=>{const u=location.origin+location.pathname+'#live/'+d.id;
    (navigator.clipboard?.writeText(u)||Promise.reject()).then(()=>toast('Link kopiert','ok'),()=>prompt('Link zum Paket:',u))};
  onRender('live',renderStats);
}
