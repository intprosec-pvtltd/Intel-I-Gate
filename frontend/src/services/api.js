import axios from 'axios';
export const api=axios.create({baseURL:import.meta.env.VITE_API_BASE||'/api',withCredentials:true,timeout:25000});
api.interceptors.request.use(c=>{c.headers['X-Intel-Request']='1';return c;});
api.interceptors.response.use(r=>r,async e=>{
  const c=e.config;
  if(c?.method==='get'&&!c._retried&&!axios.isCancel(e)&&(!e.response||e.response.status===503)){c._retried=true;await new Promise(r=>setTimeout(r,500));return api(c);}
  if(e.response?.status===401&&!c?.url?.includes('/auth/'))window.dispatchEvent(new Event('intel:unauthorized'));
  const d=e.response?.data?.detail;e.userMessage=Array.isArray(d)?d.map(x=>`${x.loc?.at(-1)}: ${x.msg}`).join('; '):d||(axios.isCancel(e)?'Request cancelled':'Unable to reach server');return Promise.reject(e);
});
export const mediaUrl=path=>`${api.defaults.baseURL}${path}`;
export function connectEvents(channel,onUpdate,onStatus=()=>{}){
  let socket,timer,attempt=0,stopped=false;
  function connect(){
    const base=import.meta.env.VITE_WS_BASE||`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`;
    socket=new WebSocket(`${base}/${channel}`);socket.onopen=()=>{attempt=0;onStatus(true);};
    socket.onmessage=e=>{try{onUpdate(JSON.parse(e.data));}catch{}};
    socket.onclose=e=>{onStatus(false);if(!stopped&&e.code!==1008)timer=setTimeout(connect,Math.min(30000,1000*2**attempt++));};
  }connect();return()=>{stopped=true;clearTimeout(timer);socket?.close();};
}
