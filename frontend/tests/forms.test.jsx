import React from 'react';
import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import CameraForm from '../src/components/CameraForm';
import GuardVerificationForm from '../src/components/GuardVerificationForm';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
const resident={id:'r1',flat:'A-101',name:'Test Resident',phone:'+919876543210'};
beforeEach(()=>{vi.clearAllMocks();api.get.mockResolvedValue({data:{sms_configured:true,state:'VERIFIED',verified:true,resident_id:'r1',expires_at:new Date(Date.now()+300000).toISOString(),resend_at:new Date().toISOString()}});api.post.mockResolvedValue({data:{id:'visit'}});});
it('supports direct camera stream URLs without exposing separate password inputs',()=>{
 render(<CameraForm onSaved={()=>{}} onCancel={()=>{}}/>);
 expect(screen.getByLabelText('Camera Name')).toBeInTheDocument();expect(screen.getByLabelText('Camera Stream URL (RTSP / HTTP / HTTPS)')).toBeInTheDocument();
 expect(screen.queryByLabelText(/^username$/i)).toBeNull();expect(screen.queryByLabelText(/^password$/i)).toBeNull();
});
it('confirming an OTP-approved visit does not save it until Save Event',async()=>{
 const saved=vi.fn();render(<GuardVerificationForm event={{id:'event',state:'PENDING_VERIFICATION',verification:{delivery_confirmed:true}}} residents={[resident]} onSaved={saved}/>);
 await screen.findByText('Resident approval: Verified');expect(screen.getByRole('button',{name:'Save Event'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'Confirm Visit'}));
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/events/event/verify',expect.objectContaining({resident_id:'r1'})));
 expect(saved).not.toHaveBeenCalled();await waitFor(()=>expect(screen.getByRole('button',{name:'Save Event'})).not.toBeDisabled());
 fireEvent.click(screen.getByRole('button',{name:'Save Event'}));await waitFor(()=>expect(saved).toHaveBeenCalled());
});
