import React,{useEffect,useState} from 'react';
import {api} from '../services/api';

// One bounded request at a time; retries automatically without stacking streams.
export default function FreshCameraPreview({cameraId,className='manual-live'}){
 const [url,setUrl]=useState(''),[waiting,setWaiting]=useState(true);
 useEffect(()=>{
  const control=new AbortController();let alive=true,timer,current='';
  setUrl('');setWaiting(true);
  async function load(){
   try{
    const r=await api.get(`/cameras/${encodeURIComponent(cameraId)}/frame`,{responseType:'blob',signal:control.signal,timeout:4000});
    if(!alive)return;
    if(r.status===200&&r.data.size){const next=URL.createObjectURL(r.data);const old=current;current=next;setUrl(next);setWaiting(false);if(old)URL.revokeObjectURL(old);}
    else {setWaiting(true);setUrl('');if(current){URL.revokeObjectURL(current);current='';}}
   }catch(e){if(alive){setWaiting(true);setUrl('');if(current){URL.revokeObjectURL(current);current='';}}}
   finally{if(alive)timer=setTimeout(load,250);}
  }
  load();return()=>{alive=false;control.abort();clearTimeout(timer);if(current)URL.revokeObjectURL(current);};
 },[cameraId]);
 return <div className="fresh-preview">{url&&<img className={className} src={url} alt="Live camera preview"/>}{waiting&&<p role="status" className="preview-wait">Waiting for a fresh frame. Check that the camera is running.</p>}</div>;
}
