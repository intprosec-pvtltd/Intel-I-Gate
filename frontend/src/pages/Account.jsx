import {useContext,useEffect,useState} from 'react';
import {Building2,ShieldCheck} from 'lucide-react';
import {api} from '../services/api';
import {Title,Field,Button,useAction,WorkspaceContext} from '../components/ui';
export default function Account(){
 const {user}=useContext(WorkspaceContext),profile=useAction(),passwordAction=useAction();
 const [name,setName]=useState(user.apartment_name||''),[email,setEmail]=useState(user.email||''),[emailPassword,setEmailPassword]=useState('');
 const [old,setOld]=useState(''),[password,setPassword]=useState(''),[confirm,setConfirm]=useState('');
 useEffect(()=>{setName(user.apartment_name||'');setEmail(user.email||'');},[user.id,user.apartment_name,user.email]);
 const emailChanged=email.trim().toLowerCase()!==(user.email||'');
 return <><Title title="My account">Manage your apartment name, login email and password.</Title>
  <div className="account-settings-grid">
   <section className="panel"><div className="section-heading account-section-heading"><h2><Building2 size={20}/> Account details</h2><span className="badge">{user.role}</span></div>
    {!user.apartment_name&&<p className="muted account-help">Your existing login is ready to use. Add an apartment name below to complete your profile.</p>}
    <form className="form" onSubmit={e=>{e.preventDefault();profile.run(async()=>{
     const response=await api.put('/account/profile',{apartment_name:name.trim(),email:email.trim(),...(emailChanged?{current_password:emailPassword}:{})});setEmailPassword('');
     if(response.data.sign_in_required)window.dispatchEvent(new Event('intel:password-changed'));
     else window.dispatchEvent(new CustomEvent('intel:profile-updated',{detail:response.data.user}));
     return response.data;
    },data=>data.sign_in_required?'Login email updated. Please sign in with your new email.':'Account details saved');}}>
     <Field label="Name (apartment name)" autoComplete="organization" required maxLength={120} placeholder="Enter your apartment or community name" value={name} onChange={e=>setName(e.target.value)}/>
     <Field label="Email ID" type="email" autoComplete="username" required maxLength={100} value={email} onChange={e=>setEmail(e.target.value)}/>
     {emailChanged&&<><Field label="Current password to change email" type="password" autoComplete="current-password" required maxLength={200} value={emailPassword} onChange={e=>setEmailPassword(e.target.value)}/><p className="muted">Changing the email signs out your sessions. Use the new email next time you log in.</p></>}
     <Button busy={profile.busy}>Save account details</Button>
    </form>
   </section>
   <section className="panel"><div className="section-heading account-section-heading"><h2><ShieldCheck size={20}/> Change password</h2></div><p className="muted account-help">Use at least 12 characters. Your current password is never displayed or returned.</p>
    <form className="form" onSubmit={e=>{e.preventDefault();passwordAction.run(async()=>{if(password!==confirm)throw new Error('New passwords do not match');await api.post('/account/password',{current_password:old,new_password:password});setOld('');setPassword('');setConfirm('');window.dispatchEvent(new Event('intel:password-changed'));},'Password changed. Please sign in again.');}}>
     <Field label="Current password" type="password" autoComplete="current-password" required maxLength={200} value={old} onChange={e=>setOld(e.target.value)}/>
     <Field label="New password" type="password" autoComplete="new-password" required minLength={12} maxLength={200} value={password} onChange={e=>setPassword(e.target.value)}/>
     <Field label="Confirm new password" type="password" autoComplete="new-password" required minLength={12} maxLength={200} value={confirm} onChange={e=>setConfirm(e.target.value)}/>
     <Button busy={passwordAction.busy}>Change password</Button>
    </form>
   </section>
  </div>
 </>;
}
