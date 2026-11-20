from datetime import timedelta
import json
import numpy as np
import pytest
from sqlalchemy import select,func
from app.models import User,Camera,Event,Visit,Snapshot,ExitObservation,Audit,now
from app.security import protect
from app.auto_exit import observe


def fixture_records(env,duplicate=False):
    c=env[2].state.config;c.biometric_enabled=True;c.auto_exit_enabled=True;c.auto_exit_fast_enabled=False
    vector=[1.0]+[0.0]*127
    with env[1]() as db:
        guard=db.scalar(select(User).where(User.username=='admin'))
        camera=Camera(name='Exit',location='Exit gate',purpose='Entry and Exit',enabled=True,zones={'exit':[.1,.5,.9,.5]},rtsp_encrypted='fixture',fingerprint='auto-exit-camera')
        db.add(camera);db.flush()
        def entry(index):
            snapshot=Snapshot(path=f'temporary/entry-{index}.jpg',quality=10,approved=True,embedding_encrypted=protect(json.dumps(vector),c),created_at=now()-timedelta(seconds=60));db.add(snapshot);db.flush()
            event=Event(track_ref=f'entry-{index}',state='ENTRY_RECORDED',snapshot_id=snapshot.id,evidence={});db.add(event);db.flush()
            visit=Visit(event_id=event.id,guard_id=guard.id,resident_name='Resident',flat='B-203',entry_at=now()-timedelta(seconds=60),historical=False);db.add(visit);db.flush();return visit.id,event.id
        visit_id,entry_id=entry(1)
        if duplicate:entry(2)
        source=Event(camera_id=camera.id,track_ref='camera:exit:epoch:1',evidence={});db.add(source);db.commit()
        return c,vector,visit_id,entry_id,source.id,camera.id


def sample(db,event_id,vector,c,index,crossed=False):
    event=db.get(Event,event_id)
    return observe(db,event,vector,1+index*.6,now()-timedelta(seconds=2-index*.6),c,crossed=crossed)


def test_repeated_unique_face_plus_crossing_automatically_completes_once(client,env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        assert not sample(db,source_id,vector,c,0)
        assert not sample(db,source_id,vector,c,1,True)
        assert sample(db,source_id,vector,c,2)
        db.commit()
        visit=db.get(Visit,visit_id)
        assert visit.status=='COMPLETED' and visit.exit_at is not None
        assert db.get(Event,entry_id).state=='COMPLETED'
        assert db.get(Event,source_id).state=='EXIT_CONFIRMED'
        assert db.scalar(select(ExitObservation)).state=='AUTO_CONFIRMED'
        assert not sample(db,source_id,vector,c,3)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='AUTO_COMPLETE_EXIT'))==1
    saved=client.get('/api/visits').json()[0]
    assert saved['exit_method']=='AUTO_FACE_EXIT'
    assert client.get('/api/apartment-map').json()['visits']==[]


