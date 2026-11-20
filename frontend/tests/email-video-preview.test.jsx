vi.mock('../src/components/Notifications',()=>({confirmAction:vi.fn(async()=>true)}));
import React from 'react';
import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {render,screen,fireEvent,waitFor,act} from '@testing-library/react';
import Login from '../src/pages/Login';
import VideoAnalysis from '../src/pages/VideoAnalysis';
import ManualFaceCapture from '../src/components/ManualFaceCapture';
import FreshCameraPreview from '../src/components/FreshCameraPreview';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn(),delete:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
beforeEach(()=>{vi.clearAllMocks();URL.createObjectURL=vi.fn(()=> 'blob:camera');URL.revokeObjectURL=vi.fn();api.post.mockResolvedValue({data:{token:'a'.repeat(32)}});});
afterEach(()=>vi.useRealTimers());
it('signs in using email and preserves the entered password',async()=>{
 const onLogin=vi.fn();api.post.mockResolvedValue({data:{email:'guard@example.test',role:'guard'}});
 render(<Login onLogin={onLogin}/>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'GUARD@example.test'}});
 fireEvent.change(screen.getByLabelText('Password'),{target:{value:'test-password-123'}});
 fireEvent.click(screen.getByRole('button',{name:'Sign in'}));
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/auth/login',{email:'guard@example.test',password:'test-password-123'}));
 expect(onLogin).toHaveBeenCalled();
});
it('requires an explicit Entry or Exit label before analysis',async()=>{
 const video={id:'v1',filename:'entry.mp4',duration:10,size:100,status:'UPLOADED',test_role:null};
 api.get.mockImplementation(path=>Promise.resolve({data:path==='/videos'?[video]:path.endsWith('/status')?{status:'UPLOADED',progress:0}:path.includes('/results')?{events:[],timeline:[]}:new Blob(),status:204,headers:{}}));
 render(<VideoAnalysis/>);await screen.findByRole('button',{name:'Start Analysis'});
 expect(screen.getByRole('button',{name:'Start Analysis'})).toBeDisabled();
 fireEvent.change(screen.getByRole('combobox',{name:'Test label for entry.mp4'}),{target:{value:'entry'}});
 fireEvent.click(screen.getByRole('button',{name:'Start Analysis'}));
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/videos/v1/analyze',{test_role:'entry'}));
});
it('retakes and replaces the photo without a crop or extra confirmation',async()=>{
 api.get.mockResolvedValue({status:204,data:new Blob()});const saved=vi.fn();
 render(<ManualFaceCapture event={{id:'e1',camera_id:'c1',snapshot_id:'old'}} onSaved={saved}/>);
 fireEvent.click(screen.getByRole('button',{name:'Retake snapshot'}));
 await waitFor(()=>expect(api.get).toHaveBeenCalledWith('/cameras/c1/frame',expect.any(Object)));
 fireEvent.click(screen.getByRole('button',{name:'Capture and save photo'}));
 await waitFor(()=>expect(saved).toHaveBeenCalled());
 expect(api.post).toHaveBeenCalledWith('/events/e1/manual-snapshot',{token:'a'.repeat(32),left:0,top:0,right:1,bottom:1});
 expect(screen.queryByText('Photo saved successfully.')).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Use selected snapshot'})).toBeNull();
});
it('does not stack camera polling requests while a response is outstanding',async()=>{
 vi.useFakeTimers();let finish;api.get.mockReturnValue(new Promise(resolve=>{finish=resolve;}));
 const {unmount}=render(<FreshCameraPreview cameraId="c1"/>);
 await act(async()=>{vi.advanceTimersByTime(2000);});expect(api.get).toHaveBeenCalledTimes(1);
 await act(async()=>{finish({status:204,data:new Blob()});});
 unmount();expect(api.get.mock.calls[0][1].signal.aborted).toBe(true);
});
