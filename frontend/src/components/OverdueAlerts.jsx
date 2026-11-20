import {useEffect} from 'react';
import {Link} from 'react-router-dom';
import toast from 'react-hot-toast';
import {useData,Time,Notice} from './ui';
const notifiedAlerts=new Set();
export default function OverdueAlerts(){
 const d=useData('/visit-alerts',15000);
 useEffect(()=>{for(const a of d.data||[]){if(!notifiedAlerts.has(a.id)){toast.error(`${a.test_mode?'TEST: ':''}Visitor to ${a.flat} is overdue`,{id:'overdue-'+a.id});notifiedAlerts.add(a.id);if(notifiedAlerts.size>500)notifiedAlerts.delete(notifiedAlerts.values().next().value);}}},[d.data]);
 return <section className="panel overdue-panel"><div className="section-heading"><h2>Overdue visits ({d.data?.length||0})</h2><Link to="/visitor-logs?status=OVERDUE">View logs →</Link></div><Notice>{d.error}</Notice>{!d.data?.length?<p className="muted">No overdue visits.</p>:d.data.map(a=><article className="overdue-row" key={a.id}><div><strong>{a.flat} · {a.visitor_name||a.purpose}</strong><p>Expected exit: <Time value={a.expected_exit_at}/> · {Math.max(0,Math.floor((Date.now()-new Date(a.expected_exit_at))/60000))} min overdue</p><small>{a.test_mode?'Video test — no SMS':`Resident message: ${a.sms_state.replaceAll('_',' ')}`}{a.response==='present'?' · Resident says still present':''}</small>{a.last_error&&<p className="muted">{a.last_error}</p>}</div><Link className="btn secondary" to={`/verify/${a.event_id}`}>Review visit</Link></article>)}</section>;
}
