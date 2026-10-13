// Statistik aus dem gespeicherten Verlauf (Server: GET /api/stats), gegliedert in Unterseiten
import {$,$$,esc,ago,snrCls,store,hasPos,NTYPE,toast} from './util.js';
import {S,onShow,onRender,ui,actions} from './state.js';
import {api,run} from './api.js';
import {baseLayers,defaultBase} from './basemaps.js';

let data=null,loading=false,timer=null,page=store.get('mcw.statsPage','overview');
const hp=location.hash.match(/^#stats\/(\w+)/);if(hp)page=hp[1];  // Direktlink auf eine Unterseite
let startNode=(location.hash.match(/[?&](node|hash)=([0-9a-f]+)/)||[]).slice(1);  // …und auf ein Detailfenster
const fmtN=n=>n==null?'–':n>=100000?Math.round(n/1000).toLocaleString('de-DE')+' Tsd.':Math.round(n).toLocaleString('de-DE');
const fmt1=v=>v==null||isNaN(v)?'–':v.toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1});
const fmtPct=v=>v==null||isNaN(v)?'–':(v<10?v.toLocaleString('de-DE',{maximumFractionDigits:2}):fmt1(v))+' %';
const fmtKm=v=>v==null?'–':fmt1(v)+' km';
const fmtDur=s=>s==null?'–':s<120?fmt1(s)+' s':s<7200?fmt1(s/60)+' min':fmt1(s/3600)+' h';
const WD=['Mo','Di','Mi','Do','Fr','Sa','So'];
const empty='<div class="muted small">keine Daten im Zeitraum</div>';
const ntype=t=>t==null?'unbekannt':NTYPE[t]||'unbekannt';

