import {useParams,Link} from 'react-router-dom';
import {Camera,MapPin,UserRound} from 'lucide-react';
import {Title,Notice,FaceSnapshot,Badge,Time,useData} from '../components/ui';
import VisitTiming from '../components/VisitTiming';
import EventTimeline from '../components/EventTimeline';

function ObservationPhoto({observation,role,fallback}){
 const o=observation;
 return <article className="visit-photo-card" aria-label={`${role} snapshot`}>
  <div className="visit-photo-heading"><Camera size={17}/><h3>{role} snapshot</h3></div>
  <FaceSnapshot id={o?.snapshot_id||fallback} reason={role==='Exit'?'Exit snapshot not recorded':'Entry snapshot not recorded'}/>
  <div className="visit-photo-caption"><b>{o?.camera_name||`${role} camera`}</b>
   {o&&(o.test_mode?<small>Video position: {o.frame_seconds==null?'Not recorded':`+${Number(o.frame_seconds).toFixed(1)}s`}</small>:<small><Time value={o.observed_at}/></small>)}
   {!o&&<small>{role==='Exit'?'An exit image appears when camera evidence is available.':'Saved entry reference'}</small>}
  </div>
 </article>;
}

export default function VisitDetails(){
 const {id}=useParams(),d=useData(`/visits/${id}`,5000),v=d.data;
 const observations=v?.observations||[],entry=observations.filter(o=>o.role?.toLowerCase()==='entry'),exit=observations.filter(o=>o.role?.toLowerCase()==='exit');
 const details=v?.event?.verification||{};
 return <><Title title="Visitor details" actions={<Link to="/history">← Visit history</Link>}>Entry, approval and departure in one record.</Title><Notice>{d.error}</Notice>
  {v?<div className="visit-record">
   <header className="visit-record-header"><div className="visit-record-person"><span className="visit-record-icon"><UserRound size={24}/></span><div><h2>{details.visitor_name||details.visit_purpose||'Visitor'}</h2><p>{details.visit_purpose||'Purpose not recorded'}{v.historical?' · Uploaded video test':' · Live visit'}</p></div></div><Badge>{v.status}</Badge></header>
   <div className="visit-record-layout">
    <aside className="visit-record-photos" aria-label="Entry and exit evidence">
     {(entry.length?entry:[null]).map((o,i)=><ObservationPhoto key={o?.event_id||`entry-${i}`} observation={o} role="Entry" fallback={v.event?.snapshot_id}/>)}
     {(exit.length?exit:[null]).map((o,i)=><ObservationPhoto key={o?.event_id||`exit-${i}`} observation={o} role="Exit"/>)}
     {observations.filter(o=>!['entry','exit'].includes(o.role?.toLowerCase())).map(o=><ObservationPhoto key={o.event_id} observation={o} role={o.role||'Additional'}/>)}
    </aside>
    <div className="visit-record-main">
     <section className="visit-destination" aria-labelledby="destination-title"><div className="visit-photo-heading"><MapPin size={18}/><h2 id="destination-title">Destination details</h2></div><dl className="visit-facts">{[['Destination',v.flat],['Resident',v.resident_name],['Purpose',details.visit_purpose],['Reason',details.visit_reason],['Company',v.company],['Notes',v.notes]].map(([k,val])=><div key={k}><dt>{k}</dt><dd>{val||'Not recorded'}</dd></div>)}</dl></section>
     <div className="visit-record-times"><VisitTiming timing={v.event?.visit_timing}/></div>
     <section className="visit-record-timeline" aria-labelledby="visit-timeline-title"><h2 id="visit-timeline-title">Visit timeline</h2><p className="muted">Recorded actions from arrival to departure.</p><EventTimeline key={id} items={v.timeline||[]} active={v.status==='ENTRY_RECORDED'}/></section>
    </div>
   </div>
  </div>:!d.error&&<p>Loading visitor details…</p>}
 </>;
}
