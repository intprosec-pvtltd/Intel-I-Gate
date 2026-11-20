import toast from 'react-hot-toast';
import {notifyError,errorText,rememberError} from '../services/feedback';
import React,{useEffect,useState,useCallback,useContext,createContext,useRef} from 'react';
import {Inbox,LoaderCircle,UserRound,VideoOff} from 'lucide-react';
import {Link} from 'react-router-dom';
import {createPortal} from 'react-dom';
import LiveCameraPreview from './LiveCameraPreview';
import {api,mediaUrl,connectEvents} from '../services/api';
export const WorkspaceContext=createContext({user:null,timezone:'Asia/Kolkata'});
export function Button({variant='primary',busy=false,children,...props}){return <button {...props} disabled={props.disabled||busy} className={`btn ${variant} ${props.className||''}`}>{busy&&<LoaderCircle size={15} className="spin"/>}{children}</button>;}
export function Field({label,children,...props}){return <label className="field"><span>{label}</span>{children||<input {...props}/>}</label>;}
export function Notice({children}){useEffect(()=>{if(children)notifyError(children);},[children]);return null;}
export function Empty({title,children}){return <div className="empty"><Inbox size={30}/><h3>{title}</h3><p>{children}</p></div>;}
export function Badge({children}){const s=String(children||'UNKNOWN');return <span className={`badge ${/^(CONNECTED|READY|COMPLETED|CAPTURED|UPLOADED|EXIT_CONFIRMED|AUTO_CONFIRMED|ENTRY_SAVED)$/.test(s)?'good':/ERROR|FAILED/.test(s)?'bad':''}`}>{s.replaceAll('_',' ')}</span>;}
export function Title({title,children,actions}){return <header className="page-title"><div><div className="eyebrow">APARTMENT SECURITY WORKSPACE</div><h1>{title}</h1><p>{children}</p></div>{actions}</header>;}
export function useData(path,interval=0){
 const [data,setData]=useState(null),[error,setError]=useState('');
 const flight=useRef(null),version=useRef(0);
 const refresh=useCallback(()=>{
  if(!path)return Promise.resolve();
  if(flight.current?.path===path)return flight.current.promise;
  const control=new AbortController(),ticket=version.current;
  const slot={path,control,promise:null};
  slot.promise=api.get(path,{signal:control.signal}).then(r=>{if(version.current===ticket){setData(r.data);setError('');}return r.data;}).catch(e=>{if(!control.signal.aborted&&version.current===ticket)setError(e.userMessage||'Unable to load data');}).finally(()=>{if(flight.current===slot)flight.current=null;});
  flight.current=slot;return slot.promise;
 },[path]);
 useEffect(()=>{
  let alive=true,timer;
  async function poll(){await refresh();if(alive&&interval)timer=setTimeout(poll,interval);}
  poll();return()=>{alive=false;clearTimeout(timer);version.current+=1;if(flight.current?.path===path){flight.current.control.abort();flight.current=null;}};
 },[path,interval,refresh]);
 return {data,error,refresh};
}
export function useLive(channel,refresh){const [online,setOnline]=useState(false);useEffect(()=>connectEvents(channel,refresh,setOnline),[channel,refresh]);return online;}
export function useAction(){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),lock=useRef(false);
 const run=async(fn,message='Changes saved')=>{
  if(lock.current)return null;lock.current=true;setBusy(true);setError('');
  const notice=toast.loading('Working…');
  try{const result=await fn();const text=typeof message==='function'?message(result):message;toast.success(text||'Changes saved',{id:notice});return result;}
  catch(e){const text=errorText(e);rememberError(text,notice);setError(text);notifyError(text,{id:notice,force:true});return null;}
  finally{lock.current=false;setBusy(false);}
 };
 return {error,busy,run,setError};
}
export function Time({value}){const {timezone}=useContext(WorkspaceContext);return value?new Date(value).toLocaleString('en-IN',{timeZone:timezone,dateStyle:'medium',timeStyle:'short'}):'Not known';}
export function FaceSnapshot({id,reason,variant='default'}){
 const [url,setUrl]=useState(null),[expanded,setExpanded]=useState(false);const dialog=useRef(null);
 useEffect(()=>{
  const control=new AbortController();let object;
  setUrl(null);setExpanded(false);
  if(id)api.get(`/snapshots/${id}`,{responseType:'blob',signal:control.signal}).then(r=>{
   if(control.signal.aborted)return;
   object=URL.createObjectURL(r.data);setUrl(object);
  }).catch(()=>{});
  return()=>{control.abort();if(object)URL.revokeObjectURL(object);};
 },[id]);
 useEffect(()=>{
  if(!expanded||!url)return;
  const node=dialog.current;node.showModal();
  return()=>{if(node.open)node.close();};
 },[expanded,url]);
 return <><button type="button" className={`face face-button${variant==='thumbnail'?' face-thumbnail':''}`} disabled={!url} onClick={()=>setExpanded(true)} aria-label={url?'Enlarge face snapshot':'No suitable face captured'}>
  {url?<><img src={url} alt="Face captured from source video"/><span className="face-enlarge">{variant==='thumbnail'?'View':'Click to enlarge'}</span></>:<><UserRound size={variant==='thumbnail'?24:36}/>{variant!=='thumbnail'&&<small>No suitable face<br/>{reason?reason.replaceAll('_',' ').toLowerCase():'Guard review required'}</small>}</>}
 </button>{expanded&&url&&createPortal(<dialog ref={dialog} className="passport-snapshot-dialog" aria-labelledby="snapshot-title" onClose={()=>setExpanded(false)} onClick={e=>{if(e.target===dialog.current)dialog.current.close();}}>
  <div className="passport-snapshot-header"><h2 id="snapshot-title">Visitor portrait</h2><Button variant="secondary" onClick={()=>dialog.current.close()} autoFocus>Close snapshot</Button></div>
  <img className="passport-snapshot-image" src={url} alt="Visitor portrait captured from source video"/>
  <p className="muted">Captured source image. Existing saved snapshots keep their original crop.</p>
 </dialog>,document.body)}</>;
}
export function CameraPreview({camera}){return <LiveCameraPreview camera={camera}/>;}
export function EventCard({event:e}){
 const exit=e.test_role==='exit'||e.state==='EXIT_REVIEW'||e.state==='EXIT_CONFIRMED';
 const label=e.state==='COMPLETED'?'COMPLETED':e.state==='EXIT_CONFIRMED'?'EXIT_CONFIRMED':exit?'EXIT_AWAITING_REVIEW':e.state==='ENTRY_RECORDED'?'ENTRY_SAVED':e.candidate_status;
 const timing=e.visit_timing,saved=!!timing&&!exit,purpose=e.verification?.visit_purpose;
 return <article className="event-card"><FaceSnapshot id={e.snapshot_id} reason={e.face_reason}/><div><div className="actions"><Badge>{label}</Badge>{e.test_role&&<span className="source-label test">TEST · {e.test_role.toUpperCase()}</span>}</div>
 <h3>{saved?`${timing.flat} · ${e.verification?.visitor_name||purpose||'Visitor'}`:e.camera_name}</h3>
 {saved?<><p className="muted">{e.camera_name}{e.verification?.resident_name?` · ${e.verification.resident_name}`:''}</p>
 {timing.test_mode?<><p>Entry video: +{Number(timing.entry_video_seconds||0).toFixed(1)}s</p><p>Exit video: {timing.exit_video_seconds==null?'Awaiting test exit':`+${Number(timing.exit_video_seconds).toFixed(1)}s`}</p></>:<><p>Entry: <Time value={timing.entry_at}/></p><p>Exit: {timing.status==='COMPLETED'?<Time value={timing.exit_at}/>:'Awaiting exit'}</p></>}
 {timing.exit_method==='RESIDENT_CONFIRMED'&&<p className="muted">Exit confirmed by resident</p>}</>:<><p>{e.video_id?`Video +${Number(e.frame_seconds||0).toFixed(1)}s`:<Time value={e.captured_at}/>}</p><p className="muted">{exit?'Departure observation':e.evidence?.objects?.map(x=>x.label).join(', ')||'Purpose has not been established'}</p></>}
 <Link className="text-link" to={exit?'/history':`/verify/${e.id}`}>{exit?'Review exit →':saved?'View visit →':'Review visitor →'}</Link></div></article>;
}
export function Pager({offset,setOffset,count,size=50}){return <div className="actions pagination"><Button variant="ghost" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-size))}>Previous</Button><span>Page {Math.floor(offset/size)+1}</span><Button variant="ghost" disabled={count<size} onClick={()=>setOffset(offset+size)}>Next</Button></div>;}
