// Verbindung zum Backend: REST-Befehle und WebSocket mit Live-Events
import {toast} from './util.js';

// Relative Pfade, damit die App auch hinter einem Reverse-Proxy mit Unterpfad läuft
const base=location.pathname.replace(/[^/]*$/,'');

export async function api(path,body,method='POST'){
  const opt={method};
  if(body!==undefined){opt.headers={'Content-Type':'application/json'};opt.body=JSON.stringify(body)}
  const r=await fetch(base+'api/'+path,opt);
  let j=null;try{j=await r.json()}catch{}
  if(!r.ok)throw new Error(typeof j?.detail==='string'?j.detail:j?.detail?'ungültige Eingabe':'Server-Fehler '+r.status);
  return j;
}
// Befehl ausführen, Fehler als Toast melden; liefert null bei Fehler
export async function run(path,body,okMsg,method){
  try{const r=await api(path,body,method);if(okMsg)toast(okMsg,'ok');return r||{}}
  catch(e){toast(e.message,'err');return null}
}
export const downloadUrl=path=>base+'api/'+path;

export function connectWs(onEvent,onOnline){
  let delay=1000;
  const open=()=>{
    const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+base+'api/ws');
    ws.onopen=()=>{delay=1000;onOnline(true)};
    ws.onmessage=e=>{let m;try{m=JSON.parse(e.data)}catch{return}try{onEvent(m)}catch(err){console.error('Event',m.t,err)}};
    ws.onclose=()=>{onOnline(false);setTimeout(open,delay);delay=Math.min(delay*2,15000)};
  };
  open();
}
