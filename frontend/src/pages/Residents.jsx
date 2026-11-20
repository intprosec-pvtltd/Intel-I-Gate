import {confirmAction} from '../components/Notifications';
import {useState} from 'react';
import {api} from '../services/api';
import {Title,Field,Button,Notice,Empty,useData,useAction} from '../components/ui';
const blank={name:'',flat:'',phone:''};
export default function Residents(){
 const d=useData('/residents'),faces=useData('/resident-faces'),a=useAction();const [form,setForm]=useState({...blank}),[editing,setEditing]=useState(null),[query,setQuery]=useState('');
 const change=e=>setForm({...form,[e.target.name]:e.target.value});
 const reset=()=>{setForm({...blank});setEditing(null);};
 const submit=e=>{e.preventDefault();a.run(async()=>{if(editing)await api.put(`/residents/${editing}`,form);else await api.post('/residents',form);reset();await d.refresh();},editing?'Resident updated':'Resident added');};
 const remove=async r=>{if(!await confirmAction(`Remove ${r.name} from flat ${r.flat}? Saved visit history is retained.`))return;a.run(async()=>{await api.delete(`/residents/${r.id}`);if(editing===r.id)reset();await d.refresh();},'Resident removed');};
 const rows=(d.data||[]).filter(r=>`${r.name} ${r.flat} ${r.phone}`.toLowerCase().includes(query.toLowerCase()));
 return <><Title title="Residents">Maintain resident names, flat numbers and phone numbers for delivery approval.</Title><Notice>{a.error||d.error||faces.error}</Notice>
 <div className="resident-layout"><section className="panel"><h2>{editing?'Edit resident':'Add resident'}</h2><form className="form" onSubmit={submit}>
 <Field label="Resident name" name="name" maxLength={120} value={form.name} onChange={change} disabled={a.busy} required/>
 <Field label="Flat number" name="flat" maxLength={40} value={form.flat} onChange={change} disabled={a.busy} required/>
 <Field label="Phone number" name="phone" type="tel" autoComplete="tel" maxLength={20} placeholder="10-digit mobile or +country code" value={form.phone} onChange={change} disabled={a.busy} required/>
 <p className="muted">Use the resident’s registered mobile number. Indian 10-digit mobile numbers are saved with +91.</p>
 <div className="actions"><Button busy={a.busy}>{editing?'Update resident':'Add resident'}</Button>{editing&&<Button type="button" variant="secondary" disabled={a.busy} onClick={reset}>Cancel edit</Button>}</div></form></section>
 <section className="panel"><h2>Resident directory</h2><Field label="Search residents" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Name, flat or phone"/>{rows.length?<div className="table-wrap resident-table"><table><thead><tr><th>Resident</th><th>Flat</th><th>Phone</th><th>Recognition</th><th>Actions</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>{r.name}</td><td>{r.flat}</td><td>{r.phone||'Phone required'}</td><td>{(Array.isArray(faces.data)?faces.data:[]).some(f=>f.resident_id===r.id&&f.active)?'Enrolled':'Not enrolled'}</td><td><div className="actions"><Button variant="secondary" disabled={a.busy} onClick={()=>{setEditing(r.id);setForm({name:r.name,flat:r.flat,phone:r.phone});}}>Edit</Button>{(Array.isArray(faces.data)?faces.data:[]).some(f=>f.resident_id===r.id&&f.active)&&<Button variant="secondary" disabled={a.busy} onClick={async()=>{if(await confirmAction('Remove this resident’s face enrollment? Future appearances will create visitor observations.'))a.run(async()=>{await api.delete(`/resident-faces/${r.id}`);await faces.refresh();},'Resident face enrollment removed');}}>Remove face</Button>}<Button variant="danger" disabled={a.busy} onClick={()=>remove(r)}>Delete</Button></div></td></tr>)}</tbody></table></div>:<Empty title="No residents found">Add a resident or adjust your search.</Empty>}</section></div></>;
}
