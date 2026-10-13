// Client-Zustand (Spiegel des Server-Zustands), Nachschlage-Helfer und Render-Steuerung
export const MAX_PKTS=3000, MAX_ROWS=400;

export const S={connected:false,status:{},self:null,dev:null,radio:{},scope:null,regions:[],
  contacts:new Map(),nodes:new Map(),channels:[],packets:[],msgs:{},neighbors:new Map(),
  stats:{total:0,byType:{}},minutes:new Map(),settings:{chanRegion:{},extraRegions:''},log:[],logOn:false,maxTxt:150,
  rooms:new Map(),watchRooms:[],chanStats:{},regionStats:{},
  // nur in diesem Browser
  // unread: ungelesen je Unterhaltung (Badge in der Liste); alert: davon gemeldet (Badge am Tab, Desktop-Meldung)
  active:null,unread:{},alert:{},paused:false,selPkt:null};

export const findContactByPrefix=p=>{for(const c of S.contacts.values())if(c.key.startsWith(p))return c;return null};
export function nodesByHash(h){const r=[];for(const n of S.nodes.values())if(n.key.startsWith(h))r.push(n);return r}
export function nodeName(h){const l=nodesByHash(h);return l.length===1?l[0].name:l.length>1?l.map(n=>n.name).join(' / '):null}
export const lastSeen=n=>Math.max(n.heard||0,(n.advTs||0)*1000>Date.now()+86400000?0:(n.advTs||0)*1000);
export const chanId=ch=>ch?(ch.name+':'+(ch.secret||'').slice(0,8)):'';
export const chanRegion=ch=>ch?(S.settings.chanRegion[chanId(ch)]||''):'';
export const findChan=idx=>S.channels.find(c=>c.idx==idx);
export const pathTxt=c=>c.flood?'Flood':c.hops.length?c.hops.join('→'):'direkt';

// Aktionen für Buttons in generiertem HTML: <button data-act="name" data-key="…">
export const actions={};

// Tabs & Rendering
export const ui={tab:'live'};
const renderers={},showHooks={},always=[];
export function onRender(tab,fn){if(tab)(renderers[tab]||(renderers[tab]=[])).push(fn);else always.push(fn)}
export function onShow(tab,fn){(showHooks[tab]||(showHooks[tab]=[])).push(fn)}
export function renderAll(){always.forEach(f=>f());(renderers[ui.tab]||[]).forEach(f=>f())}
let rT=null;
export function renderSoon(){if(!rT)rT=setTimeout(()=>{rT=null;renderAll()},150)}
export function switchTab(t){ui.tab=t;
  if(location.hash.split('/')[0]!=='#'+t)history.replaceState(null,'','#'+t);  // Direktlink/Neuladen öffnet denselben Tab
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===t));
  document.querySelectorAll('main section').forEach(s=>s.classList.toggle('active',s.id==='sec-'+t));
  (showHooks[t]||[]).forEach(f=>f());renderAll()}
