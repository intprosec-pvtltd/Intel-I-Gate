import React from 'react';
import {MemoryRouter} from 'react-router-dom';
import {render,screen,fireEvent} from '@testing-library/react';
import {it,expect,vi} from 'vitest';
import VisitorLogs from '../src/pages/VisitorLogs';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
it('a saved visit has one row with both cameras and a Details link without timeline controls',async()=>{
 api.get.mockImplementation(path=>Promise.resolve({data:path==='/cameras'?[]:path.startsWith('/visitor-logs?')?{total:1,items:[{id:'entry',visit_id:'visit',state:'COMPLETED',flat:'B-203',resident_name:'Resident',entry_camera_name:'cam 1',exit_camera_name:'cam 2',last_activity_at:'2026-10-29T09:00:00Z',visit_details:{visitor_name:'Test Visitor',visit_purpose:'Delivery'},visit_timing:{entry_at:'2026-10-29T08:45:00Z',exit_at:'2026-10-29T09:00:00Z'}}]}:{observations:[{event_id:'entry',role:'Entry',camera_name:'cam 1',observed_at:'2026-10-29T08:45:00Z'},{event_id:'exit',role:'Exit',camera_name:'cam 2',observed_at:'2026-10-29T09:00:00Z'}],timeline:[{action:'AUTO_COMPLETE_EXIT',created_at:'2026-10-29T09:00:00Z',details:{}}]}}));
 render(<MemoryRouter><VisitorLogs/></MemoryRouter>);
 await screen.findByText('Test Visitor');expect(screen.queryByRole('option',{name:'PENDING_VERIFICATION'})).not.toBeInTheDocument();expect(screen.getByRole('option',{name:'All verified visits'})).toBeInTheDocument();expect(screen.getAllByRole('row')).toHaveLength(2);
 expect(screen.getByText('Entry: cam 1')).toBeInTheDocument();expect(screen.getByText('Exit: cam 2')).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Timeline'})).not.toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Details'})).toHaveAttribute('href','/visits/visit');
 expect(api.get.mock.calls.some(([path])=>path==='/visitor-logs/entry')).toBe(false);
 expect(screen.getAllByRole('row')).toHaveLength(2);
});
