import {useEffect,useRef,useState} from 'react';
import {api} from '../services/api';
import {Button,Field,Notice,useAction} from './ui';
export default function GuardVerificationForm({event,residents=[],onSaved}){
 const previous=event.verification||{};
 const [lookupOpen,setLookupOpen]=useState(false),[highlight,setHighlight]=useState(-1);const lookup=useRef(null);
 const [form,setForm]=useState({visit_purpose:previous.visit_purpose||'Delivery',delivery_confirmed:previous.delivery_confirmed||false,flat:previous.flat||'',resident_name:previous.resident_name||'',resident_id:previous.resident_id||null,company:previous.company||'',notes:previous.notes||'',visitor_name:previous.visitor_name||'',visit_reason:previous.visit_reason||'',expected_exit_at:previous.expected_exit_at?new Date(new Date(previous.expected_exit_at).getTime()-new Date(previous.expected_exit_at).getTimezoneOffset()*60000).toISOString().slice(0,16):''});
 const [challenge,setChallenge]=useState(null),[proof,setProof]=useState(null),[code,setCode]=useState(''),[verified,setVerified]=useState(false),[smsReady,setSmsReady]=useState(null),[clock,setClock]=useState(Date.now());
 const generation=useRef(0),a=useAction();
 const term=form.flat.trim().toLocaleLowerCase();
 const compare=(a,b)=>a.flat.localeCompare(b.flat,undefined,{numeric:true,sensitivity:'base'})||a.name.localeCompare(b.name,undefined,{sensitivity:'base'})||a.id.localeCompare(b.id);
 const suggestions=residents.filter(r=>!term||r.flat.toLocaleLowerCase().includes(term)||r.name.toLocaleLowerCase().includes(term)).slice().sort((a,b)=>Number(!a.flat.toLocaleLowerCase().startsWith(term))-Number(!b.flat.toLocaleLowerCase().startsWith(term))||compare(a,b));
 const matches=residents.filter(r=>r.flat.trim().toUpperCase()===form.flat.trim().toUpperCase()).slice().sort(compare);
 const selected=matches.find(r=>r.id===form.resident_id);
 const otpOk=!!(proof&&proof.resident_id===selected?.id&&new Date(proof.expires_at).getTime()>clock);
 const wait=Math.max(0,Math.ceil(((challenge?.resendAt||0)-clock)/1000));
 useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[]);
 useEffect(()=>{let active=true;api.get(`/events/${event.id}/otp`).then(({data})=>{
  if(!active||generation.current)return;
  setSmsReady(data.sms_configured);
  if(['SENT','VERIFIED'].includes(data.state)){
   setChallenge({...data,resendAt:new Date(data.resend_at).getTime()});
   const r=residents.find(r=>r.id===data.resident_id);
   if(r){setForm(f=>({...f,flat:r.flat,resident_name:r.name,resident_id:r.id}));if(data.verified)setProof(data);}
  }
 }).catch(e=>{if(active)a.setError(e.userMessage||'Cannot load OTP status');});return()=>{active=false;};},[event.id,residents]);
 function resetApproval(){generation.current+=1;setProof(null);setChallenge(null);setCode('');setVerified(false);a.setError('');}
 function choose(r,flat=form.flat){resetApproval();setForm(f=>({...f,flat,resident_id:r?.id||null,resident_name:r?.name||''}));}
 function flatChange(e){setLookupOpen(true);setHighlight(-1);const flat=e.target.value;const rows=residents.filter(r=>r.flat.trim().toUpperCase()===flat.trim().toUpperCase());choose(rows.length===1?rows[0]:null,flat);}
 // Phone changes invalidate the displayed approval as well as server-side approval.
 function pick(r){choose(r,r.flat);setLookupOpen(false);setHighlight(-1);}
 function lookupKeys(e){
  if(e.key==='Escape'){e.preventDefault();setLookupOpen(false);setHighlight(-1);return;}
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setLookupOpen(true);setHighlight(n=>suggestions.length?(e.key==='ArrowDown'?Math.min(n+1,suggestions.length-1):Math.max(n-1,0)):-1);return;}
  if(e.key==='Enter'&&lookupOpen){e.preventDefault();const r=suggestions[highlight<0?0:highlight];if(r)pick(r);}
 }
 useEffect(()=>{if(lookupOpen&&highlight>=0)lookup.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({block:'nearest'});},[highlight,lookupOpen]);
 const contact=selected?`${selected.id}:${selected.name}:${selected.flat}:${selected.phone}`:'';
 const lastContact=useRef(contact);
 useEffect(()=>{if(lastContact.current&&lastContact.current!==contact){setProof(null);setVerified(false);}lastContact.current=contact;},[contact]);
 const send=()=>a.run(async()=>{
  const ticket=++generation.current;setProof(null);setVerified(false);setCode('');
  const {data}=await api.post(`/events/${event.id}/otp/request`,{resident_id:selected.id,delivery_confirmed:true});
  if(ticket!==generation.current)return;
  setSmsReady(true);setChallenge({...data,resident_id:selected.id,resendAt:Date.now()+data.resend_after_seconds*1000});
 },'OTP sent to resident');
 const check=()=>a.run(async()=>{
  const {data}=await api.post(`/events/${event.id}/otp/verify`,{challenge_id:challenge.challenge_id,code});setProof(data);setCode('');
 },'Resident OTP verified');
 const action=mode=>a.run(async()=>{
  const payload={...form,expected_exit_at:form.visit_purpose==='Delivery'?null:(form.expected_exit_at?new Date(form.expected_exit_at).toISOString():null),flat:selected.flat,resident_name:selected.name,resident_id:selected.id};
  const {data}=await api.post(`/events/${event.id}/${mode}`,payload);
  if(mode==='verify')setVerified(true);else onSaved(data);
 },mode==='verify'?'Visit confirmed. Save the entry to finish.':'Visitor entry saved');
 return <form className="form" onSubmit={e=>{e.preventDefault();if(verified&&otpOk)action('save');}}>
  <h2>Verify visitor destination</h2><p className="muted">Select the visit purpose and resident, then obtain resident approval.</p>
  <Field label="Visit purpose"><select value={form.visit_purpose} disabled={a.busy} required onChange={e=>{resetApproval();setForm(f=>({...f,visit_purpose:e.target.value,delivery_confirmed:false,company:'',visitor_name:'',visit_reason:'',expected_exit_at:''}));}}><option value="Delivery">Delivery</option><option value="Relation">Guest / Relation</option><option value="Maid/Caretaker">Maid / Caretaker</option></select></Field>
  {form.visit_purpose==='Delivery'?<p className="muted">Expected exit: 15 minutes after this entry is saved.</p>:<Field label="Expected exit date and time (local)" type="datetime-local" required value={form.expected_exit_at} onChange={e=>{setVerified(false);setForm({...form,expected_exit_at:e.target.value});}}/>}
  <label className="check"><input type="checkbox" checked={form.delivery_confirmed} disabled={a.busy} onChange={e=>{setVerified(false);setForm({...form,delivery_confirmed:e.target.checked});}} required/>I confirm the selected visit purpose and destination</label>
  <div className="resident-lookup" ref={lookup} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setLookupOpen(false);}}>
   <div className="resident-lookup-anchor"><Field label="Destination Flat Number" value={form.flat} onChange={flatChange} maxLength={40} disabled={a.busy} required autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={lookupOpen} aria-controls="resident-flat-options" aria-activedescendant={lookupOpen&&highlight>=0&&suggestions[highlight]?`resident-flat-option-${highlight}`:undefined} onFocus={()=>{setLookupOpen(true);setHighlight(-1);}} onKeyDown={lookupKeys}/>
   {lookupOpen&&<div className="resident-lookup-menu"><div id="resident-flat-options" role="listbox" aria-label="Stored flats and residents">{suggestions.length?suggestions.map((r,i)=><button key={r.id} id={`resident-flat-option-${i}`} type="button" role="option" aria-selected={i===highlight} onMouseDown={e=>e.preventDefault()} onClick={()=>pick(r)}><strong>{r.flat}</strong><span>{r.name}</span></button>):<p role="status">No matching resident. Ask the administrator to update the directory.</p>}</div></div>}
   </div><p className="muted resident-lookup-hint">Choose a stored flat and resident, or type a flat number/name to filter. Use arrow keys and Enter to select.</p>
  </div>
  {form.flat.trim()&&!matches.length&&!suggestions.length&&<p className="muted">No registered resident found for this flat. Ask the administrator to add or update the resident.</p>}
  <Field label="Select resident"><select value={form.resident_id||''} disabled={a.busy||!matches.length} onChange={e=>choose(matches.find(r=>r.id===e.target.value))} required><option value="">Select resident in this flat</option>{matches.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
  <div className="form-grid"><Field label="Destination Resident Name" value={selected?.name||''} readOnly/><Field label="Resident phone number" value={selected?.phone||''} readOnly/></div>
  {selected&&!selected.phone&&<p className="muted">This resident has no phone number. The administrator must update their record before OTP verification.</p>}
  <section className="otp-panel" aria-label="Resident OTP approval">
   <h3>Resident approval</h3>
   {smsReady===false&&<p className="muted">SMS delivery is not configured. Ask the administrator to configure the SMS provider.</p>}
   <Button type="button" variant="secondary" busy={a.busy} disabled={!form.delivery_confirmed||!selected?.phone||wait>0||smsReady===false} onClick={send}>{wait>0?`Resend in ${wait}s`:challenge?'Resend OTP':'Send OTP'}</Button>
   {challenge&&!otpOk&&<><Field label="Resident OTP" value={code} type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} disabled={a.busy} onChange={e=>setCode(e.target.value.replace(/\D/g,''))}/><Button type="button" busy={a.busy} disabled={!/^\d{6}$/.test(code)} onClick={check}>Verify OTP</Button><p className="muted">Code expires at {new Date(challenge.expires_at).toLocaleTimeString()}. Ask the resident to share it only if they expect this visit.</p></>}
   {otpOk&&<p role="status" className="success-text">Resident approval: Verified</p>}
   
  </section>
  {form.visit_purpose==='Delivery'&&<Field label="Delivery Company (optional)" value={form.company} maxLength={120} disabled={a.busy} onChange={e=>{setVerified(false);setForm({...form,company:e.target.value});}}/>}
  {form.visit_purpose!=='Delivery'&&<><Field label={form.visit_purpose==='Relation'?'Guest name':'Maid / caretaker name'} value={form.visitor_name} maxLength={120} disabled={a.busy} required onChange={e=>{setVerified(false);setForm({...form,visitor_name:e.target.value});}}/><Field label="Reason for visit" value={form.visit_reason} maxLength={500} disabled={a.busy} required onChange={e=>{setVerified(false);setForm({...form,visit_reason:e.target.value});}}/></>}
  <Field label="Notes (optional)"><textarea maxLength={2000} value={form.notes} disabled={a.busy} onChange={e=>{setVerified(false);setForm({...form,notes:e.target.value});}}/></Field>
  <Notice>{a.error}</Notice>
  <div className="actions"><Button type="button" variant="secondary" busy={a.busy} disabled={!form.delivery_confirmed||!otpOk||(form.visit_purpose!=='Delivery'&&(!form.visitor_name.trim()||!form.visit_reason.trim()||!form.expected_exit_at))} onClick={()=>action('verify')}>Confirm Visit</Button><Button busy={a.busy} disabled={!verified||!form.delivery_confirmed||!otpOk}>Save Event</Button></div>
 </form>;
}
