import {useEffect,useState} from 'react';
import {api} from '../services/api';
import {Button,Notice,useAction} from '../components/ui';
import {confirmAction} from '../components/Notifications';
export default function ResidentResponse(){
 const [token]=useState(()=>location.hash.slice(1));
 useEffect(()=>{history.replaceState(null,'',location.pathname);},[]);
 const [done,setDone]=useState('');const a=useAction();
 const answer=async value=>{if(!await confirmAction(value==='left'?'Confirm the visitor has left? This will close their visit.':'Confirm the visitor is still present?'))return;a.run(async()=>{const {data}=await api.post('/resident-response',{token,answer:value});setDone(data.message);},value==='left'?'Resident-reported exit saved':'Resident response saved: still present');};
 return <main className="resident-response"><section className="panel"><img src="/branding/intel-i-gate.png" alt="INTEL-I GATE" width="220"/><h1>Visitor exit confirmation</h1>{done?<h2 aria-live="polite">Response recorded</h2>:<><p>Please confirm the status of the overdue visitor mentioned in your message.</p><Notice>{a.error||(!token?'Open the complete link from your message.':'')}</Notice><div className="actions"><Button busy={a.busy} disabled={!token} onClick={()=>answer('left')}>Has left</Button><Button variant="secondary" busy={a.busy} disabled={!token} onClick={()=>answer('present')}>Still present</Button></div><p className="muted">Only respond if you are the intended resident. The link expires and can be used once.</p></>}</section></main>;
}