@pytest.mark.parametrize('condition',['disabled','wrong_purpose','no_line','stopped','ambiguous','low_score','young_entry','deleted_snapshot','historical','stale_frame','no_crossing'])
def test_unsafe_or_incomplete_matches_never_complete(env,condition):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env,duplicate=condition=='ambiguous')
    with env[1]() as db:
        camera=db.get(Camera,camera_id);visit=db.get(Visit,visit_id)
        if condition=='disabled':c.auto_exit_enabled=False
        if condition=='wrong_purpose':camera.purpose='Entry Gate'
        if condition=='no_line':camera.zones={}
        if condition=='stopped':camera.enabled=False
        if condition=='low_score':vector=[0.,1.]+[0.]*126
        if condition=='young_entry':visit.entry_at=now()
        if condition=='deleted_snapshot':db.get(Snapshot,db.get(Event,entry_id).snapshot_id).deleted=True
        if condition=='historical':visit.historical=True
        for index in range(3):
            if condition=='stale_frame':result=observe(db,db.get(Event,source_id),vector,index,now()-timedelta(seconds=30),c,crossed=True)
            else:result=sample(db,source_id,vector,c,index,crossed=condition!='no_crossing')
            assert not result
        db.commit();assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_duplicate_sample_and_one_frame_cannot_supply_three_confirmations(env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        for _ in range(5):assert not sample(db,source_id,vector,c,0,True)
        db.commit();assert db.get(Event,source_id).evidence['auto_exit_candidate']['hits']==1
        assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_snapshot_retake_resets_accumulated_confirmation_samples(env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        assert not sample(db,source_id,vector,c,0,True)
        assert not sample(db,source_id,vector,c,1)
        new=Snapshot(path='temporary/replacement.jpg',quality=10,approved=True,embedding_encrypted=protect(json.dumps(vector),c));db.add(new);db.flush()
        db.get(Event,entry_id).snapshot_id=new.id;db.flush()
        assert not sample(db,source_id,vector,c,2)
        db.commit();assert db.get(Event,source_id).evidence['auto_exit_candidate']['hits']==1
        assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_invalid_face_vectors_fail_closed(env):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        for vector in ([float('nan')]*128,[0.]*128,[1.,2.],[[1.]*128]):
            assert not sample(db,source_id,vector,c,0,True)
        assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_worker_passes_every_face_sample_to_automatic_exit(env):
    from app.worker import Source
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    source=Source('camera:'+camera_id,camera_id,True,{'exit':[.1,.5,.9,.5]})
    for index in range(3):
        row={'track_id':1,'box':[0,0,100,200],'face':None,'exit_embedding':vector,'objects':[],'possible':False,'entry':False,'exit':index==1}
        env[2].state.worker.persist(source,[row],1+index*.6,now()-timedelta(seconds=2-index*.6),source.epoch)
    with env[1]() as db:
        assert db.get(Visit,visit_id).status=='COMPLETED'
        assert db.scalar(select(ExitObservation)).state=='AUTO_CONFIRMED'


def test_saved_manual_photo_receives_a_reference_embedding_on_inference_thread(env):
    import cv2
    from types import SimpleNamespace
    from app.security import reveal
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env)
    with env[1]() as db:
        snapshot=db.get(Snapshot,db.get(Event,entry_id).snapshot_id);snapshot.embedding_encrypted=None
        ok,jpeg=cv2.imencode('.jpg',np.full((100,80,3),120,dtype=np.uint8));assert ok
        env[2].state.storage.path(snapshot.path).write_bytes(jpeg.tobytes());ident=snapshot.id;db.commit()
    worker=env[2].state.worker;worker.pipeline=SimpleNamespace(face=SimpleNamespace(single_snapshot_embedding=lambda frame:vector))
    worker.hydrate_active_embeddings()
    with env[1]() as db:assert json.loads(reveal(db.get(Snapshot,ident).embedding_encrypted,c))==vector


def test_equal_quality_frames_still_produce_distinct_exit_embeddings(env,monkeypatch):
    import sys,types
    from types import SimpleNamespace
    from app.vision import Pipeline
    modules={name:types.ModuleType(name) for name in ['ultralytics','ultralytics.trackers','ultralytics.trackers.basetrack']}
    modules['ultralytics.trackers.basetrack'].BaseTrack=type('BaseTrack',(),{'_count':0})
    for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
    p=Pipeline.__new__(Pipeline);p.c=env[2].state.config
    p.sources={'key':{'tracker':SimpleNamespace(update=lambda *_:np.array([[0,0,100,200,1,.9]])),'counter':0,'tracks':{},'dino_at':1000}}
    p.yolo=SimpleNamespace(predict=lambda *a,**k:[SimpleNamespace(boxes=SimpleNamespace(cpu=lambda:SimpleNamespace(numpy=lambda:None)))])
    vector=[1.]+[0.]*127
    p.face=SimpleNamespace(candidates=lambda *_:{1:{'quality':10,'embedding':vector}},reasons={1:'CAPTURED'})
    p.timed=lambda name,fn:fn()
    a=p.process('key',np.zeros((540,960,3),np.uint8),0,{})[0]
    b=p.process('key',np.zeros((540,960,3),np.uint8),.6,{})[0]
    assert a['face'] and b['face'] is None
    assert a['exit_embedding']==b['exit_embedding']==vector
    assert p.sources['key']['tracks'][1]['row']['exit_embedding'] is None
