import React from 'react';
import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import ResidentEnrollment from '../src/components/ResidentEnrollment';
import {api} from '../src/services/api';
vi.mock('../src/services/api',()=>({api:{post:vi.fn()}}));
it('requires a resident, photo, consent and identity confirmation before enrollment',async()=>{
 api.post.mockResolvedValue({data:{ok:true}});const saved=vi.fn();
 render(<ResidentEnrollment event={{id:'event',snapshot_id:'photo'}} residents={[{id:'resident',flat:'B-203',name:'Resident'}]} onSaved={saved}/>);
 fireEvent.click(screen.getByRole('button',{name:'Mark as resident'}));
 const submit=screen.getByRole('button',{name:'Enroll resident'});expect(submit).toBeDisabled();
 fireEvent.change(screen.getByLabelText('Resident'),{target:{value:'resident'}});
 for(const box of screen.getAllByRole('checkbox'))fireEvent.click(box);
 expect(submit).not.toBeDisabled();fireEvent.click(submit);
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/events/event/resident',{resident_id:'resident',consent:true,confirmed_identity:true}));
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
});
it('cannot enroll a missing photo',()=>{
 render(<ResidentEnrollment event={{id:'empty'}} residents={[]} onSaved={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Mark as resident'}));expect(screen.getByRole('button',{name:'Enroll resident'})).toBeDisabled();
});