// ---------- Bausteine ----------
// Tooltip (eine Instanz, Inhalt per textContent; erste Zeile = Wert)
function tip(e,lines){
  let t=$('#vizTip');if(!t){t=document.createElement('div');t.id='vizTip';document.body.appendChild(t)}
  t.replaceChildren(...lines.map((l,i)=>{const d=document.createElement('div');d.textContent=l;if(i===0)d.className='v';return d}));
  t.style.display='block';const r=t.getBoundingClientRect();
  t.style.left=Math.max(8,Math.min(innerWidth-r.width-8,e.clientX+12))+'px';t.style.top=Math.max(8,e.clientY-r.height-10)+'px';
}
const hideTip=()=>{const t=$('#vizTip');if(t)t.style.display='none'};
const niceStep=v=>{const p=10**Math.floor(Math.log10(v)),f=v/p;return (f<=1?1:f<=2?2:f<=5?5:10)*p};
// Achsenbereich mit glatten Werten; ab0: Mengen beginnen immer bei 0
function scale(vals,ab0){
  let lo=Math.min(...vals),hi=Math.max(...vals);if(ab0)lo=Math.min(0,lo);
  if(hi===lo){hi+=1;if(!ab0)lo-=1}
  const st=niceStep((hi-lo)/2);return [Math.floor(lo/st)*st,Math.ceil(hi/st)*st];
}
function frame(W,H,pl,pt,ih,lo,hi,fmt){
  const y=v=>pt+ih-(v-lo)/(hi-lo)*ih;let g='';
  [lo,(lo+hi)/2,hi].forEach(v=>{g+=`<line x1="${pl}" x2="${W}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${pl-6}" y="${y(v)+4}" class="ax" text-anchor="end">${fmt(v)}</text>`});
  return [g,y];
}
const xTicks=(pts,W,pl)=>Math.ceil(pts.length/Math.max(2,Math.floor((W-pl)/72)));
function hover(el,pts,onIdx){
  el.querySelectorAll('.hit').forEach(h=>{const i=+h.dataset.i;
    h.onpointermove=e=>{onIdx&&onIdx(i);h.classList.add('on');tip(e,pts[i].tip)};
    h.onpointerleave=()=>{onIdx&&onIdx(-1);h.classList.remove('on');hideTip()}});
}
// Säulen (eine Reihe): pts=[{label,v,tip}]
function colChart(el,pts,fmt=fmtN,H=170){
  if(!pts.length||pts.every(p=>!p.v)){el.innerHTML=empty;return}
  const W=Math.max(240,el.clientWidth),pl=46,pt=8,pb=22,n=pts.length,ih=H-pt-pb,slot=(W-pl)/n,bw=Math.max(2,Math.min(24,slot-2));
  const [lo,hi]=scale(pts.map(p=>p.v||0),true),[g0,y]=frame(W,H,pl,pt,ih,lo,hi,fmt);let g=g0;const every=xTicks(pts,W,pl);
  pts.forEach((p,i)=>{
    const x=pl+i*slot+(slot-bw)/2,top=y(p.v||0),h=pt+ih-top,r=Math.min(4,bw/2,h);
    if(h>0)g+=h>r?`<path class="bar" d="M${x},${pt+ih}V${top+r}Q${x},${top} ${x+r},${top}H${x+bw-r}Q${x+bw},${top} ${x+bw},${top+r}V${pt+ih}Z"/>`:`<rect class="bar" x="${x}" y="${top}" width="${bw}" height="${h}"/>`;
    if(i%every===0)g+=`<text x="${x+bw/2}" y="${H-6}" class="ax" text-anchor="middle">${esc(p.label)}</text>`;
    g+=`<rect class="hit" data-i="${i}" x="${pl+i*slot}" y="${pt}" width="${slot}" height="${ih}"/>`;
  });
  el.innerHTML=`<svg width="${W}" height="${H}" role="img">${g}</svg>`;hover(el,pts);
}
// Linie (eine Reihe, Lücken bei fehlenden Werten) mit Fadenkreuz
function lineChart(el,pts,fmt=fmt1,H=170){
  const vals=pts.map(p=>p.v).filter(v=>v!=null);
  if(!vals.length){el.innerHTML=empty;return}
  const W=Math.max(240,el.clientWidth),pl=46,pt=8,pb=22,n=pts.length,ih=H-pt-pb,slot=(W-pl)/n;
  const [lo,hi]=scale(vals,false),[g0,y]=frame(W,H,pl,pt,ih,lo,hi,fmt);let g=g0;const every=xTicks(pts,W,pl);
  const x=i=>pl+i*slot+slot/2;let d='';
  pts.forEach((p,i)=>{if(p.v==null)return;d+=(i&&pts[i-1].v!=null?'L':'M')+x(i)+','+y(p.v)});
  g+=`<path class="line" d="${d}"/>`;
  pts.forEach((p,i)=>{if(p.v!=null&&(i===0||pts[i-1].v==null)&&(i===n-1||pts[i+1].v==null))g+=`<circle class="dot" cx="${x(i)}" cy="${y(p.v)}" r="3"/>`});
  pts.forEach((p,i)=>{if(i%every===0)g+=`<text x="${x(i)}" y="${H-6}" class="ax" text-anchor="middle">${esc(p.label)}</text>`;
    g+=`<rect class="hit" data-i="${i}" x="${pl+i*slot}" y="${pt}" width="${slot}" height="${ih}"/>`});
  g+=`<line class="xhair" x1="0" x2="0" y1="${pt}" y2="${pt+ih}" style="display:none"/><circle class="dot hov" r="4" style="display:none"/>`;
  el.innerHTML=`<svg width="${W}" height="${H}" role="img">${g}</svg>`;
  const xh=el.querySelector('.xhair'),dot=el.querySelector('.dot.hov');
  hover(el,pts,i=>{if(i<0||pts[i].v==null){xh.style.display=dot.style.display='none';return}
    xh.setAttribute('x1',x(i));xh.setAttribute('x2',x(i));xh.style.display='';dot.setAttribute('cx',x(i));dot.setAttribute('cy',y(pts[i].v));dot.style.display=''});
}
// Horizontale Balken mit Wert (und Anteil) am Ende: items=[[label,value]]
function hBars(el,items,total){
  if(!items.length){el.innerHTML=empty;return}
  const max=Math.max(...items.map(x=>x[1]));
  el.innerHTML=items.map(([l,v])=>`<div class="hb"><span class="hb-l" title="${esc(l)}">${esc(l)}</span><span class="hb-t"><span class="hb-b" style="width:${Math.max(1,v/max*100)}%"></span></span><span class="hb-v">${fmtN(v)}${total?` <span class="muted">${Math.round(v/total*100)} %</span>`:''}</span></div>`).join('');
}
// Kompakte Heatmap Wochentag × Uhrzeit (Ortszeit), eine Farbe hell→dunkel
const STEPS=[12,30,50,72,100];
function heatmap(el,hourly){
  if(!hourly.length){el.innerHTML=empty;return}
  const g=WD.map(()=>Array(24).fill(0));
  hourly.forEach(([h,c])=>{const d=new Date(h*3600000);g[(d.getDay()+6)%7][d.getHours()]+=c});
  const max=Math.max(1,...g.flat()),bg=s=>`color-mix(in srgb,var(--accent2) ${s}%,var(--panel2))`;
  let h='<div class="hm"><div></div>'+[...Array(24)].map((_,i)=>`<div class="hm-h">${i%6===0?i:''}</div>`).join('');
  g.forEach((row,wd)=>{h+=`<div class="hm-d">${WD[wd]}</div>`+row.map((v,hr)=>`<div class="hm-c" data-wd="${wd}" data-hr="${hr}" data-v="${v}"${v?` style="background:${bg(STEPS[Math.min(4,Math.floor(v/max*5))])}"`:''}></div>`).join('')});
  el.innerHTML=h+'</div><div class="hm-leg muted small">wenig '+STEPS.map(s=>`<i style="background:${bg(s)}"></i>`).join('')+' viel</div>';
  el.querySelectorAll('.hm-c').forEach(c=>{c.onpointermove=e=>tip(e,[fmtN(+c.dataset.v)+' Pakete',`${WD[c.dataset.wd]} ${c.dataset.hr}–${+c.dataset.hr+1} Uhr, Summe im Zeitraum`]);c.onpointerleave=hideTip});
}
const table=(head,rows)=>rows.length?`<div class="tblwrap"><table><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:empty;
const kpi=(l,v,dl='',sub='')=>`<div class="kpi"><div class="kpi-l">${l}</div><div class="kpi-v">${v}</div>${dl}${sub?`<div class="kpi-s" title="${esc(sub)}">${esc(sub)}</div>`:''}</div>`;
const card=(title,body,cls='',note='')=>`<div class="card ${cls}"><h3>${title}</h3>${body}${note?`<p class="muted small">${note}</p>`:''}</div>`;
function delta(cur,prev){if(prev==null||!prev||cur==null)return '';const p=(cur-prev)/prev*100;return `<div class="kpi-d">${p>=0?'▲':'▼'} ${fmt1(Math.abs(p))} % ggü. Vorzeitraum</div>`}

const isoWeek=d=>{const t=new Date(Date.UTC(d.getFullYear(),d.getMonth(),d.getDate()));t.setUTCDate(t.getUTCDate()+4-(t.getUTCDay()||7));return Math.ceil(((t-Date.UTC(t.getUTCFullYear(),0,1))/86400000+1)/7)};
function xLabel(t,size){const d=new Date(t);
  if(size<=3600000)return d.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
  if(size<86400000)return d.toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit'})+' '+d.getHours()+'h';
  if(size>86400000)return 'KW '+isoWeek(d);
  return d.toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit'})}

// ---------- abgeleitete Werte ----------
function derive(d){
  const c=d.cur,now=Date.now(),size=d.bucketMs;
  const dur=Math.max(60000,now-Math.max(d.since,c.first||now));       // tatsächlich aufgezeichnete Dauer
  const days=Math.max(1/24,dur/86400000);
  const unit=size<=3600000?'Stunde':size<86400000?'6 Stunden':size<=86400000?'Tag':'Woche';
  const when=t=>new Date(t).toLocaleString('de-DE',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  const lbl=t=>xLabel(t,size);
  const dev=d.device&&d.device.samples>=2?d.device:null;
  const occ=c.air!=null?c.air/dur*100:null,occPrev=d.prev&&d.prev.air!=null?d.prev.air/(now-d.since)*100:null;
  return {c,dur,days,unit,when,lbl,size,dev,occ,occPrev};
}
function hints(d,x){
  const h=[],warn=(t)=>h.push(['⚠',t]),info=(t)=>h.push(['ℹ',t]);
  if(x.occ!=null&&x.occ>25)warn(`Kanalbelegung sehr hoch (${fmtPct(x.occ)}). Ab etwa 25 % häufen sich Kollisionen.`);
  else if(x.occ!=null&&x.occ>10)info(`Kanalbelegung erhöht (${fmtPct(x.occ)}).`);
  const lim=d.duty.limit;
  if(lim&&d.duty.hour!=null&&d.duty.hour>lim*.8)warn(`Eigene Sendezeit in der letzten Stunde ${fmtPct(d.duty.hour)} – nahe an der Grenze von ${fmtPct(lim)}.`);
  if(x.days>=1)d.nodesTop.filter(n=>n.adverts/x.days>24).slice(0,3).forEach(n=>warn(`${n.name||n.key.slice(0,8)} sendet etwa ${fmt1(n.adverts/x.days)} Adverts pro Tag – das belastet das ganze Netz.`));
  const rg=d.regions.reduce((a,r)=>a+r[1],0),unk=(d.regions.find(r=>r[0]==='?')||[0,0])[1];
  if(rg>=20&&unk/rg>.25)info(`${Math.round(unk/rg*100)} % der Pakete mit Region gehören zu einer unbekannten Region – Namen unter Gerät › „Weitere Regionen“ ergänzen.`);
  const unkCh=d.channels.filter(c=>/^[0-9a-f]{2}$/.test(c[0]));
  if(unkCh.length)info(`${unkCh.length} unbekannte Kanäle gehört (${unkCh.map(c=>'Hash '+c[0]).slice(0,4).join(', ')}) – im Chat mit „#Raum suchen“ prüfen.`);
  if(x.dev){const ns=x.dev.buckets.map(b=>b.noise).filter(v=>v!=null),last=ns[ns.length-1],avg=ns.reduce((a,b)=>a+b,0)/ns.length;
    if(last!=null&&last>-95)warn(`Rauschpegel hoch (${Math.round(last)} dBm) – Störquelle in der Nähe?`);
    else if(last!=null&&ns.length>4&&last-avg>6)info(`Rauschpegel um ${fmt1(last-avg)} dB über dem Durchschnitt.`);
    const b=x.dev.last&&x.dev.last.batt;if(b&&b<3500)warn(`Batterie niedrig (${fmt1(b/1000)} V).`)}
  const col=d.collisions,b=(col.mode??0)+1,cn=col['b'+b].length;
  if(cn){const nx=b<3?col['b'+(b+1)].length:null;
    info(`${cn} Hop-Hash${cn===1?'':'es'} (${b} Byte) teilen sich mehrere aktive Repeater – auf diesen Hops ist der Weg nicht eindeutig.`+(nx!=null&&nx<cn?` Mit ${b+1}-Byte-Hashes wären es ${nx}.`:''))}
  watched().filter(w=>w.down).forEach(w=>warn(`Beobachteter Knoten ${w.name} seit ${ago(w.since)} nicht gehört.`));
  const dm=d.msgs.dm,all=(dm.ok||0)+(dm.noack||0)+(dm.fail||0);
  if(all>=5&&dm.ok/all<.7)warn(`Nur ${Math.round(dm.ok/all*100)} % der eigenen Direktnachrichten wurden bestätigt – Pfade prüfen oder zurücksetzen.`);
  return h;
}

