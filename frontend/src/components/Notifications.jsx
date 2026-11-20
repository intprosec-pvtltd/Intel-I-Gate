import {useEffect,useId,useRef} from 'react';
import {createPortal} from 'react-dom';
import toast,{Toaster} from 'react-hot-toast';
import {notifyError} from '../services/feedback';
export default function Notifications(){
 useEffect(()=>{
  let validating=false;
  const invalid=e=>{
   e.preventDefault();if(validating)return;validating=true;queueMicrotask(()=>{validating=false;});
   const field=e.target;const label=field.labels?.[0]?.querySelector('span')?.textContent||field.getAttribute('aria-label')||field.name||'This field';
   notifyError(`${label}: ${field.validationMessage||'Please check this value.'}`,{id:'form-validation',force:true});field.focus?.();
  };
  document.addEventListener('invalid',invalid,true);return()=>document.removeEventListener('invalid',invalid,true);
 },[]);
 return <Toaster position="top-right" toastOptions={{duration:4500,style:{background:'#123139',color:'#fff',maxWidth:420},success:{iconTheme:{primary:'#6cdbb5',secondary:'#123139'}},error:{duration:6500}}}/>;}
function Confirmation({message,finish}){
 const dialog=useRef(null),label=useId();
 const native=typeof HTMLDialogElement!=='undefined'&&typeof HTMLDialogElement.prototype.showModal==='function';
 useEffect(()=>{
  const previous=document.activeElement,node=dialog.current;
  if(native&&!node.open)node.showModal();
  const timer=setTimeout(()=>finish(false),120000);
  return()=>{clearTimeout(timer);if(native&&node.open)node.close();if(previous?.isConnected)previous.focus?.();};
 },[]);
 const keys=e=>{
  if(e.key==='Escape'){e.preventDefault();finish(false);return;}
  if(e.key==='Tab'){
   const buttons=dialog.current.querySelectorAll('button:not(:disabled)'),first=buttons[0],last=buttons[buttons.length-1];
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  }
 };
 // Render outside the toast's transformed positioning container. The dialog is viewport-centred.
 return createPortal(<>{!native&&<div className="gate-confirm-backdrop" aria-hidden="true"/>}<dialog ref={dialog} open={!native} className="gate-confirm" aria-modal="true" aria-labelledby={label} aria-describedby={label+'-message'} onKeyDown={keys} onCancel={e=>{e.preventDefault();finish(false);}}>
 <h2 id={label}>Please confirm</h2><p id={label+'-message'}>{message}</p><div className="actions"><button type="button" className="btn secondary" autoFocus onClick={()=>finish(false)}>Cancel</button><button type="button" className="btn danger" onClick={()=>finish(true)}>Confirm</button></div>
 </dialog></>,document.body);
}
export function confirmAction(message){return new Promise(resolve=>{let settled=false,id;const finish=value=>{if(settled)return;settled=true;toast.remove(id);resolve(value);};id=toast.custom(<Confirmation message={message} finish={finish}/>,{duration:Infinity,position:'top-center'});});}
