import React, {useEffect,useState} from 'react';
import {UserRound} from 'lucide-react';
import {api,mediaUrl} from '../services/api';
import {Button,Notice,Time,Title} from '../components/ui';

function Face({id}){
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[id]);
 return id&&!failed?<img src={mediaUrl(`/snapshots/${encodeURIComponent(id)}`)} alt="Visitor face snapshot" onError={()=>setFailed(true)}/>:<UserRound aria-label="No face snapshot available"/>;
}
export default function ApartmentView(){
 const [data,setData]=useState(null),[error,setError]=useState(''),[selected,setSelected]=useState(''),[page,setPage]=useState(0),[source,setSource]=useState('all');
 useEffect(()=>{let live=true;async function load(){try{const r=await api.get('/apartment-map');if(live){setData(r.data);setError('');}}catch(e){if(live)setError(e.userMessage||'Could not load the apartment view.');}}load();const timer=setInterval(load,5000);return()=>{live=false;clearInterval(timer);};},[]);
 const visits=(data?.visits||[]).filter(v=>source==='all'||(source==='test'?v.test_mode:!v.test_mode)), pages=Math.max(1,Math.ceil(visits.length/12)), safePage=Math.min(page,pages-1);
 const visible=visits.slice(safePage*12,safePage*12+12), details=selected?visits.filter(v=>v.id===selected):visits;
 return <>
  <Title title="Apartment view">Active guard-confirmed visits appear automatically.</Title>
  <div className="source-tabs" role="group" aria-label="Visitor source">{[['all','All visitors'],['live','Live visits'],['test','Video tests']].map(([key,label])=><button type="button" key={key} aria-pressed={source===key} onClick={()=>{setSource(key);setPage(0);setSelected('');}}>{label}</button>)}</div><Notice>{error}</Notice>{data?.truncated&&<p className="muted">Only the most recent 500 active visits are displayed.</p>}
  <p className="map-note">Pins are placed automatically for display. The flat is the guard-recorded destination; pins do not show actual or live visitor locations.</p>
  <div className="apartment-layout"><div>
   <div className="apartment-ground" aria-label="Active visitor destination display">
    <div className="apartment-pin-grid">{visible.map(v=><button type="button" key={v.id} className={`map-pin has-visit ${selected===v.id?'is-selected':''}`} onClick={()=>setSelected(v.id)} aria-label={`${v.flat}, active visitor`}><span className="map-pin-face"><Face id={v.snapshot_id}/></span><span className="map-pin-label">{v.flat}{v.test_mode?' · TEST':''}</span></button>)}</div>
    {!data&&<div className="map-loading">Loading apartment view…</div>}
   </div>
   {pages>1&&<div className="map-pages"><Button type="button" variant="secondary" disabled={safePage===0} onClick={()=>setPage(safePage-1)}>Previous</Button><span>Page {safePage+1} of {pages}</span><Button type="button" variant="secondary" disabled={safePage>=pages-1} onClick={()=>setPage(safePage+1)}>Next</Button></div>}
  </div>
  <section className="map-visit-panel"><h2>{selected?'Selected visitor':'Active visitors'}</h2><p className="muted">{selected?'Guard-confirmed destination and visit details.':'Select a pin to see visitor details.'}</p>
   {selected&&<button className="text-link map-clear" type="button" onClick={()=>setSelected('')}>Show all visitors</button>}
   {details.map(v=><div className="map-visitor" key={v.id}><div className="map-visitor-face"><Face id={v.snapshot_id}/></div><div><strong>{v.flat}</strong>{v.test_mode&&<span className="source-label test">VIDEO TEST · ENTRY</span>}<span>{v.purpose==='Relation'?'Guest / Relation':(v.purpose||'Visitor')} · {v.resident_name}</span>{v.visitor_name&&<span>Visitor: {v.visitor_name}</span>}{v.visit_reason&&<span>Reason: {v.visit_reason}</span>}<small>{v.test_mode?`Entry video +${Number(v.video_seconds||0).toFixed(1)}s`:<>Entry: <Time value={v.entry_at}/></>}</small></div></div>)}
   {data&&!details.length&&<p className="muted">No active visits to show.</p>}
  </section></div>
 </>;
}
