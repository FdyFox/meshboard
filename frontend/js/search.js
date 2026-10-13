// Globale Suche (Strg+K oder /): Knoten, Kontakte, Kanäle, Räume und Nachrichten im Browser-Zustand
import {$,esc,ago,chTitle,NTYPE} from './util.js';
import {S,actions,switchTab} from './state.js';
import {convTitle} from './chat.js';

let hits=[],sel=0;
const MAX=8;
function find(q){
  const r=[],ql=q.toLowerCase(),hex=/^[0-9a-f]{2,64}$/.test(ql);
  const nodes=[...S.nodes.values()].filter(n=>(n.name||'').toLowerCase().includes(ql)||hex&&n.key.startsWith(ql))
    .sort((a,b)=>(b.heard||0)-(a.heard||0)).slice(0,MAX);
  nodes.forEach(n=>r.push({g:'Knoten',t:n.name||n.key.slice(0,8),s:`${NTYPE[n.type??0]} · ${n.key.slice(0,8)}${n.heard?' · gehört vor '+ago(n.heard):''}`,go:()=>actions.nodeDetail({key:n.key})}));
  [...S.contacts.values()].filter(c=>!S.nodes.has(c.key)&&(c.name.toLowerCase().includes(ql)||hex&&c.key.startsWith(ql))).slice(0,MAX)
    .forEach(c=>r.push({g:'Kontakte',t:c.name,s:NTYPE[c.type]+' · im Gerät gespeichert',go:()=>c.type===1||c.type===3?actions.openChat({key:c.key}):switchTab('contacts')}));
  S.channels.filter(c=>c.name.toLowerCase().includes(ql)).forEach(c=>r.push({g:'Kanäle',t:chTitle(c.name),s:'Kanal '+c.idx,go:()=>openConv('ch:'+c.idx)}));
  [...S.rooms.values()].filter(x=>x.name.toLowerCase().includes(ql)).slice(0,MAX).forEach(x=>r.push({g:'Kanäle',t:chTitle(x.name),s:'gehörter Raum · '+x.count+' Pakete',go:()=>openConv('room:'+x.name)}));
  if(ql.length>=3){const m=[];for(const [conv,arr] of Object.entries(S.msgs))for(const x of arr)if((x.text||'').toLowerCase().includes(ql)||(x.from||'').toLowerCase().includes(ql))m.push([conv,x]);
    m.sort((a,b)=>(b[1].rx||0)-(a[1].rx||0)).slice(0,MAX).forEach(([conv,x])=>r.push({g:'Nachrichten',t:x.text,s:`${x.from} · ${convTitle(conv)} · ${new Date(x.rx||x.ts).toLocaleString('de-DE')}`,go:()=>openConv(conv,x.id)}))}
  return r;
}
// Unterhaltung öffnen und optional zur Nachricht scrollen
function openConv(conv,mid){S.active=conv;switchTab('chat');
  if(mid)setTimeout(()=>{const el=document.querySelector(`#msgs [data-mid="${mid}"]`);if(el){el.scrollIntoView({block:'center'});el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),2000)}},250)}
function render(){
  const q=$('#gsIn').value.trim();hits=q?find(q):[];sel=Math.min(sel,Math.max(0,hits.length-1));let g='',h='';
  hits.forEach((x,i)=>{if(x.g!==g){g=x.g;h+=`<div class="gs-g">${g}</div>`}
    h+=`<div class="gs-i${i===sel?' on':''}" data-i="${i}"><div>${esc(x.t)}</div><div class="muted small">${esc(x.s)}</div></div>`});
  $('#gsList').innerHTML=h||(q?'<div class="muted gs-e">Nichts gefunden</div>':'<div class="muted gs-e">Name, Hash (z. B. 5c), Kanal oder Text aus Nachrichten</div>');
  const on=$('#gsList .on');if(on)on.scrollIntoView({block:'nearest'});
}
function open(){$('#gs').classList.add('show');$('#gsIn').value='';sel=0;render();$('#gsIn').focus()}
function close(){$('#gs').classList.remove('show')}
function go(i){const x=hits[i];if(!x)return;close();x.go()}

export function initSearch(){
  $('#btnSearch').onclick=open;
  addEventListener('keydown',e=>{
    const typing=/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
    if((e.key==='k'&&(e.ctrlKey||e.metaKey))||(e.key==='/'&&!typing)){e.preventDefault();open()}});
  $('#gsIn').oninput=()=>{sel=0;render()};
  $('#gsIn').onkeydown=e=>{
    if(e.key==='ArrowDown'){sel=Math.min(hits.length-1,sel+1);render();e.preventDefault()}
    else if(e.key==='ArrowUp'){sel=Math.max(0,sel-1);render();e.preventDefault()}
    else if(e.key==='Enter')go(sel);else if(e.key==='Escape')close()};
  $('#gsList').onclick=e=>{const it=e.target.closest('.gs-i');if(it)go(+it.dataset.i)};
  $('#gs').onclick=e=>{if(e.target.id==='gs')close()};
}
