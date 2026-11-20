import {notifyError} from '../services/feedback';
import {useEffect,useRef,useState} from 'react';
import {api,mediaUrl,connectEvents} from '../services/api';
import FreshCameraPreview from './FreshCameraPreview';

function waitForIce(pc,signal){
 return new Promise((resolve,reject)=>{
  let timer;
  const finish=error=>{clearTimeout(timer);pc.removeEventListener('icegatheringstatechange',check);signal.removeEventListener('abort',abort);error?reject(error):resolve();};
  const check=()=>{if(pc.iceGatheringState==='complete')finish();};
  const abort=()=>finish(new Error('Preview closed'));
  pc.addEventListener('icegatheringstatechange',check);signal.addEventListener('abort',abort,{once:true});
  timer=setTimeout(()=>finish(new Error('ICE gathering timed out')),8000);check();
 });
}
export default function LiveCameraPreview({camera}){
 const video=useRef(null),canvas=useRef(null),latest=useRef(null),fallbackRef=useRef(null);
 const [mode,setMode]=useState('connecting'),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[stats,setStats]=useState(null);
 useEffect(()=>{if(error)notifyError(error);},[error]);
 const active=['CONNECTED','AI_ERROR'].includes(camera.status);
 useEffect(()=>{
  latest.current=null;setStats(null);
  if(!active){setMode('stopped');return;}
  const stop=connectEvents('analysis',message=>{
   const packet=message.items?.find(item=>item.camera_id===camera.id);
   latest.current=packet?{...packet,received:performance.now()}:null;
   setStats(packet||null);
  },online=>{if(!online){latest.current=null;setStats(null);}});
  return()=>{stop();latest.current=null;};
 },[camera.id,active]);
 useEffect(()=>{
  const timer=setInterval(()=>{
   const node=canvas.current;if(!node)return;
   const ctx=node.getContext('2d');if(!ctx)return;
   ctx.clearRect(0,0,node.width,node.height);
   const packet=latest.current;
   // Never leave boxes frozen over a newer moving person.
   if(!packet||packet.stale||performance.now()-packet.received>800||!active)return;
   if((packet.result_age_ms||0)+performance.now()-packet.received>1000)return;
   for(const row of packet.rows||[]){
    const [x1,y1,x2,y2]=row.box;
    const x=x1*node.width,y=y1*node.height,w=(x2-x1)*node.width,h=(y2-y1)*node.height;
    ctx.strokeStyle=row.possible?'#54e39b':'#f4ce6a';ctx.lineWidth=2;ctx.strokeRect(x,y,w,h);
    const text=`#${row.track_id} · ${row.possible?'Possible delivery · verify':'Person · review'}`;
    ctx.font='16px sans-serif';const width=ctx.measureText(text).width;
    const ty=Math.max(20,y);ctx.fillStyle='#101b28';ctx.fillRect(x,ty-20,width+10,23);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(text,x+4,ty-3);
   }
  },100);
  return()=>clearInterval(timer);
 },[active]);
 useEffect(()=>{
  if(!active)return;
  let pc,peerId,closed=false,timeout;
  const control=new AbortController();setMode('connecting');setError('');
  const fallback=message=>{if(!closed){setMode('mjpeg');setError(message);pc?.close();if(peerId){api.delete(`/preview-sessions/${peerId}`).catch(()=>{});peerId=null;}}};
  fallbackRef.current=fallback;
  async function start(){
   try{
    if(!window.RTCPeerConnection)throw new Error('WebRTC unavailable in this browser');
    pc=new RTCPeerConnection({iceServers:[]});pc.addTransceiver('video',{direction:'recvonly'});
    pc.ontrack=event=>{
     if(closed)return;
     if(video.current){video.current.srcObject=event.streams[0]||new MediaStream([event.track]);video.current.play().catch(()=>{});}
    };
    pc.onconnectionstatechange=()=>{
     if(closed)return;
     if(pc.connectionState==='connected'){clearTimeout(timeout);setMode('webrtc');setError('');}
     if(['failed','disconnected'].includes(pc.connectionState))fallback('WebRTC connection lost. Using JPEG fallback.');
    };
    await pc.setLocalDescription(await pc.createOffer());await waitForIce(pc,control.signal);
    const response=await api.post(`/cameras/${camera.id}/webrtc`,{type:'offer',sdp:pc.localDescription.sdp},{signal:control.signal});
    peerId=response.data.id;
    if(closed){api.delete(`/preview-sessions/${peerId}`).catch(()=>{});return;}
    await pc.setRemoteDescription({type:response.data.type,sdp:response.data.sdp});
    timeout=setTimeout(()=>fallback('WebRTC connection timed out. Using JPEG fallback.'),12000);
   }catch(e){if(!closed)fallback('Smooth video is unavailable on this connection. Using standard JPEG preview.');}
  }
  start();
  return()=>{closed=true;fallbackRef.current=null;control.abort();clearTimeout(timeout);pc?.close();if(video.current)video.current.srcObject=null;if(peerId)api.delete(`/preview-sessions/${peerId}`).catch(()=>{});};
 },[camera.id,active,attempt]);
 useEffect(()=>{
  if(mode!=='webrtc')return;
  let last=-1,changed=performance.now();
  const timer=setInterval(()=>{const now=performance.now(),value=video.current?.currentTime;if(value!=null&&value!==last){last=value;changed=now;}else if(now-changed>6000){fallbackRef.current?.('Camera video stalled. Reconnecting with fresh-frame preview.');}},1000);
  return()=>clearInterval(timer);
 },[mode]);
 return <section aria-label={`${camera.name} live analysis`}>
  <div className="camera-preview realtime-preview">
   {active?<><video ref={video} autoPlay muted playsInline aria-label={`${camera.name} live video`} style={{display:mode==='mjpeg'?'none':'block'}}/>
    {mode==='mjpeg'&&<FreshCameraPreview cameraId={camera.id} className="camera-fresh-image"/>}
    <canvas ref={canvas} width="960" height="540" aria-hidden="true"/>
    <span className="live-dot">{mode==='webrtc'?'LIVE · WebRTC':mode==='mjpeg'?'LIVE · JPEG fallback':'Connecting video…'}</span>
   </>:<span>{camera.status==='STOPPED'?'Monitoring stopped':'Waiting for camera connection…'}</span>}
  </div>
  {active&&<div className="live-analysis-stats"><span>AI: {stats?.actual_ai_fps??'—'} FPS measured</span><span>Result age: {stats?.result_age_ms!=null?`${Math.round(stats.result_age_ms)} ms`:'waiting'}</span><span>{stats?.stale?'Waiting for fresh AI result':'Guard confirmation required'}</span></div>}
  {error&&<p className="muted"><button type="button" className="text-link" onClick={()=>setAttempt(n=>n+1)}>Retry WebRTC</button></p>}
 </section>;
}
