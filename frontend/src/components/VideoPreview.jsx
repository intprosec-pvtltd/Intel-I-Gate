import {useEffect,useState} from 'react';
import {VideoOff} from 'lucide-react';
import {api} from '../services/api';
import {Badge,Notice} from './ui';

export default function VideoPreview({videoId,status}){
 const [frame,setFrame]=useState(null),[error,setError]=useState('');
 const active=['RUNNING','QUEUED'].includes(status);
 useEffect(()=>()=>{if(frame?.url)URL.revokeObjectURL(frame.url);},[frame?.url]);
 useEffect(()=>{
  let stopped=false,timer,sequence;
  const controller=new AbortController();
  async function load(){
   try{
    const response=await api.get(`/videos/${videoId}/preview`,{responseType:'blob',signal:controller.signal});
    if(stopped)return;
    setError('');
    if(response.status===200){
     const next=response.headers['x-preview-sequence'];
     if(next!==sequence){
      sequence=next;
      setFrame({url:URL.createObjectURL(response.data),seconds:Number(response.headers['x-frame-seconds']||0)});
     }
    }
   }catch(e){if(!stopped)setError(e.userMessage||'Analysis preview unavailable');}
   finally{if(!stopped&&active)timer=setTimeout(load,200);}
  }
  setFrame(null);load();
  return()=>{stopped=true;controller.abort();clearTimeout(timer);};
 },[videoId,active,status]);
 return <section className="panel analysis-preview" aria-label="Video analysis preview">
  <div className="preview-heading"><div><h2>Analysis preview</h2><p className="muted">Frames processed by AI · person boxes and tracking IDs</p></div><Badge>{status||'LOADING'}</Badge></div>
  <div className="analysis-frame">{frame?<img src={frame.url} alt={`AI analyzed video frame at ${frame.seconds.toFixed(1)} seconds`}/>:<div className="preview-placeholder"><VideoOff size={36}/><p>{active?'Waiting for the first analyzed frame…':'No analyzed preview available'}</p><small>{active?'The first frame appears after the models finish loading.':'Start analysis on a new upload. Previews from earlier sessions are not stored.'}</small></div>}</div>
  <div className="preview-caption"><span>{frame?`Source time +${frame.seconds.toFixed(1)}s`:'No frame received yet'}</span><span>{active?'Updates during processing':frame?'Last analyzed frame':'Preview available during analysis'}</span></div>
  <p className="muted">Processing speed determines the update rate. Boxes mark tracked people; delivery suggestions require guard verification. The last frame is retained temporarily, for up to 15 minutes, while this backend stays running.</p>
  <Notice>{error}</Notice>
 </section>;
}