// ---------- Unterseiten ----------
const gname=n=>n.name?esc(n.name)+(n.guess?' <span class="muted" title="vermutet: mehrere Knoten mit diesem Hash, gewählt nach Lage">?</span>':''):'unbekannt';
// Hash-Kollisionen: Zahlen je Hash-Größe, Tabelle für die Größe des Geräts
function collisions(c){
  const b=(c.mode??0)+1,sum=k=>c[k].reduce((a,g)=>a+g.nodes.length,0);
  const head=[1,2,3].map(i=>`<span class="${i===b?'strong':'muted'}">${i} Byte: ${c['b'+i].length?`${c['b'+i].length} Hash${c['b'+i].length===1?'':'es'} (${sum('b'+i)} Knoten)`:'keine'}</span>`).join(' · ');
  return `<p class="small">${fmtN(c.active)} aktive Repeater/Room-Server · ${head}${c.mode!=null?` · <span class="muted">dein Gerät nutzt ${b} Byte</span>`:''}</p>`+
    (c['b'+b].length?table(['Hash','Knoten','Entfernung','zuletzt'],c['b'+b].map(g=>`<tr><td class="mono">${g.hash}</td><td class="wrap">${g.nodes.map(n=>`<a href="#" data-act="nodeDetail" data-key="${n.key}">${esc(n.name||n.key.slice(0,8))}</a>`).join(', ')}</td><td class="mono">${g.nodes.map(n=>fmtKm(n.km)).join(' / ')}</td><td>${g.nodes.map(n=>ago(n.last)).join(' / ')}</td></tr>`)):'<p class="muted">Keine Kollisionen bei '+b+' Byte.</p>');
}
// ---------- Knoten beobachten ----------
const watched=()=>Object.entries(S.settings.watch||{}).map(([key,w])=>{const n=S.nodes.get(key)||{};return {key,...w,name:n.name||key.slice(0,8),last:Math.max(w.last||0,n.heard||0)}}).sort((a,b)=>b.down-a.down||a.name.localeCompare(b.name));
const fmtH=h=>h>=48&&h%24===0?h/24+' Tage':fmt1(h).replace(/,0$/,'')+' h';
function watchTable(){const l=watched();
  return l.length?table(['Knoten','Status','zuletzt gehört','Schwelle',''],l.map(w=>`<tr><td><a href="#" data-act="nodeDetail" data-key="${w.key}">${esc(w.name)}</a></td><td class="${w.down?'snr-r':'snr-g'}">${w.down?'● verstummt seit '+ago(w.since):'● aktiv'}</td><td>${w.last?ago(w.last):'–'}</td><td class="mono">${fmtH(w.hours)}</td><td><button class="sm" data-act="watch" data-key="${w.key}" title="Schwelle ändern">✎</button> <button class="sm" data-act="unwatch" data-key="${w.key}" title="Nicht mehr beobachten">✕</button></td></tr>`)):'<p class="muted">Noch keine Knoten beobachtet.</p>'}
export const watchBtn=(key,id='ndWatch')=>{const w=(S.settings.watch||{})[key];return `<button class="sm"${id?` id="${id}"`:''} data-act="${w?'unwatch':'watch'}" data-key="${key}" title="${w?'Beobachtung beenden':'Melden, wenn der Knoten länger nicht gehört wird'}">${w?'👁 beobachtet ('+fmtH(w.hours)+') ✕':'👁 Beobachten'}</button>`};
function watchAsk(d){const cur=(S.settings.watch||{})[d.key];
  const v=prompt('Melden, wenn der Knoten so viele Stunden nicht gehört wurde:',cur?String(cur.hours).replace('.',','):'24');if(v==null)return;
  const h=parseFloat(v.replace(',','.'));if(!(h>0))return toast('Bitte eine Zahl eingeben','err');
  run('watch',{key:d.key,hours:h},cur?'Schwelle geändert':'Knoten wird beobachtet','PUT')}

