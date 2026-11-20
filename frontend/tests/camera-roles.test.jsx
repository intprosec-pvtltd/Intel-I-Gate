import React from 'react';
import {render,screen} from '@testing-library/react';
import {it,expect,vi} from 'vitest';
import Cameras from '../src/pages/Cameras';
import {WorkspaceContext} from '../src/components/ui';
vi.mock('../src/services/api',()=>({api:{get:vi.fn()},mediaUrl:p=>p,connectEvents:vi.fn()}));
vi.mock('../src/components/ui',async()=>{
 const actual=await vi.importActual('../src/components/ui');
 return {...actual,useLive:()=>true,useData:path=>({data:path==='/cameras'?[{id:'exit',name:'Exit camera',purpose:'Exit Gate',enabled:false,status:'STOPPED',zones:{}}]:{},refresh:vi.fn()})};
});
it('dedicated exit setup explains face matching and does not ask for coordinates',()=>{
 render(<WorkspaceContext.Provider value={{user:{role:'admin'}}}><Cameras manage/></WorkspaceContext.Provider>);
 expect(screen.getByText(/No crossing line is needed/)).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Zones'})).toBeNull();
 expect(screen.getByRole('button',{name:'Start Monitoring'})).toBeInTheDocument();
});
