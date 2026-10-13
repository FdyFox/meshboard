// Grundkarten für Leaflet: Vektorkarten von OpenFreeMap (über maplibre-gl-leaflet), OSM, OpenTopoMap, Esri-Satellit
const a=(href,text)=>`<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
const OFM=`${a('https://openfreemap.org','OpenFreeMap')} © ${a('https://www.openmaptiles.org/','OpenMapTiles')} Daten von ${a('https://www.openstreetmap.org/copyright','OpenStreetMap')}`;
const OSM=`© ${a('https://www.openstreetmap.org/copyright','OpenStreetMap')}-Mitwirkende`;
const OTM=`Kartendaten: © ${a('https://www.openstreetmap.org/copyright','OpenStreetMap')}-Mitwirkende, SRTM | Kartendarstellung: © ${a('https://opentopomap.org','OpenTopoMap')} (${a('https://creativecommons.org/licenses/by-sa/3.0/','CC-BY-SA')})`;

export const vectorOK=()=>typeof L!=='undefined'&&typeof L.maplibreGL==='function'&&typeof maplibregl!=='undefined';

// Ortsnamen auf Deutsch (die Stile bevorzugen sonst name_en), Rückfall auf den Originalnamen
function german(m){
  for(const ly of m.getStyle().layers)
    if(ly.layout&&ly.layout['text-field'])m.setLayoutProperty(ly.id,'text-field',['coalesce',['get','name:de'],['get','name']]);
}
function ofm(style){
  const l=L.maplibreGL({style:'https://tiles.openfreemap.org/styles/'+style,attribution:OFM});
  l.on('add',()=>{const m=l.getMaplibreMap();if(!m)return;if(m.isStyleLoaded())german(m);else m.once('load',()=>german(m))});
  return l;
}
export function baseLayers(){
  const b={};
  if(vectorOK()){b['Hell']=ofm('positron');b['Dunkel']=ofm('dark');b['Straße']=ofm('liberty');b['Bunt']=ofm('bright')}
  b['OpenStreetMap']=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:OSM});
  b['Topo (OpenTopoMap)']=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:OTM});
  b['Satellit (Esri)']=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri — Esri, Maxar, Earthstar Geographics'});
  return b;
}
// Standard passend zum hellen/dunklen Modus; ohne MapLibre (offline o. Ä.) OSM
export const defaultBase=b=>(matchMedia('(prefers-color-scheme: dark)').matches?b['Dunkel']:b['Hell'])||b['OpenStreetMap'];