const PAGES={
  overview:{title:'Übersicht',render(d,x){
    const c=d.cur,p=d.prev,lim=d.duty.limit;
    const dm=d.msgs.dm,dmAll=(dm.ok||0)+(dm.noack||0)+(dm.fail||0);
    const best=[...d.neighbors].filter(n=>n.count>=3).sort((a,b)=>b.snr-a.snr)[0];
    const h=hints(d,x);
    return `<div class="kpis">${[
      kpi('Eindeutige Pakete',fmtN(c.unique),delta(c.unique,p&&p.unique),c.unique?`Ø ${fmt1(c.total/c.unique)} Empfänge je Paket · ${fmt1(c.unique/(x.dur/3600000))} pro Stunde`:''),
      kpi('Kanalbelegung',fmtPct(x.occ),delta(x.occ,x.occPrev),'geschätzte Sendezeit aller empfangenen Pakete'),
      kpi('Eigene Sendezeit',d.duty.hour!=null?fmtPct(d.duty.hour):'–','',d.duty.hour!=null?`letzte Stunde${lim?` · Grenze ${fmtPct(lim)} (EU ${fmt1(d.duty.freq)} MHz)`:''}`:'wird ab jetzt alle 5 Minuten aufgezeichnet'),
      kpi('Aktive Knoten',fmtN(c.nodes),delta(c.nodes,p&&p.nodes),`${d.newNodes.length} neu im Zeitraum`),
      kpi('Direkte Nachbarn',fmtN(d.neighbors.length),'',best?`bester Empfang: ${best.name||best.hash} (${fmt1(best.snr)} dB)`:''),
      kpi('Zustellquote DMs',dmAll?Math.round(dm.ok/dmAll*100)+' %':'–','',dmAll?`${dm.ok} von ${dmAll} bestätigt${d.msgs.rttAvg?` · Ø ${fmt1(d.msgs.rttAvg/1000)} s`:''}`:'keine eigenen Direktnachrichten'),
    ].join('')}</div><div class="sgrid">
      ${card('Auffälligkeiten',h.length?`<ul class="hints">${h.map(([i,t])=>`<li><span aria-hidden="true">${i}</span> ${esc(t)}</li>`).join('')}</ul>`:'<p class="muted">Keine Auffälligkeiten im Zeitraum.</p>','wide')}
      ${card('Eindeutige Pakete pro '+x.unit,'<div class="viz" id="cTime"></div>','wide','Jedes Paket zählt einmal, auch wenn es über mehrere Repeater ankommt.')}
    </div>`},
    after(d,x){colChart($('#cTime'),d.timeline.map(b=>({label:x.lbl(b.t),v:b.unique,tip:[fmtN(b.unique)+' eindeutige Pakete',x.when(b.t)+' · '+x.unit,fmtN(b.count)+' Empfänge · '+fmtN(b.adverts)+' Adverts']})))}},

  radio:{title:'Funk & Gerät',render(d,x){
    const t=x.dev&&x.dev.total,lim=d.duty.limit;
    const noDev='<p class="muted small">Gerätewerte werden alle 5 Minuten aufgezeichnet – für diesen Zeitraum liegen noch zu wenige vor.</p>';
    return `<div class="sgrid">
      ${card('Rauschpegel (dBm)',x.dev?'<div class="viz" id="cNoise"></div>':noDev,'','Grundrauschen am Empfänger. Je niedriger, desto besser; ein Anstieg deutet auf Störquellen hin.')}
      ${card('Eigene Sendezeit (Duty-Cycle)',x.dev?'<div class="viz" id="cDuty"></div>':noDev,'',lim?`Anteil der Zeit, in der deine Node sendet. Gesetzliche Grenze bei ${fmt1(d.duty.freq)} MHz: ${fmtPct(lim)} (über eine Stunde gemittelt).`:'Anteil der Zeit, in der deine Node sendet.')}
      ${card('Empfangsqualität direkter Nachbarn (Ø SNR, dB)','<div class="viz" id="cSnrT"></div>','','Signal-Rausch-Abstand der Pakete, die deine Node direkt von Nachbarn empfängt.')}
      ${card('Batterie (V)',x.dev?'<div class="viz" id="cBatt"></div>':noDev)}
      ${card('SNR-Verteilung aller Empfänge (dB)','<div class="viz" id="cSnr"></div>')}
      ${card('Gerätezähler im Zeitraum',t?table(['Wert','Anzahl'],[['Gesendet',t.sent],['davon Flood / Direkt',`${fmtN(t.flood_tx)} / ${fmtN(t.direct_tx)}`],['Empfangen',t.recv],['davon Flood / Direkt',`${fmtN(t.flood_rx)} / ${fmtN(t.direct_rx)}`],['Empfangsfehler',t.rx_err],['Sendezeit',fmtDur(t.tx_air)],['Empfangszeit',fmtDur(t.rx_air)]].map(([k,v])=>`<tr><td>${k}</td><td class="mono">${typeof v==='number'?fmtN(v):v}</td></tr>`)):noDev)}
    </div>`},
    after(d,x){
      lineChart($('#cSnrT'),d.timeline.map(b=>({label:x.lbl(b.t),v:b.snr,tip:[b.snr==null?'keine Daten':fmt1(b.snr)+' dB Ø SNR',x.when(b.t)+' · '+x.unit]})),v=>fmt1(v));
      colChart($('#cSnr'),d.snr.map(([b,v])=>({label:String(b).replace('.',','),v,tip:[fmtN(v)+' Empfänge','SNR '+fmt1(b)+' bis '+fmt1(b+2.5)+' dB']})));
      if(!x.dev)return;
      const B=x.dev.buckets,secs=x.size/1000;
      lineChart($('#cNoise'),d.timeline.map((b,i)=>({label:x.lbl(b.t),v:B[i].noise,tip:[B[i].noise==null?'keine Daten':Math.round(B[i].noise)+' dBm',x.when(b.t)+' · '+x.unit]})),v=>Math.round(v));
      colChart($('#cDuty'),d.timeline.map((b,i)=>({label:x.lbl(b.t),v:B[i].tx_air/secs*100,tip:[fmtPct(B[i].tx_air/secs*100)+' gesendet',x.when(b.t)+' · '+x.unit,fmtDur(B[i].tx_air)+' Sendezeit']})),fmtPct);
      lineChart($('#cBatt'),d.timeline.map((b,i)=>({label:x.lbl(b.t),v:B[i].batt&&B[i].batt/1000,tip:[B[i].batt?fmt1(B[i].batt/1000)+' V':'keine Daten',x.when(b.t)+' · '+x.unit]})),v=>v.toLocaleString('de-DE',{maximumFractionDigits:2}));
    }},

  net:{title:'Netz',render(d,x){
    const c=d.cur;
    return `<div class="sgrid">
      ${card('Kanalbelegung pro '+x.unit,'<div class="viz" id="cAir"></div>','wide','Geschätzte Sendezeit aller empfangenen Pakete im Verhältnis zur Zeit (LoRa-Formel mit deinen Funkparametern). Eigene Sendungen und nicht gehörte Pakete fehlen.')}
      ${card('Empfänge je Paket','<div class="viz" id="cAmp"></div>','','Wie oft dasselbe Paket ankommt. Hohe Werte bedeuten viele Repeater in Reichweite – und mehr Last auf dem Kanal.')}
      ${card('Routen','<div id="cRoutes"></div>','','Flood: wird von allen Repeatern weitergeleitet. Direkt: folgt einem bekannten Pfad und spart Sendezeit.')}
      ${card('Pakettypen','<div id="cTypes"></div>')}
      ${card('Hops (Flood-Pakete)','<div class="viz" id="cHops"></div>','','Über wie viele Repeater Pakete bei dir ankommen.')}
      ${card('Pfad-Hash-Größe','<div id="cHash"></div>','','Byte pro Hop im Pfad. 2 und 3 Byte setzen neuere Firmware voraus; ältere Repeater leiten solche Pakete eventuell nicht weiter.')}
      ${card('Regionen','<div id="cRegions"></div>','','Flood-Pakete mit Regionsmarkierung. „unbekannt“: Region, deren Name dem Server nicht bekannt ist.')}
      ${card('Aktivität nach Wochentag und Uhrzeit','<div id="cHeat"></div>')}
    </div>`},
    after(d,x){
      colChart($('#cAir'),d.timeline.map(b=>({label:x.lbl(b.t),v:b.air/x.size*100,tip:[fmtPct(b.air/x.size*100)+' belegt',x.when(b.t)+' · '+x.unit,fmt1(b.air/1000)+' s Sendezeit']})),fmtPct);
      lineChart($('#cAmp'),d.timeline.map(b=>({label:x.lbl(b.t),v:b.unique?b.count/b.unique:null,tip:[b.unique?fmt1(b.count/b.unique)+' Empfänge je Paket':'keine Daten',x.when(b.t)+' · '+x.unit]})),v=>fmt1(v));
      hBars($('#cRoutes'),d.routes,d.cur.total);hBars($('#cTypes'),d.types,d.cur.total);
      colChart($('#cHops'),d.hops.map(([h,v])=>({label:h>=10?'10+':String(h),v,tip:[fmtN(v)+' Pakete',(h>=10?'10 oder mehr':h)+' Hop'+(h===1?'':'s')]})));
      const hs=d.hashSize.reduce((a,x)=>a+x[1],0);hBars($('#cHash'),d.hashSize.map(([s,v])=>[s+' Byte',v]),hs);
      hBars($('#cRegions'),d.regions.map(([n,v])=>[n==='?'?'unbekannt':'#'+n,v]),d.regions.reduce((a,r)=>a+r[1],0));
      heatmap($('#cHeat'),d.hourly);
    }},

  nodes:{title:'Knoten',render(d,x){
    const per=n=>n.adverts/x.days;
    return `<div class="sgrid">
      ${card('Aktive Knoten pro '+x.unit,'<div class="viz" id="cNodes"></div>','','Knoten mit mindestens einem Advert im Zeitabschnitt.')}
      ${card('Knotentypen','<div id="cNtypes"></div>','','Aktive Knoten im Zeitraum nach Typ.')}
      ${card('Direkte Nachbarn',table(['Hash','Knoten','Typ','Pakete','Ø SNR','Ø RSSI','Entfernung','zuletzt'],d.neighbors.map(n=>`<tr class="click" data-act="nodeDetail" data-hash="${n.hash}" title="Details"><td class="mono">${n.hash}</td><td>${gname(n)}</td><td>${ntype(n.type)}</td><td class="mono">${fmtN(n.count)}</td><td class="mono ${snrCls(n.snr)}">${fmt1(n.snr)}</td><td class="mono">${n.rssi==null?'–':Math.round(n.rssi)}</td><td class="mono">${fmtKm(n.km)}</td><td>${ago(n.last)}</td></tr>`)),'wide','Stationen, die deine Node ohne Umweg hört (letzter Hop). Mehrdeutige Hashes ohne Namen.')}
      ${card('Repeater-Last',table(['Hash','Knoten','Typ','weitergeleitet'],d.repeaters.map(r=>`<tr class="click" data-act="nodeDetail" data-hash="${r.hash}" title="Details"><td class="mono">${r.hash}</td><td>${gname(r)}</td><td>${ntype(r.type)}</td><td class="mono">${fmtN(r.count)}</td></tr>`)),'','Eindeutige Pakete, in deren Pfad der Repeater vorkommt. ? = vermutet: mehrere Knoten mit diesem Hash, gewählt nach Lage.')}
      ${card('Beobachtete Knoten',`<div id="watchList">${watchTable()}</div>`,'wide','Meldung, wenn ein Knoten länger als die Schwelle nicht gehört wurde (eigenes Advert oder eindeutig als Hop im Pfad) und wenn er wieder da ist. Beobachten über das Detailfenster eines Knotens oder die Karte.')}
      ${card('Hash-Kollisionen',collisions(d.collisions),'wide',`Aktive Repeater und Room-Server (gehört seit ${new Date(d.collisions.since).toLocaleDateString('de-DE')}), die sich einen Hop-Hash teilen. Auf solchen Hops ist im Pfad nicht zu erkennen, welcher Knoten weitergeleitet hat; der Server wählt dann nach Lage. Größere Hashes (Gerät › Region & Routing) lösen das, wenn die Repeater sie unterstützen.`)}
      ${card('Neue Knoten',table(['Knoten','Typ','erstmals gehört'],d.newNodes.map(n=>`<tr class="click" data-act="nodeDetail" data-key="${n.key}" title="Details"><td>${esc(n.name||n.key.slice(0,8))}</td><td>${ntype((S.nodes.get(n.key)||{}).type)}</td><td>${new Date(n.first).toLocaleString('de-DE')}</td></tr>`)))}
      ${card('Advert-Häufigkeit',table(['Knoten','Typ','Adverts','pro Tag','Empfänge','Entfernung','zuletzt',''],d.nodesTop.map(n=>`<tr class="click" data-act="nodeDetail" data-key="${n.key}" title="Details"><td>${esc(n.name||n.key.slice(0,8))}</td><td>${ntype(n.type)}</td><td class="mono">${fmtN(n.adverts)}</td><td class="mono${per(n)>24?' strong':''}">${per(n)>24?'⚠ ':''}${fmt1(per(n))}</td><td class="mono">${fmtN(n.count)}</td><td class="mono">${fmtKm(n.km)}</td><td>${ago(n.last)}</td><td>${hasPos(S.nodes.get(n.key))?`<button class="sm" data-act="zoomTo" data-key="${n.key}" title="Auf der Karte zeigen">🗺</button>`:''}</td></tr>`)),'wide','Eindeutige Adverts je Knoten. Jedes geflutete Advert belegt Sendezeit im ganzen Netz – mehr als etwa 24 pro Tag ist auffällig.')}
    </div>`},
    after(d,x){
      colChart($('#cNodes'),d.timeline.map(b=>({label:x.lbl(b.t),v:b.nodes,tip:[fmtN(b.nodes)+' aktive Knoten',x.when(b.t)+' · '+x.unit]})));
      hBars($('#cNtypes'),d.nodeTypes.map(([t,v])=>[ntype(t),v]),d.nodeTypes.reduce((a,x)=>a+x[1],0));
    }},

  routes:{title:'Routen',render(d){
    const nm=n=>`<a href="#" data-act="nodeDetail" data-key="${n.key}">${esc(n.name)}</a>`,q=l=>l.guess?' <span class="muted" title="mindestens ein Ende vermutet (mehrdeutiger Hash)">?</span>':'';
    return `<div class="sgrid">
      ${card('Funkverbindungen auf der Karte','<div class="ndmap big" id="rtMap"></div><p class="muted small" id="rtInfo"></p>','wide','Verbindungen zwischen Knoten entlang der Pfade gehörter Pakete (Absender eines Adverts → Repeater → … → du). Linienstärke nach Anzahl der Pakete, gestrichelt = vermutet.')}
      ${card('Häufigste Pfade',table(['Pfad','Pakete','Empfänge','Ø SNR','zuletzt'],d.topPaths.map(p=>`<tr><td class="wrap">${p.names.map(esc).join(' → ')}</td><td class="mono">${fmtN(p.count)}</td><td class="mono">${fmtN(p.recv)}</td><td class="mono ${snrCls(p.snr)}">${fmt1(p.snr)}</td><td>${ago(p.last)}</td></tr>`)),'wide','Hop-Folgen, über die eindeutige Pakete bei dir ankommen. ? = vermutet.')}
      ${card('Weiteste Verbindungen',table(['Verbindung','Entfernung','Pakete','zuletzt'],d.longest.map(l=>`<tr><td class="wrap">${nm(l.a)} ↔ ${nm(l.b)}${q(l)}</td><td class="mono">${fmtKm(l.km)}</td><td class="mono">${fmtN(l.count)}</td><td>${ago(l.last)}</td></tr>`)),'wide','Direkte Funkstrecken zwischen zwei Knoten mit bekannter Position. Sehr weite Strecken mit ? sind oft falsch zugeordnete Hashes.')}
    </div>`},
    after(d){routeMap(d)}},

  msgs:{title:'Nachrichten',render(d,x){
    const m=d.msgs,dm=m.dm,all=(dm.ok||0)+(dm.noack||0)+(dm.fail||0);
    return `<div class="kpis">${[
      kpi('Empfangene Nachrichten',fmtN(m.convs.reduce((a,c)=>a+c.in,0))),
      kpi('Gesendete Nachrichten',fmtN(m.convs.reduce((a,c)=>a+c.out,0))),
      kpi('Zustellquote DMs',all?Math.round(dm.ok/all*100)+' %':'–','',all?`${dm.ok} bestätigt · ${dm.noack} ohne Bestätigung · ${dm.fail} Fehler`:'keine eigenen Direktnachrichten'),
      kpi('Ø Laufzeit DMs',m.rttAvg?fmt1(m.rttAvg/1000)+' s':'–','','bis zur Zustellbestätigung'),
    ].join('')}</div><div class="sgrid">
      ${card('Kanalverkehr im Netz','<div id="cChans"></div>','','Eindeutige Gruppenpakete je Kanal oder Raum – auch Kanäle, die nicht auf deinem Gerät sind.')}
      ${card('Aktivste Absender','<div id="cSenders"></div>','','Absender empfangener Kanalnachrichten.')}
      ${card('Unterhaltungen',table(['Unterhaltung','empfangen','gesendet','Absender','zuletzt'],m.convs.map(c=>`<tr><td>${esc(c.title)}</td><td class="mono">${fmtN(c.in)}</td><td class="mono">${fmtN(c.out)}</td><td class="mono">${c.conv.startsWith('c:')?'–':fmtN(c.senders)}</td><td>${ago(c.last)}</td></tr>`)),'wide')}
    </div>`},
    after(d){
      hBars($('#cChans'),d.channels.map(([n,_,u])=>[/^[0-9a-f]{2}$/.test(n)?'Hash '+n+' (unbekannt)':n.startsWith('#')||n==='Public'?n:'#'+n,u]));
      hBars($('#cSenders'),d.msgs.senders);
    }},
};

