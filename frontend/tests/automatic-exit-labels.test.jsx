import React from 'react';
import {MemoryRouter} from 'react-router-dom';
import {it,expect,vi} from 'vitest';
import {render,screen} from '@testing-library/react';
import {EventCard} from '../src/components/ui';
vi.mock('../src/services/api',()=>({api:{get:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
it('shows exit awaiting review instead of possible delivery on an exit observation',()=>{
 render(<MemoryRouter><EventCard event={{id:'exit',state:'EXIT_REVIEW',test_role:'exit',candidate_status:'POSSIBLE_DELIVERY',camera_name:'Exit camera',evidence:{}}}/></MemoryRouter>);
 expect(screen.getByText('EXIT AWAITING REVIEW')).toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Review exit →'})).toHaveAttribute('href','/history');
 expect(screen.queryByText('POSSIBLE DELIVERY')).toBeNull();
});
it('shows the completed exit state after an automatic match',()=>{
 render(<MemoryRouter><EventCard event={{id:'exit',state:'EXIT_CONFIRMED',candidate_status:'POSSIBLE_DELIVERY',camera_name:'Exit camera',evidence:{}}}/></MemoryRouter>);
 expect(screen.getByText('EXIT CONFIRMED')).toBeInTheDocument();
});
