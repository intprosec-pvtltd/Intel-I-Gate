import React from 'react';
import {it,expect,vi,beforeEach} from 'vitest';
import {render,screen,waitFor,act} from '@testing-library/react';
import LiveCameraPreview from '../src/components/LiveCameraPreview';
import {api,connectEvents} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn(),delete:vi.fn()},mediaUrl:path=>'/api'+path,connectEvents:vi.fn()}));
beforeEach(()=>{vi.clearAllMocks();connectEvents.mockReturnValue(vi.fn());api.delete.mockResolvedValue({data:{ok:true}});api.get.mockResolvedValue({status:204,data:new Blob()});});
it('stopped cameras do not negotiate streams or subscribe to AI',()=>{
 render(<LiveCameraPreview camera={{id:'one',name:'Gate',status:'STOPPED'}}/>);
 expect(screen.getByText('Monitoring stopped')).toBeInTheDocument();expect(api.post).not.toHaveBeenCalled();expect(connectEvents).not.toHaveBeenCalled();
});
it('uses existing authenticated JPEG route when WebRTC is unavailable',async()=>{
 const old=window.RTCPeerConnection;window.RTCPeerConnection=undefined;
 const {unmount}=render(<LiveCameraPreview camera={{id:'one',name:'Gate',status:'CONNECTED'}}/>);
 await waitFor(()=>expect(api.get).toHaveBeenCalledWith('/cameras/one/frame',expect.objectContaining({responseType:'blob'})));
 expect(connectEvents).toHaveBeenCalledWith('analysis',expect.any(Function),expect.any(Function));
 expect(api.post).not.toHaveBeenCalled();unmount();window.RTCPeerConnection=old;
});
it('shows measured AI speed and discards metrics when update socket disconnects',async()=>{
 const old=window.RTCPeerConnection;window.RTCPeerConnection=undefined;
 const {unmount}=render(<LiveCameraPreview camera={{id:'one',name:'Gate',status:'CONNECTED'}}/>);
 const [,receive,status]=connectEvents.mock.calls[0];
 act(()=>receive({items:[{camera_id:'one',actual_ai_fps:4.3,result_age_ms:200,rows:[],stale:false}]}));
 expect(screen.getByText('AI: 4.3 FPS measured')).toBeInTheDocument();
 act(()=>status(false));expect(screen.getByText('AI: — FPS measured')).toBeInTheDocument();
 unmount();window.RTCPeerConnection=old;
});

it('Save Event requires confirmation again after destination changes',async()=>{
 const {default:GuardVerificationForm}=await import('../src/components/GuardVerificationForm');
 render(<GuardVerificationForm event={{id:'guard-test',state:'CONFIRMED',verification:{delivery_confirmed:true,flat:'A-101',resident_name:'Resident'}}} onSaved={()=>{}}/>);
 expect(screen.getByRole('button',{name:'Save Event'})).toBeDisabled();
 const {fireEvent}=await import('@testing-library/react');
 fireEvent.change(screen.getByLabelText('Destination Flat Number'),{target:{value:'A-102'}});
 expect(screen.getByRole('button',{name:'Save Event'})).toBeDisabled();
});
