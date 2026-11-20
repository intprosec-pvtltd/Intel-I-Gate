import toast from 'react-hot-toast';
// Share error identities across hooks and compatibility Notice components.
// Bounded storage avoids repeated polling errors and StrictMode duplicate effects.
const errors=new Map();let sequence=0;
export function errorText(value){const detail=typeof value==='string'?value:value?.userMessage||value?.message;return typeof detail==='string'&&detail.trim()?detail:'Something went wrong. Please try again.';}
export function rememberError(value,id){const text=errorText(value);errors.delete(text);errors.set(text,{id,time:Date.now()});if(errors.size>100)errors.delete(errors.keys().next().value);}
export function notifyError(value,{id,force=false}={}){
 if(!value)return;const text=errorText(value),previous=errors.get(text);
 if(!force&&previous&&Date.now()-previous.time<30000)return previous.id;
 const key=id||previous?.id||`error-${++sequence}`;rememberError(text,key);return toast.error(text,{id:key});
}
