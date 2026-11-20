import React from 'react';
import {it,expect,vi,afterEach} from 'vitest';
import {render,screen,fireEvent,act,waitFor} from '@testing-library/react';
import toast from 'react-hot-toast';
import {MemoryRouter} from 'react-router-dom';
import Notifications,{confirmAction} from '../src/components/Notifications';
import VisitorLogs from '../src/pages/VisitorLogs';
import ResidentResponse from '../src/pages/ResidentResponse';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
afterEach(()=>{toast.remove();vi.clearAllMocks();history.replaceState(null,'','/');});
it('confirmation requires an explicit decision and returns the decision',async()=>{
 render(<Notifications/>);let result;act(()=>{result=confirmAction('Delete this record?');});
 expect(await screen.findByRole('dialog')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}));expect(await result).toBe(false);
 act(()=>{result=confirmAction('Confirm this change?');});
 fireEvent.click(await screen.findByRole('button',{name:'Confirm'}));expect(await result).toBe(true);
});
it('resident link is removed from the address and does not mutate on page load',async()=>{
 history.replaceState(null,'','/resident-response#'+'a'.repeat(43));render(<><Notifications/><ResidentResponse/></>);
 expect(location.hash).toBe('');expect(api.post).not.toHaveBeenCalled();
 api.post.mockResolvedValue({data:{message:'Visit marked as exited.'}});
 fireEvent.click(screen.getByRole('button',{name:'Has left'}));fireEvent.click(await screen.findByRole('button',{name:'Confirm'}));
 await screen.findByText('Resident-reported exit saved');expect(screen.getByRole('heading',{name:'Response recorded'})).toBeInTheDocument();expect(api.post).toHaveBeenCalledWith('/resident-response',{token:'a'.repeat(43),answer:'left'});
});
it('visitor logs filters overdue visits without an inline timeline',async()=>{
 api.get.mockImplementation(path=>Promise.resolve({data:path==='/cameras'?[]:path.startsWith('/visitor-logs?')?{total:1,items:[{id:'entry',camera_name:'Entry cam',state:'ENTRY_RECORDED',flat:'B-203',resident_name:'Resident',visit_details:{visit_purpose:'Delivery'},created_at:'2026-10-29T01:00:00Z',overdue:true}]}:{timeline:[{action:'SAVE_EVENT',created_at:'2026-10-29T01:01:00Z',details:{}}]}}));
 render(<MemoryRouter initialEntries={['/visitor-logs?status=OVERDUE']}><VisitorLogs/></MemoryRouter>);
 expect(await screen.findByText('B-203 · Resident')).toBeInTheDocument();
 expect(screen.getByLabelText('Status')).toHaveValue('OVERDUE');
 expect(screen.queryByRole('button',{name:'Timeline'})).not.toBeInTheDocument();
 expect(screen.queryByRole('heading',{name:'Recorded event timeline'})).not.toBeInTheDocument();
 expect(api.get).not.toHaveBeenCalledWith('/visitor-logs/entry',expect.anything());
});
