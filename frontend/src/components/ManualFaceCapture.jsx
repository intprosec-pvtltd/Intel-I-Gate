import toast from 'react-hot-toast';
import React,{useRef,useState} from 'react';
import {api} from '../services/api';
import {Button} from './ui';
import FreshCameraPreview from './FreshCameraPreview';
export default function ManualFaceCapture({event,onSaved}){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false);
 const lock=useRef(false);
 const notification=useRef(null);
 async function capture(){
  if(lock.current)return;lock.current=true;setBusy(true);notification.current=toast.loading('Saving snapshot…');
  try{
   const {data}=await api.post(`/events/${event.id}/manual-capture`);
   await api.post(`/events/${event.id}/manual-snapshot`,{token:data.token,left:0,top:0,right:1,bottom:1});
   setOpen(false);toast.success(event.snapshot_id?'Snapshot replaced':'Snapshot saved',{id:notification.current});await onSaved?.();
  }catch(e){toast.error(e.userMessage||'Could not save the snapshot. Check the camera and try again.',{id:notification.current});}
  finally{lock.current=false;setBusy(false);}
 }
 return <section className="manual-capture"><Button type="button" variant="secondary" disabled={busy} onClick={()=>{setOpen(!open);}}>{open?'Close camera':event.snapshot_id?'Retake snapshot':'Capture missed photo'}</Button>
  {open&&<div className="manual-capture-body"><p className="muted">Ask the visitor to face the camera. Capture saves and replaces the photo immediately.</p><FreshCameraPreview cameraId={event.camera_id}/><Button type="button" busy={busy} onClick={capture}>Capture and save photo</Button></div>}

 </section>;
}
