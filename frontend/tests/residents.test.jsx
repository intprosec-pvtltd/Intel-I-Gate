vi.mock('../src/components/Notifications',()=>({confirmAction:vi.fn(async()=>true)}));
import React from 'react';
import {beforeEach,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import Residents from '../src/pages/Residents';
import {confirmAction} from '../src/components/Notifications';
import GuardVerificationForm from '../src/components/GuardVerificationForm';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn(),delete:vi.fn()}}));
const rows=[{id:'one',name:'Resident One',flat:'A-101',phone:'+919876543210'},{id:'two',name:'Resident Two',flat:'A-101',phone:'+919876543211'}];
beforeEach(()=>{vi.clearAllMocks();api.get.mockImplementation(path=>Promise.resolve({data:path==='/residents'?rows:{sms_configured:true,state:'NONE'}}));api.post.mockResolvedValue({data:{}});api.put.mockResolvedValue({data:{}});api.delete.mockResolvedValue({data:{}});});
it('resident form adds and edits all contact fields',async()=>{
 render(<Residents/>);await screen.findByText('Resident One');
 fireEvent.change(screen.getByLabelText('Resident name'),{target:{value:'New Resident'}});fireEvent.change(screen.getByLabelText('Flat number'),{target:{value:'B-2'}});fireEvent.change(screen.getByLabelText('Phone number'),{target:{value:'9876543212'}});
 fireEvent.click(screen.getByRole('button',{name:'Add resident'}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/residents',{name:'New Resident',flat:'B-2',phone:'9876543212'}));
 await waitFor(()=>expect(screen.getByLabelText('Resident name')).toHaveValue(''));fireEvent.click(screen.getAllByRole('button',{name:'Edit'})[0]);
 expect(screen.getByLabelText('Phone number')).toHaveValue('+919876543210');fireEvent.change(screen.getByLabelText('Phone number'),{target:{value:'9876543213'}});fireEvent.click(screen.getByRole('button',{name:'Update resident'}));
 await waitFor(()=>expect(api.put).toHaveBeenCalledWith('/residents/one',expect.objectContaining({phone:'9876543213'})));
});
it('removing a resident requires confirmation and refreshes directory',async()=>{
 render(<Residents/>);await screen.findByText('Resident One');fireEvent.click(screen.getAllByRole('button',{name:'Delete'})[0]);await waitFor(()=>expect(api.delete).toHaveBeenCalledWith('/residents/one'));expect(confirmAction).toHaveBeenCalledWith(expect.stringContaining('Saved visit history is retained'));
});
it('shared flats require explicit selection and clear approval on a flat change',async()=>{
 render(<GuardVerificationForm event={{id:'event'}} residents={rows} onSaved={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('Destination Flat Number'),{target:{value:'a-101'}});expect(screen.getByLabelText('Destination Resident Name')).toHaveValue('');
 fireEvent.change(screen.getByLabelText('Select resident'),{target:{value:'two'}});expect(screen.getByLabelText('Resident phone number')).toHaveValue('+919876543211');
 fireEvent.change(screen.getByLabelText('Destination Flat Number'),{target:{value:'B-999'}});expect(screen.getByLabelText('Resident phone number')).toHaveValue('');expect(screen.getByRole('button',{name:'Send OTP'})).toBeDisabled();expect(screen.getByRole('button',{name:'Save Event'})).toBeDisabled();
});
it('restores valid resident OTP status without bypassing Confirm Visit',async()=>{
 api.get.mockResolvedValue({data:{sms_configured:true,state:'VERIFIED',verified:true,resident_id:'one',challenge_id:'challenge',expires_at:new Date(Date.now()+300000).toISOString(),resend_at:new Date().toISOString()}});
 render(<GuardVerificationForm event={{id:'event',verification:{delivery_confirmed:true}}} residents={rows} onSaved={()=>{}}/>);
 await screen.findByText('Resident approval: Verified');expect(screen.getByRole('button',{name:'Confirm Visit'})).not.toBeDisabled();expect(screen.getByRole('button',{name:'Save Event'})).toBeDisabled();
});

it('flat lookup lists stored residents on focus, filters and selects a partial match',async()=>{
 const directory=[{id:'ten',name:'Resident Ten',flat:'A-10',phone:'+919876543210'},{id:'two',name:'Resident Two',flat:'A-2',phone:'+919876543211'},{id:'bee',name:'Other Resident',flat:'B-204',phone:'+919876543212'}];
 render(<GuardVerificationForm event={{id:'lookup'}} residents={directory} onSaved={()=>{}}/>);
 const input=screen.getByRole('combobox',{name:'Destination Flat Number'});fireEvent.focus(input);
 expect(screen.getAllByRole('option').filter(x=>x.tagName==='BUTTON').map(x=>x.textContent)).toEqual(['A-2Resident Two','A-10Resident Ten','B-204Other Resident']);
 fireEvent.change(input,{target:{value:'b-2'}});expect(screen.getByRole('option',{name:'B-204 Other Resident'})).toBeInTheDocument();expect(screen.queryByRole('option',{name:'A-2 Resident Two'})).toBeNull();
 fireEvent.click(screen.getByRole('option',{name:'B-204 Other Resident'}));expect(input).toHaveValue('B-204');expect(screen.getByLabelText('Destination Resident Name')).toHaveValue('Other Resident');expect(screen.getByLabelText('Resident phone number')).toHaveValue('+919876543212');expect(input).toHaveAttribute('aria-expanded','false');
});
it('flat lookup supports name search, keyboard selection and Escape',()=>{
 render(<GuardVerificationForm event={{id:'lookup'}} residents={rows} onSaved={()=>{}}/>);
 const input=screen.getByRole('combobox',{name:'Destination Flat Number'});fireEvent.change(input,{target:{value:'Resident Two'}});fireEvent.keyDown(input,{key:'ArrowDown'});fireEvent.keyDown(input,{key:'Enter'});
 expect(input).toHaveValue('A-101');expect(screen.getByLabelText('Destination Resident Name')).toHaveValue('Resident Two');
 fireEvent.focus(input);fireEvent.keyDown(input,{key:'Escape'});expect(input).toHaveAttribute('aria-expanded','false');
});