// ---------- Detailfenster zu einem Knoten ----------
let detailReq=0;
async function nodeDetail(d){
  const req=++detailReq,box=$('#nodeDrawer'),body=$('#nodeDrawerBody');
  box.classList.add('show');body.innerHTML='<p class="muted">Lade Details…</p>';
  let st;try{st=await api(`stats/node?key=${d.key||''}&hash=${d.hash||''}&hours=${$('#stRange').value}`,undefined,'GET')}
  catch(e){body.innerHTML=`<p class="muted">${esc(e.message)}</p>`;return}
  if(req!==detailReq)return;
  const n=st.node||{},size=st.bucketMs,lbl=t=>xLabel(t,size),days=Math.max(1/24,st.hours/24);
  const when=t=>new Date(t).toLocaleString('de-DE',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  const title=n.name||(st.key?st.key.slice(0,8):(st.names&&!st.names.includes(' / ')?st.names:'Hash '+st.hash));
  const kv=[['Typ',ntype(n.type)],['Schlüssel',st.key?`<span class="mono" style="word-break:break-all">${st.key}</span>`:`nur Hop-Hash <span class="mono">${st.hash}</span>${st.names?' · möglich: '+esc(st.names):''}`],
    ['Entfernung',st.km!=null?fmtKm(st.km):hasPos(n)?'eigene Position unbekannt':'keine Position'],
    ['Zuerst gehört',st.firstSeen?new Date(st.firstSeen).toLocaleString('de-DE'):'–'],['Zuletzt gehört',st.lastSeen?ago(st.lastSeen)+' ('+new Date(st.lastSeen).toLocaleString('de-DE')+')':'–'],
    ['Im Gerät gespeichert',st.contact?'ja':'nein']].map(([k,v])=>`<div>${k}</div><div>${v}</div>`).join('');
  const btns=(st.key&&S.nodes.has(st.key)?watchBtn(st.key)+' ':'')+(hasPos(n)?`<button class="sm" data-act="zoomTo" data-key="${st.key}">🗺 Karte</button> `:'')+(st.contact&&(st.contact.type===1||st.contact.type===3)?`<button class="sm" data-act="openChat" data-key="${st.key}">💬 Chat</button>`:'');
  body.innerHTML=`<div class="drawer-h"><h3>${esc(title)}</h3><button class="sm" data-act="closeDetailNode" title="Schließen (Esc)">✕</button></div>
    ${btns?`<div class="frm">${btns}</div>`:''}
    <div class="kv">${kv}</div>
    <div class="kpis">${[kpi('Adverts',fmtN(st.adverts),'',st.adverts?fmt1(st.adverts/days)+' pro Tag':''),kpi('Direkt empfangen',fmtN(st.direct),'','Pakete mit diesem Knoten als letztem Hop'),
      kpi('Ø SNR direkt',st.snr==null?'–':fmt1(st.snr)+' dB','',st.rssi==null?'':'Ø RSSI '+Math.round(st.rssi)+' dBm'),kpi('Weitergeleitet',fmtN(st.relayed),'','eindeutige Pakete mit diesem Hop im Pfad')].join('')}</div>
    ${st.direct?'<h4>Empfangsqualität (Ø SNR direkt, dB)</h4><div class="viz" id="ndSnr"></div>':''}
    ${st.relayed?'<h4>Weitergeleitete Pakete</h4><div class="viz" id="ndRel"></div>':''}
    ${st.adverts?'<h4>Adverts</h4><div class="viz" id="ndAdv"></div>':''}
    ${st.paths.length?'<h4>Wege, über die Adverts ankommen</h4><div class="ndmap" id="ndMap"></div><p class="muted small" id="ndMapInfo"></p>'+table(['Pfad','Empfänge','Ø SNR'],st.paths.map(p=>`<tr><td class="wrap">${p.path?p.names.map(esc).join(' → '):'direkt'}</td><td class="mono">${fmtN(p.count)}</td><td class="mono ${snrCls(p.snr)}">${fmt1(p.snr)}</td></tr>`)):''}
    ${st.via.length?'<h4>Kommt bei dir an über</h4>'+table(['Nachbar','Empfänge','Ø SNR'],st.via.map(v=>`<tr${v.hash?` class="click" data-act="nodeDetail" data-hash="${v.hash}" title="Details"`:''}><td>${v.hash?`<span class="mono">${v.hash}</span> ${esc(v.name||'unbekannt')}`:'direkt (ohne Repeater)'}</td><td class="mono">${fmtN(v.count)}</td><td class="mono ${snrCls(v.snr)}">${fmt1(v.snr)}</td></tr>`)):''}
    ${st.peers.length?'<h4>Nachbarn im Netz</h4>'+table(['Hop','Knoten','hört ihn','liefert an ihn'],st.peers.map(p=>`<tr class="click" data-act="nodeDetail" data-hash="${p.hash}" title="Details"><td class="mono">${p.hash}</td><td>${esc(p.name||'unbekannt')}</td><td class="mono">${p.out?fmtN(p.out):'–'}</td><td class="mono">${p.in?fmtN(p.in):'–'}</td></tr>`))+'<p class="muted small">Aus den Pfaden: wer seine Pakete als Nächstes weiterleitet („hört ihn“) und von wem er Pakete übernimmt. ? = vermutet.</p>':''}
    ${st.hourly.length?'<h4>Aktivität nach Wochentag und Uhrzeit</h4><div id="ndHeat"></div>':''}
    ${st.snrDist.length>1?'<h4>SNR-Verteilung direkter Empfänge (dB)</h4><div class="viz" id="ndSnrD"></div>':''}
    ${st.recent.length?'<h4>Letzte Adverts</h4>'+table(['Zeit','Hops','Pfad','SNR','Region'],st.recent.map(a=>`<tr><td>${new Date(a.t).toLocaleString('de-DE')}</td><td class="mono">${a.hops}</td><td class="mono">${esc(a.path||'–')}</td><td class="mono ${snrCls(a.snr)}">${fmt1(a.snr)}</td><td>${a.region?(a.region==='?'?'unbekannt':'#'+esc(a.region)):'–'}</td></tr>`)):''}
    ${!st.adverts&&!st.direct&&!st.relayed?'<p class="muted">Im gewählten Zeitraum nichts von diesem Knoten gehört.</p>':''}`;
  const pts=f=>st.buckets.map((b,i)=>({t:st.start+i*size,...f(b)}));
  if(st.direct)lineChart($('#ndSnr'),pts(b=>({v:b.snr})).map(p=>({label:lbl(p.t),v:p.v,tip:[p.v==null?'keine Daten':fmt1(p.v)+' dB',when(p.t)]})),v=>fmt1(v),140);
  if(st.relayed)colChart($('#ndRel'),st.buckets.map((b,i)=>({label:lbl(st.start+i*size),v:b.relayed,tip:[fmtN(b.relayed)+' weitergeleitet',when(st.start+i*size)]})),fmtN,140);
  if(st.paths.length)pathMap(st);
  if(st.hourly.length)heatmap($('#ndHeat'),st.hourly);
  if(st.snrDist.length>1)colChart($('#ndSnrD'),st.snrDist.map(([b,v])=>({label:String(b).replace('.',','),v,tip:[fmtN(v)+' Empfänge','SNR '+fmt1(b)+' bis '+fmt1(b+2.5)+' dB']})),fmtN,140);
  if(st.adverts)colChart($('#ndAdv'),st.buckets.map((b,i)=>({label:lbl(st.start+i*size),v:b.adverts,tip:[fmtN(b.adverts)+' Adverts',when(st.start+i*size)]})),fmtN,140);
}
// Wege auf einer kleinen Karte: Linienstärke nach Anzahl der Empfänge
let ndMap=null;
function pathMap(st){
  if(ndMap){ndMap.remove();ndMap=null}
  const el=$('#ndMap'),drawn=st.paths.filter(p=>p.points.length>=2);
  if(typeof L==='undefined'||!drawn.length){el.style.display='none';$('#ndMapInfo').textContent=typeof L==='undefined'?'Karte nicht verfügbar (offline?).':'Für diese Wege sind zu wenige Positionen bekannt.';return}
  ndMap=L.map(el,{zoomControl:true,attributionControl:true,scrollWheelZoom:false});
  defaultBase(baseLayers()).addTo(ndMap);
  const max=Math.max(...drawn.map(p=>p.count)),col=getComputedStyle(document.documentElement).getPropertyValue('--accent2').trim()||'#58a6ff',all=[];
  drawn.slice().reverse().forEach(p=>{const ll=p.points.map(x=>[x[0],x[1]]);all.push(...ll);
    const tt=`${p.path?p.names.join(' → '):'direkt'}<br>${fmtN(p.count)} Empfänge · Ø SNR ${fmt1(p.snr)} dB${p.unresolved?`<br>${p.unresolved} Hop(s) ohne Position ausgelassen`:''}`;
    L.polyline(ll,{color:col,weight:2+5*p.count/max,opacity:.75}).bindTooltip(tt,{sticky:true}).addTo(ndMap)});
  const pts=new Map();drawn.forEach(p=>p.points.forEach((x,i)=>pts.set(x[0]+','+x[1],{x,end:i===0||i===p.points.length-1})));
  pts.forEach(({x,end})=>L.circleMarker([x[0],x[1]],{radius:end?6:4,color:'#fff',weight:2,fillColor:col,fillOpacity:1}).bindTooltip(esc(x[2]),{direction:'top',permanent:end}).addTo(ndMap));
  ndMap.fitBounds(L.latLngBounds(all).pad(.15),{maxZoom:13});
  const unres=st.paths.reduce((a,p)=>a+p.unresolved,0),miss=st.paths.length-drawn.length;
  $('#ndMapInfo').textContent=[`${drawn.length} von ${st.paths.length} Wegen eingezeichnet`,miss?`${miss} ohne genug Positionen`:'',unres?`Hops ohne bekannte Position werden übersprungen`:'',!st.me?'eigene Position unbekannt':''].filter(Boolean).join(' · ');
}
// Alle Funkverbindungen auf einer Karte
let rtMap=null,rtView=null;  // Ausschnitt bleibt beim automatischen Neuladen erhalten
function routeMap(d){
  if(rtMap){rtMap.remove();rtMap=null}
  const el=$('#rtMap');if(!el)return;
  if(typeof L==='undefined'||!d.links.length){el.style.display='none';$('#rtInfo').textContent=typeof L==='undefined'?'Karte nicht verfügbar (offline?).':'Keine Verbindungen mit bekannten Positionen im Zeitraum.';return}
  rtMap=L.map(el);defaultBase(baseLayers()).addTo(rtMap);
  const max=Math.max(...d.links.map(l=>l.count)),col=getComputedStyle(document.documentElement).getPropertyValue('--accent2').trim()||'#58a6ff',all=[],nodes=new Map();
  d.links.slice().reverse().forEach(l=>{const ll=[[l.a.lat,l.a.lon],[l.b.lat,l.b.lon]];all.push(...ll);nodes.set(l.a.key,l.a);nodes.set(l.b.key,l.b);
    L.polyline(ll,{color:col,weight:1.5+4*Math.sqrt(l.count/max),opacity:.75,dashArray:l.guess?'6 5':null})
      .bindTooltip(`${esc(l.a.name)} ↔ ${esc(l.b.name)}<br>${fmtKm(l.km)} · ${fmtN(l.count)} Pakete${l.guess?'<br>vermutet (mehrdeutiger Hash)':''}`,{sticky:true}).addTo(rtMap)});
  nodes.forEach(n=>L.circleMarker([n.lat,n.lon],{radius:4,color:'#fff',weight:1.5,fillColor:col,fillOpacity:1}).bindTooltip(esc(n.name),{direction:'top'}).on('click',()=>nodeDetail({key:n.key})).addTo(rtMap));
  if(rtView)rtMap.setView(rtView[0],rtView[1]);else rtMap.fitBounds(L.latLngBounds(all).pad(.1),{maxZoom:13});
  $('#rtInfo').textContent=`${d.links.length} Verbindungen zwischen ${nodes.size} Knoten`+(d.links.length>=150?' (die 150 häufigsten)':'')+' · Klick auf einen Punkt öffnet die Details';
}
const closeDetail=()=>{detailReq++;$('#nodeDrawer').classList.remove('show');hideTip();if(ndMap){ndMap.remove();ndMap=null}};

function renderStatsTab(){
  if(!PAGES[page])page='overview';
  $$('#stPages button').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
  if(ui.tab==='stats'&&!startNode.length)history.replaceState(null,'','#stats/'+page);
  if(!data){$('#statsInfo').textContent='Lade Statistik…';return}
  const x=derive(data),c=data.cur;
  $('#statsInfo').textContent=c.first?`Daten seit ${new Date(c.first).toLocaleString('de-DE')} · Aufbewahrung ${data.retentionDays} Tage`+(data.prev?'':' · noch kein vollständiger Vorzeitraum zum Vergleich'):`Noch keine Pakete im Zeitraum · Aufbewahrung ${data.retentionDays} Tage`;
  const P=PAGES[page]||PAGES.overview;
  if(rtMap){rtView=page==='routes'?[rtMap.getCenter(),rtMap.getZoom()]:null;rtMap.remove();rtMap=null}else rtView=null;
  $('#statsPage').innerHTML=P.render(data,x);P.after(data,x);
}

async function load(){
  if(loading)return;loading=true;$('#statsBody').classList.add('loading');
  try{data=await api('stats?hours='+$('#stRange').value,undefined,'GET');renderStatsTab();
    if(startNode.length){nodeDetail(startNode[0]==='node'?{key:startNode[1]}:{hash:startNode[1]});startNode=[]}}
  catch(e){$('#statsInfo').textContent='Statistik konnte nicht geladen werden: '+e.message}
  finally{loading=false;$('#statsBody').classList.remove('loading')}
}

export function initStats(){
  actions.nodeDetail=nodeDetail;actions.closeDetailNode=closeDetail;
  actions.watch=watchAsk;actions.unwatch=d=>run('watch',{key:d.key,hours:0},'Beobachtung beendet','PUT');
  onRender(null,()=>{const l=$('#watchList');if(l)l.innerHTML=watchTable();const b=$('#ndWatch');if(b)b.outerHTML=watchBtn(b.dataset.key)});
  $('#nodeDrawer').addEventListener('click',e=>{if(e.target.id==='nodeDrawer')closeDetail()});
  addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail()});
  $('#stPages').innerHTML=Object.entries(PAGES).map(([k,p])=>`<button data-page="${k}">${p.title}</button>`).join('');
  $('#stPages').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;page=b.dataset.page;store.set('mcw.statsPage',page);hideTip();renderStatsTab()});
  $('#stRange').value=store.get('mcw.statsRange','24');
  $('#stRange').onchange=()=>{store.set('mcw.statsRange',$('#stRange').value);load()};
  $('#btnStatsReload').onclick=load;
  onShow('stats',()=>{renderStatsTab();load();clearInterval(timer);timer=setInterval(()=>{if(ui.tab==='stats'&&!document.hidden)load()},60000)});
  let rz=null;addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(()=>{if(ui.tab==='stats'&&data)renderStatsTab()},200)});
}
