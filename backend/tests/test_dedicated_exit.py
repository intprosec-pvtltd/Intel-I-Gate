from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.models import Camera,Visit,Event,ExitObservation,Audit,now
from app.auto_exit import observe
from tests.test_auto_exit import fixture_records,sample


def dedicated(env):
    result=fixture_records(env)
    with env[1]() as db:
        camera=db.get(Camera,result[-1]);camera.purpose='Exit Gate';camera.zones={};db.commit()
    return result


def test_dedicated_exit_completes_without_any_line_or_crossing(client,env):
    c,vector,visit_id,entry_id,source_id,camera_id=dedicated(env)
    with env[1]() as db:
        assert not sample(db,source_id,vector,c,0)
        assert not sample(db,source_id,vector,c,1)
        assert sample(db,source_id,vector,c,2);db.commit()
        visit=db.get(Visit,visit_id);assert visit.status=='COMPLETED' and visit.exit_at
        details=db.get(Event,entry_id).evidence['exit_completion']
        assert details['exit_time_basis']=='FACE_RECOGNITION' and 'crossed_at' not in details
        assert db.get(Event,source_id).state=='EXIT_CONFIRMED'
        assert db.scalar(select(ExitObservation)).state=='AUTO_CONFIRMED'
        assert not sample(db,source_id,vector,c,3);db.commit()
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='AUTO_COMPLETE_EXIT'))==1
    assert client.get('/api/apartment-map').json()['visits']==[]
    assert client.get('/api/events/'+source_id).json()['visit_timing']['exit_at']


@pytest.mark.parametrize('condition',['entry_camera','stopped','wrong_face','historical','too_young','disabled','stale','duplicate_samples'])
def test_dedicated_exit_keeps_invalid_matches_active(env,condition):
    c,vector,visit_id,entry_id,source_id,camera_id=dedicated(env)
    with env[1]() as db:
        camera=db.get(Camera,camera_id)
        if condition=='entry_camera':camera.purpose='Entry Gate'
        if condition=='stopped':camera.enabled=False
        if condition=='wrong_face':vector=[0.,1.]+[0.]*126
        if condition=='historical':db.get(Visit,visit_id).historical=True
        if condition=='too_young':db.get(Visit,visit_id).entry_at=now()
        if condition=='disabled':c.auto_exit_enabled=False
        for i in range(3):
            if condition=='stale':result=observe(db,db.get(Event,source_id),vector,i,now()-timedelta(seconds=30),c)
            else:result=sample(db,source_id,vector,c,0 if condition=='duplicate_samples' else i)
            assert not result
        db.commit();assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_dedicated_exit_rejects_ambiguous_active_faces(env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env,duplicate=True)
    with env[1]() as db:
        camera=db.get(Camera,camera_id);camera.purpose='Exit Gate';camera.zones={};db.flush()
        assert not any(sample(db,source_id,vector,c,i) for i in range(3))


def test_worker_routes_dedicated_exit_without_crossing(env):
    from app.worker import Source
    c,vector,visit_id,entry_id,source_id,camera_id=dedicated(env)
    source=Source('camera:'+camera_id,camera_id,True,{})
    for i in range(3):
        row={'track_id':1,'box':[0,0,100,200],'face':None,'exit_embedding':vector,'objects':[],'possible':False,'entry':False,'exit':False}
        env[2].state.worker.persist(source,[row],i*.6,now()-timedelta(seconds=2-i*.6),source.epoch)
    with env[1]() as db:
        assert db.get(Visit,visit_id).status=='COMPLETED'
        observation=db.scalar(select(ExitObservation));assert observation and observation.state=='AUTO_CONFIRMED'
