import React from 'react';
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,waitFor,within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import toast from 'react-hot-toast';
import Account from '../src/pages/Account';
import Dashboard from '../src/pages/Dashboard';
import Notifications from '../src/components/Notifications';
import {WorkspaceContext} from '../src/components/ui';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),put:vi.fn(),post:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn(()=>()=>{})}));
afterEach(()=>{vi.clearAllMocks();toast.remove();});
const user={id:'admin',email:'admin@example.test',role:'admin',apartment_name:null};
function showAccount(){return render(<WorkspaceContext.Provider value={{user}}><Notifications/><Account/></WorkspaceContext.Provider>);}
it('lets an existing admin add an apartment name without changing the login or password',async()=>{
 const update=vi.fn();window.addEventListener('intel:profile-updated',update);
 api.put.mockResolvedValue({data:{ok:true,sign_in_required:false,user:{...user,apartment_name:'Lake View'}}});
 try{
  showAccount();expect(screen.getByLabelText('Name (apartment name)')).toHaveValue('');
  expect(screen.getByLabelText('Email ID')).toHaveValue('admin@example.test');
  fireEvent.change(screen.getByLabelText('Name (apartment name)'),{target:{value:'Lake View'}});
  fireEvent.click(screen.getByRole('button',{name:'Save account details'}));
  await screen.findByText('Account details saved');
  expect(api.put).toHaveBeenCalledWith('/account/profile',{apartment_name:'Lake View',email:'admin@example.test'});
  expect(update).toHaveBeenCalledOnce();expect(api.post).not.toHaveBeenCalled();
 }finally{window.removeEventListener('intel:profile-updated',update);}
});
it('requires password confirmation for changed login email and requests a fresh sign-in',async()=>{
 const changed=vi.fn();window.addEventListener('intel:password-changed',changed);
 api.put.mockResolvedValue({data:{ok:true,sign_in_required:true,user:{...user,email:'new@example.test',apartment_name:'Lake View'}}});
 try{
  showAccount();fireEvent.change(screen.getByLabelText('Name (apartment name)'),{target:{value:'Lake View'}});
  fireEvent.change(screen.getByLabelText('Email ID'),{target:{value:'new@example.test'}});
  const password=screen.getByLabelText('Current password to change email');expect(password).toBeRequired();
  fireEvent.change(password,{target:{value:'old-password'}});fireEvent.click(screen.getByRole('button',{name:'Save account details'}));
  await screen.findByText('Login email updated. Please sign in with your new email.');
  expect(changed).toHaveBeenCalledOnce();expect(api.put).toHaveBeenCalledWith('/account/profile',{apartment_name:'Lake View',email:'new@example.test',current_password:'old-password'});
 }finally{window.removeEventListener('intel:password-changed',changed);}
});
it('shows configured camera count separately from actual connected streams',async()=>{
 api.get.mockImplementation(path=>Promise.resolve({data:path==='/dashboard/summary'?{cameras:2,connected:0,pending:0,active_visits:0,completed:6}:path==='/system/status'?{timezone:'Asia/Kolkata'}:path==='/visit-alerts'?[]:{items:[]}}));
 render(<MemoryRouter><Dashboard/></MemoryRouter>);
 const card=screen.getByRole('link',{name:/Connected cameras/});
 await waitFor(()=>expect(within(card).getByText('2 configured · 0 streaming →')).toBeInTheDocument());
 expect(within(card).getByText('0')).toBeInTheDocument();expect(card).toHaveAttribute('href','/live');
});
