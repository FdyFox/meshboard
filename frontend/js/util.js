// Hilfsfunktionen und Konstanten für die Anzeige
export const PT=['REQ','RESP','TXT','ACK','ADVERT','GRP_TXT','GRP_DATA','ANON_REQ','PATH','TRACE','MULTIPART','CONTROL','T12','T13','T14','RAW'];
export const ROUTES=['T-FLOOD','FLOOD','DIRECT','T-DIRECT'];
export const NTYPE={0:'Unbekannt',1:'Companion',2:'Repeater',3:'Room',4:'Sensor'};
export const NLETTER={0:'?',1:'C',2:'R',3:'S',4:'T'};

export const enc=new TextEncoder();
export const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const tfmt=ms=>new Date(ms).toLocaleTimeString('de-DE');
export const dtfmt=ms=>{const d=new Date(ms),t=new Date();return d.toDateString()===t.toDateString()?d.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}):d.toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})};
export function ago(ms){if(!ms)return '–';const s=(Date.now()-ms)/1000;if(s<60)return Math.max(0,Math.round(s))+' s';if(s<3600)return Math.round(s/60)+' min';if(s<86400)return Math.round(s/3600)+' h';return Math.round(s/86400)+' d'}
export const dur=s=>s==null?'–':s>=86400?Math.floor(s/86400)+' d '+Math.floor(s%86400/3600)+' h':s>=3600?Math.floor(s/3600)+' h '+Math.floor(s%3600/60)+' min':Math.floor(s/60)+' min '+(s%60)+' s';
export const snrCls=v=>v==null?'':v>=5?'snr-g':v>=-5?'snr-y':'snr-r';
export function hav(a,b,c,d){const r=Math.PI/180,R6=6371,x=Math.sin((c-a)*r/2)**2+Math.cos(a*r)*Math.cos(c*r)*Math.sin((d-b)*r/2)**2;return 2*R6*Math.asin(Math.sqrt(x))}
export const hasPos=n=>n&&typeof n.lat==='number'&&typeof n.lon==='number'&&!(n.lat===0&&n.lon===0)&&Math.abs(n.lat)<=90&&Math.abs(n.lon)<=180;
// Text escapen und http(s)-/www-Adressen als Links (neuer Tab) darstellen; andere Schemata nie
export function linkify(s){
  return String(s??'').split(/((?:https?:\/\/|www\.)[^\s<>"']+)/i).map((part,i)=>{
    if(i%2===0)return esc(part);
    const m=part.match(/^(.*?)([.,;:!?)\]]*)$/),url=m[1],tail=m[2];  // Satzzeichen am Ende gehören nicht dazu
    const href=/^www\./i.test(url)?'https://'+url:url;
    return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>${esc(tail)}`;
  }).join('');
}
export const chTitle=n=>String(n).startsWith('#')?n:'#'+n;
export const hexSpaced=h=>(h.match(/.{1,2}/g)||[]).join(' ');
// Browser-lokale Einstellungen (Kartenstil, Benachrichtigungen) – Daten liegen auf dem Server
export const store={get(k,d){try{const v=localStorage.getItem(k);return v?JSON.parse(v):d}catch{return d}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
export function toast(msg,kind=''){const t=document.createElement('div');t.className='toast '+kind;t.textContent=msg;$('#toasts').appendChild(t);setTimeout(()=>t.remove(),kind==='err'?6000:3500)}
