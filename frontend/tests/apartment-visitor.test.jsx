import React from 'react';
import {it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import GuardVerificationForm from '../src/components/GuardVerificationForm';
import ApartmentView from '../src/pages/ApartmentView';
import {WorkspaceContext} from '../src/components/ui';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{get:vi.fn(),post:vi.fn(),put:vi.fn()},mediaUrl:path=>'/api'+path,connectEvents:vi.fn()}));
beforeEach(()=>{vi.clearAllMocks();api.get.mockResolvedValue({data:{sms_configured:true,state:'NONE'}});});
it('requests name and reason for guest and caretaker, but not delivery',()=>{
 render(<GuardVerificationForm event={{id:'one'}} residents={[]} onSaved={()=>{}}/>);
 expect(screen.queryByLabelText('Reason for visit')).toBeNull();
 fireEvent.change(screen.getByLabelText('Visit purpose'),{target:{value:'Relation'}});
 expect(screen.getByLabelText('Guest name')).toBeRequired();expect(screen.getByLabelText('Reason for visit')).toBeRequired();
 fireEvent.change(screen.getByLabelText('Visit purpose'),{target:{value:'Maid/Caretaker'}});
 expect(screen.getByLabelText('Maid / caretaker name')).toBeRequired();expect(screen.getByLabelText('Reason for visit')).toBeRequired();
});
it('shows active visitor details on their destination pin',async()=>{
 api.get.mockResolvedValue({data:{points:[],flats:['B-203'],visits:[{id:'v1',flat:'B-203',resident_name:'Resident',visitor_name:'Visitor One',visit_reason:'Family visit',purpose:'Relation',snapshot_id:null}],truncated:false}});
 render(<WorkspaceContext.Provider value={{user:{role:'guard'},timezone:'Asia/Kolkata'}}><ApartmentView/></WorkspaceContext.Provider>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'B-203, active visitor'})).toBeInTheDocument());
 expect(screen.getByText('Visitor: Visitor One')).toBeInTheDocument();expect(screen.getByText('Reason: Family visit')).toBeInTheDocument();
 expect(screen.getByText(/do not show actual or live visitor locations/i)).toBeInTheDocument();
});
