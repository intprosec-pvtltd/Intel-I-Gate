import React,{StrictMode} from 'react';
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,waitFor,act} from '@testing-library/react';
import toast from 'react-hot-toast';
import Notifications from '../src/components/Notifications';
import {Notice,useAction,Button} from '../src/components/ui';
import Login from '../src/pages/Login';
import CameraForm from '../src/components/CameraForm';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{post:vi.fn(),put:vi.fn(),get:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn(()=>()=>{})}));
afterEach(()=>{toast.remove();vi.clearAllMocks();});
function Action({work}){const a=useAction();return <><Notice>{a.error}</Notice><Button onClick={()=>a.run(work,'Visit saved')}>Save</Button></>;}
it('an action error has one toast and no inline duplicate, including StrictMode',async()=>{
 const work=vi.fn().mockRejectedValue({userMessage:'Unique camera failure'});
 const {container}=render(<StrictMode><Notifications/><Action work={work}/></StrictMode>);
 fireEvent.click(screen.getByRole('button',{name:'Save'}));
 await screen.findByText('Unique camera failure');
 expect(screen.getAllByText('Unique camera failure')).toHaveLength(1);
 expect(container.querySelector('.notice')).toBeNull();
});
it('repeated polling messages and remounts do not create duplicate error toasts',async()=>{
 const {rerender}=render(<><Notifications/><Notice>Unique polling failure</Notice></>);
 await screen.findByText('Unique polling failure');
 rerender(<><Notifications/><Notice key="new">Unique polling failure</Notice><Notice>Unique polling failure</Notice></>);
 expect(screen.getAllByText('Unique polling failure')).toHaveLength(1);
});
it('updates the loading toast to an action success and prevents duplicate submissions',async()=>{
 let finish;const work=vi.fn(()=>new Promise(resolve=>{finish=resolve;}));render(<><Notifications/><Action work={work}/></>);
 const button=screen.getByRole('button',{name:'Save'});fireEvent.click(button);fireEvent.click(button);
 expect(work).toHaveBeenCalledOnce();expect(await screen.findByText('Working…')).toBeInTheDocument();
 await act(async()=>finish());await screen.findByText('Visit saved');
 expect(screen.queryByText('Working…')).not.toBeInTheDocument();expect(screen.getAllByText('Visit saved')).toHaveLength(1);
});
it('login success is action-specific and shown only once',async()=>{
 api.post.mockResolvedValue({data:{id:'user'}});const onLogin=vi.fn();render(<><Notifications/><Login onLogin={onLogin}/></>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'guard@example.test'}});
 fireEvent.change(screen.getByLabelText('Password'),{target:{value:'test-password-123'}});
 fireEvent.submit(screen.getByRole('button',{name:/Sign in/}).closest('form'));
 await screen.findByText('Login successful');expect(onLogin).toHaveBeenCalledOnce();expect(screen.getAllByText('Login successful')).toHaveLength(1);
});
it('an HTTP 200 camera test with connected false is a failure, never success',async()=>{
 api.post.mockResolvedValue({data:{connected:false,message:'Stream cannot be decoded'}});
 render(<><Notifications/><CameraForm onSaved={()=>{}} onCancel={()=>{}}/></>);
 fireEvent.change(screen.getByLabelText('Camera Stream URL (RTSP / HTTP / HTTPS)'),{target:{value:'rtsp://192.168.0.3:554/stream'}});
 fireEvent.click(screen.getByRole('button',{name:'Test Connection'}));
 await screen.findByText('Stream cannot be decoded');expect(screen.getAllByText('Stream cannot be decoded')).toHaveLength(1);
 expect(screen.queryByText('Camera connected successfully')).not.toBeInTheDocument();
});
it('browser required-field validation uses a toast and preserves invalid form blocking',async()=>{
 render(<><Notifications/><form><label>Email<input name="email" type="email" required/></label><button>Submit</button></form></>);
 const field=screen.getByRole('textbox');fireEvent.invalid(field);
 await waitFor(()=>expect(screen.getByText(/email: /)).toBeInTheDocument());expect(field).toHaveFocus();expect(field.checkValidity()).toBe(false);
});
it('logout reports success once and returns to the login screen',async()=>{
 const {default:App}=await import('../src/App');
 api.get.mockImplementation(path=>Promise.resolve({data:path==='/auth/me'?{id:'guard',email:'guard@example.test',role:'guard'}:path==='/system/status'?{timezone:'Asia/Kolkata'}:path==='/dashboard/summary'?{}:[]}));
 api.post.mockResolvedValue({data:{ok:true}});render(<><Notifications/><App/></>);
 fireEvent.click(await screen.findByRole('button',{name:'Sign out'}));
 await screen.findByText('Logged out successfully');expect(screen.getAllByText('Logged out successfully')).toHaveLength(1);
 expect(await screen.findByRole('button',{name:/Sign in/})).toBeInTheDocument();
});
