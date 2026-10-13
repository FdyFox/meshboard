// Einstieg: Live-Events vom Server in den Client-Zustand übernehmen und Module verdrahten
import {$,toast} from './util.js';
import {S,actions,ui,switchTab,renderAll,renderSoon} from './state.js';
import {connectWs} from './api.js';
import {initLive,addPacket,renderLive,renderStats,drawSpark} from './live.js';
import {initChat,onMsg} from './chat.js';
import {initMapTab,renderMapSoon} from './map.js';
import {initContacts,renderContacts} from './contacts.js';
import {initDevice,renderLog} from './device.js';
import {initStats} from './stats.js';

function applyStatus(st){
  S.status=st;S.connected=st.connected;S.self=st.self;S.dev=st.dev;S.radio=st.radio||{};S.scope=st.scope;S.regions=st.regions||[];
}
function ensureActive(){if(!S.active&&S.channels.length)S.active='ch:'+S.channels[0].idx}

const handlers={
  snapshot({state:s}){
    applyStatus(s.status);
    S.contacts=new Map(s.contacts.map(c=>[c.key,c]));
    S.nodes=new Map(s.nodes.map(n=>[n.key,n]));
    S.channels=s.channels;S.packets=s.packets;S.msgs=s.msgs;S.settings=s.settings;S.maxTxt=s.maxTxt;
    S.neighbors=new Map(Object.entries(s.neighbors));
    S.stats={total:s.stats.total,byType:s.stats.byType};
    S.minutes=new Map(Object.entries(s.stats.minutes).map(([k,v])=>[+k,v]));
    S.logOn=s.logOn;S.log=s.log;
    S.rooms=new Map(s.rooms.map(r=>[r.name,r]));S.watchRooms=s.watchRooms;S.chanStats=s.chanStats;S.regionStats=s.regionStats;
    ensureActive();renderLive();renderStats();renderAll();renderMapSoon();
  },
  status({status}){applyStatus(status);renderSoon();if(ui.tab==='map')renderMapSoon()},
  packet({p,node,nb,rs,cs}){
    if(node)S.nodes.set(node.key,node);
    if(nb)S.neighbors.set(nb[0],nb[1]);
    if(rs)S.regionStats[rs[0]]=rs[1];
    if(cs)S.chanStats[cs.hash]=cs;
    addPacket(p);
    if(ui.tab==='map')renderMapSoon();
    if(ui.tab==='device'&&(rs||cs))renderSoon();
  },
  packets({packets}){S.packets=packets;renderLive()},
  packets_clear(){S.packets=[];S.stats={total:0,byType:{}};S.minutes.clear();renderLive();renderStats();$('#detail').classList.remove('show')},
  msg({conv,m,new:isNew}){onMsg(conv,m,isNew)},
  msgs({msgs}){S.msgs=msgs;renderSoon()},
  contacts({contacts}){S.contacts=new Map(contacts.map(c=>[c.key,c]));renderSoon()},
  contact({c}){S.contacts.set(c.key,c);renderSoon()},
  contact_del({key}){S.contacts.delete(key);const n=S.nodes.get(key);if(n)n.inContacts=false;renderSoon()},
  node({n}){S.nodes.set(n.key,n);renderSoon()},
  nodes({nodes}){nodes.forEach(n=>S.nodes.set(n.key,n));renderSoon()},
  channels({channels}){S.channels=channels;ensureActive();renderSoon()},
  settings({settings}){S.settings=settings;renderSoon()},
  room({room}){S.rooms.set(room.name,room);renderSoon()},
  rooms({rooms,watch}){S.rooms=new Map(rooms.map(r=>[r.name,r]));S.watchRooms=watch;
    // Raum abonniert (Verlauf liegt jetzt im Kanal) oder vergessen
    if(S.active?.startsWith('room:')&&!S.rooms.has(S.active.slice(5))){const n=S.active.slice(5),ch=S.channels.find(c=>c.name.replace(/^#/,'')===n);S.active=ch?'ch:'+ch.idx:null}
    renderSoon()},
  toast({msg,kind}){toast(msg,kind)},
  log({line}){if(!S.logOn)return;S.log.push(line);if(S.log.length>300)S.log.shift();renderLog()},
};

function online(on){
  const w=$('#warn');w.style.display=on?'none':'block';
  w.textContent='Keine Verbindung zum Server – versuche erneut…';
}

initLive();initChat();initMapTab();initContacts();initDevice();initStats();
actions.openChat=d=>{S.active='c:'+d.key.slice(0,12);switchTab('chat')};
// Buttons in generiertem HTML (Tabellen, Popups, Detailansicht)
document.addEventListener('click',e=>{const el=e.target.closest('[data-act]');if(!el||el.disabled)return;const fn=actions[el.dataset.act];if(fn){e.preventDefault();fn(el.dataset)}});
$('#tabs').addEventListener('click',e=>{const b=e.target.closest('button');if(b)switchTab(b.dataset.tab)});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)renderSoon()});
setInterval(()=>{drawSpark();if(ui.tab==='contacts')renderContacts()},10000);
const startTab=location.hash.slice(1).split('/')[0];
if(startTab&&document.getElementById('sec-'+startTab))switchTab(startTab);
renderStats();renderAll();
connectWs(m=>{const h=handlers[m.t];if(h)h(m)},online);
