import toast from 'react-hot-toast';
import {confirmAction} from '../components/Notifications';
import {useState,useEffect,useRef,useMemo} from 'react';
import {UploadCloud} from 'lucide-react';
import {api} from '../services/api';
import VideoPreview from '../components/VideoPreview';
import {Title,Button,Notice,Empty,Badge,Field,EventCard,Pager,useData,useAction} from '../components/ui';

const active=status=>['RUNNING','QUEUED'].includes(status);
export default function VideoAnalysis(){
 const d=useData('/videos',3000),a=useAction();
 const [roles,setRoles]=useState({});
 const [queue,setQueue]=useState([]),[uploading,setUploading]=useState(false),[selected,setSelected]=useState(null);
 const [state,setState]=useState(null),[result,setResult]=useState(null),[offset,setOffset]=useState(0),[deleted,setDeleted]=useState(new Set());
 const controller=useRef(),cancelBatch=useRef(false),uploadLock=useRef(false),mounted=useRef(true);
 const videos=useMemo(()=>(d.data||[]).filter(v=>!deleted.has(v.id)),[d.data,deleted]);
 const selectVideo=id=>{setSelected(id);setOffset(0);setState(null);setResult(null);};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;cancelBatch.current=true;controller.current?.abort();};},[]);
 useEffect(()=>{if(!selected&&videos.length)setSelected(videos[0].id);},[selected,videos]);
 useEffect(()=>{
  if(!selected)return;
  let alive=true,timer;const control=new AbortController();
  async function load(){
   try{
    const [s,r]=await Promise.all([api.get(`/videos/${selected}/status`,{signal:control.signal}),api.get(`/videos/${selected}/results?offset=${offset}`,{signal:control.signal})]);
    if(alive){setState(s.data);setResult(r.data);}
   }catch(e){if(alive)a.setError(e.userMessage||e.message);}
   finally{if(alive)timer=setTimeout(load,3000);}
  }
  load();return()=>{alive=false;control.abort();clearTimeout(timer);};
 },[selected,offset]);
 const updateQueue=(id,patch)=>{if(mounted.current)setQueue(rows=>rows.map(row=>row.id===id?{...row,...patch}:row));};
 const chooseFiles=e=>{
  if(uploadLock.current)return;
  setQueue(Array.from(e.target.files||[]).map((file,index)=>({id:`${Date.now()}-${index}`,file,name:file.name,status:'QUEUED',progress:0,error:''})));
  e.target.value='';
 };
 const upload=async e=>{
  e.preventDefault();if(uploadLock.current)return;
  const batch=queue.filter(row=>row.status==='QUEUED');if(!batch.length)return;
  uploadLock.current=true;cancelBatch.current=false;setUploading(true);a.setError('');let first=true;
  try{
   for(const item of batch){
    if(cancelBatch.current)break;
    updateQueue(item.id,{status:'UPLOADING',progress:0,error:''});
    controller.current=new AbortController();
    const notice=toast.loading(`Uploading ${item.name}…`);
    try{
     const body=new FormData();body.append('file',item.file);
     const response=await api.post('/videos/upload',body,{
      timeout:0,signal:controller.current.signal,
      onUploadProgress:p=>updateQueue(item.id,{progress:p.total?Math.round(p.loaded/p.total*100):0})
     });
     updateQueue(item.id,{status:'UPLOADED',progress:100});toast.success(`${item.name} uploaded`,{id:notice});
     if(mounted.current){if(first){selectVideo(response.data.id);first=false;}await d.refresh();}
    }catch(error){
     if(cancelBatch.current)toast('Upload cancelled',{id:notice});else toast.error(`${item.name}: ${error.userMessage||error.message||'Upload failed'}`,{id:notice});
     updateQueue(item.id,{status:cancelBatch.current?'CANCELLED':'FAILED',error:cancelBatch.current?'Upload cancelled; check the uploaded list before retrying.':error.userMessage||error.message});
    }
   }
  }finally{
   uploadLock.current=false;
   if(mounted.current){
    setUploading(false);
    if(cancelBatch.current)setQueue(rows=>rows.map(row=>row.status==='QUEUED'?{...row,status:'CANCELLED'}:row));
    d.refresh();
   }
  }
 };
 const action=(v,mode)=>a.run(async()=>{
  const role=roles[v.id]||v.test_role;
  if(mode==='analyze'&&!role)throw new Error('Choose Entry or Exit before starting analysis.');
  await api.post(`/videos/${v.id}/${mode}`,mode==='analyze'?{test_role:role}:undefined);
  if(selected!==v.id)selectVideo(v.id);
  setState({status:mode==='analyze'?'RUNNING':'CANCELLED',progress:0});await d.refresh();
 },mode==='analyze'?'Video analysis started':'Video analysis cancelled');
 const deleteVideo=async v=>{
  if(!await confirmAction(`Delete "${v.filename}" and its source video file? Saved visits and face evidence will be retained.`))return;
  a.run(async()=>{
   const response=await api.delete(`/videos/${v.id}`);
   setDeleted(previous=>new Set([...previous,v.id]));
   if(selected===v.id)selectVideo(null);
   await d.refresh();return response.data;
  },result=>result?.warning?'Video removed; source-file cleanup is pending':'Video deleted');
 };
 const pending=queue.filter(row=>row.status==='QUEUED').length;
 const uploaded=queue.filter(row=>row.status==='UPLOADED').length;
 return <>
  <Title title="Video testing">Test entry and exit recordings without changing live visitor records.</Title><div className="test-mode-banner"><b>LOCAL TESTING ONLY</b><span>Label each recording Entry or Exit before analysis. Confirm and save entry visitors, then review exit observations in Visit history.</span></div>
  <Notice>{a.error||d.error}</Notice>
  <form className="upload-panel" onSubmit={upload}>
   <UploadCloud size={36}/><div><h2>Upload recorded footage</h2><p>Select multiple MP4, MOV or AVI files. Each video is validated and uploaded individually.</p>
    <input type="file" multiple aria-label="Select videos" accept="video/mp4,video/quicktime,video/x-msvideo" disabled={uploading} onChange={chooseFiles}/>
   </div>
   <Button disabled={!pending||a.busy} busy={uploading}>Upload {pending||''} {pending===1?'Video':'Videos'}</Button>
   {uploading&&<Button type="button" variant="secondary" onClick={()=>{cancelBatch.current=true;controller.current?.abort();}}>Cancel remaining uploads</Button>}
  </form>
  {!!queue.length&&<section className="panel upload-queue" aria-label="Upload queue">
   <div className="section-heading"><h2>Upload queue</h2><span role="status">{uploaded} of {queue.length} uploaded successfully</span></div>
   {queue.map(item=><div className="upload-queue-row" key={item.id}>
    <div className="upload-queue-info"><b>{item.name}</b><small>{(item.file.size/1048576).toFixed(1)} MB</small><Badge>{item.status}</Badge></div>
    {item.status==='UPLOADING'&&<><progress aria-label={`Upload progress for ${item.name}`} max="100" value={item.progress}/><small>{item.progress===100?'Validating video…':`${item.progress}% transferred`}</small></>}
    
   </div>)}
   {!uploading&&queue.some(row=>['FAILED','CANCELLED'].includes(row.status))&&<Button type="button" variant="secondary" onClick={()=>setQueue(rows=>rows.map(row=>['FAILED','CANCELLED'].includes(row.status)?{...row,status:'QUEUED',progress:0,error:''}:row))}>Queue unsuccessful uploads again</Button>}
  </section>}
  <div className="video-layout analysis-layout"><section className="panel"><h2>Uploaded videos</h2>
   {videos.length?videos.map(v=><div className={`video-row ${selected===v.id?'selected':''}`} key={v.id}>
    <button className="video-select" onClick={()=>selectVideo(v.id)}><b>{v.filename}</b><small>{(v.size/1048576).toFixed(1)} MB · {v.duration.toFixed(1)} seconds</small></button>
    <Badge>{v.status}</Badge><Field label={`Test label for ${v.filename}`}><select aria-label={`Test label for ${v.filename}`} disabled={active(v.status)||!!v.test_role} value={v.test_role||roles[v.id]||''} onChange={e=>setRoles({...roles,[v.id]:e.target.value})}><option value="">Choose Entry or Exit</option><option value="entry">Entry video · test</option><option value="exit">Exit video · test</option></select></Field>{v.test_role&&<small className="muted">The test label is saved with this recording. Upload another copy to change it.</small>}<div className="actions">
     <Button variant="secondary" busy={a.busy} disabled={active(v.status)||v.status==='EXPIRED'||!(v.test_role||roles[v.id])} onClick={()=>action(v,'analyze')}>{v.status==='COMPLETED'?'Analyze Again':'Start Analysis'}</Button>
     <Button variant="ghost" busy={a.busy} disabled={!active(v.status)} onClick={()=>action(v,'cancel')}>Cancel Analysis</Button>
     <Button variant="danger" busy={a.busy} disabled={active(v.status)} aria-label={`Delete video ${v.filename}`} onClick={()=>deleteVideo(v)}>Delete Video</Button>
    </div>{active(v.status)&&<p className="muted">Cancel analysis before deleting this video.</p>}
   </div>):<Empty title="No uploaded videos">Select one or more videos above to begin.</Empty>}
  </section><div>
   {selected&&<VideoPreview key={selected} videoId={selected} status={state?.status||videos.find(v=>v.id===selected)?.status}/>}
   <section className="panel"><h2>Analysis results</h2><p className="muted">Reanalysis creates new observations; existing test records remain. Each confirmed entry must be saved before it can appear on the map.</p>{selected?<>
    <Badge>{state?.status||'LOADING'}</Badge><progress max="100" value={state?.progress||0}/><p>{(state?.progress||0).toFixed(1)}% processed</p><Notice>{state?.error}</Notice>
    <h3>Detection timeline</h3>{result?.timeline?.length?result.timeline.map((x,i)=><p key={i} className="timeline-item"><b>+{x.seconds.toFixed(1)}s</b> {x.evidence.objects?.map(o=>o.label).join(', ')||'Zone crossing'}</p>):<p className="muted">No delivery evidence recorded yet.</p>}
    <p className="muted">Video positions are test evidence, not real entry or exit dates.</p>{(state?.test_role||videos.find(v=>v.id===selected)?.test_role)==='exit'&&<a className="text-link" href="/history">Review these exit observations in Visit history →</a>}
   </>:<p className="muted">Choose an uploaded video.</p>}</section>
  </div></div>
  {!!result?.events?.length&&<><div className="section-heading"><h2>Visitors in this video</h2></div><div className="event-grid">{result.events.map(e=><EventCard key={e.id} event={e}/>)}</div></>}
  {selected&&<Pager offset={offset} setOffset={setOffset} count={Math.max(result?.events?.length||0,result?.timeline?.length||0)} size={100}/>}
 </>;
}
