import React from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen} from '@testing-library/react';
import {MemoryRouter,Routes,Route} from 'react-router-dom';
import EventTimeline from '../src/components/EventTimeline';
import VisitDetails from '../src/pages/VisitDetails';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn()},mediaUrl:p=>p}));
it('shows actual timeline actions, preserves entries on refresh and marks awaiting exit separately',()=>{
 const items=[{action:'DETECTED',created_at:'2026-10-30T06:00:00Z',details:{source:'Entry'}}];
 const {rerender}=render(<EventTimeline items={items} active/>);
 expect(screen.getAllByRole('listitem')).toHaveLength(2);expect(screen.getByText('Awaiting exit')).toBeInTheDocument();
 rerender(<EventTimeline items={[...items,{action:'AUTO_COMPLETE_EXIT',created_at:'2026-10-30T06:10:00Z'}]} active={false}/>);
 expect(screen.queryByText('Awaiting exit')).not.toBeInTheDocument();expect(screen.getByText('Exit automatically confirmed')).toBeInTheDocument();
});
it('saved visit has a dedicated read-only detail route with a timeline',async()=>{
 api.get.mockResolvedValue({data:{id:'visit',flat:'A-1',resident_name:'Resident',status:'COMPLETED',event:{verification:{visitor_name:'Test visitor',visit_purpose:'Delivery'},visit_timing:{status:'COMPLETED',flat:'A-1'}},observations:[],timeline:[{action:'SAVE_EVENT',created_at:'2026-10-30T06:00:00Z'}]}});
 render(<MemoryRouter initialEntries={['/visits/visit']}><Routes><Route path="/visits/:id" element={<VisitDetails/>}/></Routes></MemoryRouter>);
 await screen.findByText('Test visitor');expect(screen.getByText('Entry saved')).toBeInTheDocument();expect(api.get).toHaveBeenCalledWith('/visits/visit',expect.anything());expect(screen.queryByRole('button',{name:'Confirm Visit'})).not.toBeInTheDocument();
});
