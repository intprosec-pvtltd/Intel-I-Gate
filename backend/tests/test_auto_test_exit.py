"""Synthetic vectors verify workflow isolation, not real-world face accuracy."""
import json
from datetime import timedelta
from types import SimpleNamespace
import numpy as np
import pytest
from sqlalchemy import select,func
from app.models import Video,Event,Visit,Snapshot,ExitObservation,Audit,User,now
from app.security import protect,reveal
from app.auto_exit import observe_test
from tests.test_auto_exit import fixture_records


def records(env,duplicate=False):
    c,vector,visit_id,entry_id,source_id,camera_id=fixture_records(env,duplicate)
    c.auto_exit_enabled=False;c.auto_test_exit_enabled=True
    with env[1]() as db:
        for visit in db.scalars(select(Visit)):
            video=Video(test_role='entry',filename=visit.id+'.mp4',path='uploads/'+visit.id,size=10,duration=10);db.add(video);db.flush()
            entry=db.get(Event,visit.event_id);entry.video_id=video.id
            visit.historical=True;visit.entry_at=None
        video=Video(test_role='exit',filename='exit.mp4',path='uploads/exit',size=10,duration=10);db.add(video);db.flush()
        source=db.get(Event,source_id);source.camera_id=None;source.video_id=video.id;source.state='EXIT_REVIEW';db.commit()
        return c,vector,visit_id,entry_id,source_id,video.id


def samples(db,source_id,vector,c):
    return [observe_test(db,db.get(Event,source_id),vector,s,c) for s in (0,.6,1.2)]


def test_completion_pin_removal_and_no_real_world_exit_time(client,env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    assert client.get('/api/apartment-map').json()['visits']
    with env[1]() as db:
        assert samples(db,source_id,vector,c)==[False,False,True];db.commit()
        visit=db.get(Visit,visit_id);assert visit.status=='COMPLETED' and visit.exit_at is None and visit.entry_at is None
        assert db.get(Event,entry_id).state=='COMPLETED'
        assert db.get(Event,source_id).state=='EXIT_CONFIRMED'
        observation=db.scalar(select(ExitObservation));assert observation.visit_id==visit_id and observation.state=='AUTO_CONFIRMED'
        assert observation.video_id==video_id and observation.camera_id is None
        assert observation.evidence['video_seconds']==1.2 and 'crossed_at' not in observation.evidence
        assert not observe_test(db,db.get(Event,source_id),vector,2,c)
        db.commit();assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='AUTO_COMPLETE_TEST_EXIT'))==1
    assert client.get('/api/apartment-map').json()['visits']==[]
    assert client.get('/api/visits').json()[0]['exit_method']=='AUTO_TEST_FACE_EXIT'
    assert client.get('/api/exit-observations').json()==[]


@pytest.mark.parametrize('condition',['disabled','biometrics_off','ambiguous','wrong_face','live_visit','wrong_label','unapproved','deleted','bad_vector'])
def test_invalid_test_evidence_does_not_complete(env,condition):
    c,vector,visit_id,entry_id,source_id,video_id=records(env,duplicate=condition=='ambiguous')
    with env[1]() as db:
        photo=db.get(Snapshot,db.get(Event,entry_id).snapshot_id)
        if condition=='disabled':c.auto_test_exit_enabled=False
        if condition=='biometrics_off':c.biometric_enabled=False
        if condition=='wrong_face':vector=[0.,1.]+[0.]*126
        if condition=='live_visit':db.get(Visit,visit_id).historical=False
        if condition=='wrong_label':db.get(Video,video_id).test_role='entry'
        if condition=='unapproved':photo.approved=False
        if condition=='deleted':photo.deleted=True
        if condition=='bad_vector':vector=[float('nan')]*128
        db.flush();assert samples(db,source_id,vector,c)==[False]*3
        db.commit();assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_duplicates_async_updates_and_short_span_cannot_complete(env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    with env[1]() as db:
        event=db.get(Event,source_id)
        for seconds in (0,0,0):assert not observe_test(db,event,vector,seconds,c)
        assert not observe_test(db,event,None,.2,c)
        assert event.evidence['auto_test_exit_candidate']['hits']==1
        for seconds in (.1,.2):assert not observe_test(db,event,vector,seconds,c)
        assert db.get(Visit,visit_id).status=='ENTRY_RECORDED'


def test_retake_and_window_reset_match_count(env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    with env[1]() as db:
        event=db.get(Event,source_id)
        assert not observe_test(db,event,vector,0,c)
        assert not observe_test(db,event,vector,.6,c)
        replacement=Snapshot(path='temporary/replacement.jpg',quality=10,approved=True,embedding_encrypted=protect(json.dumps(vector),c));db.add(replacement);db.flush()
        db.get(Event,entry_id).snapshot_id=replacement.id;db.flush()
        assert not observe_test(db,event,vector,1.2,c)
        assert event.evidence['auto_test_exit_candidate']['hits']==1
        assert not observe_test(db,event,vector,20,c)
        assert event.evidence['auto_test_exit_candidate']['hits']==1


def test_worker_integrates_uploaded_matching(env):
    from app.worker import Source
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    source=Source('video:'+video_id,video_id,False,{});source.test_role='exit'
    for seconds in (0,.6,1.2):
        row={'track_id':1,'box':[0,0,100,200],'face':None,'exit_embedding':vector,'objects':[],'possible':False,'entry':False,'exit':False}
        env[2].state.worker.persist(source,[row],seconds,None,source.epoch)
    with env[1]() as db:
        assert db.get(Visit,visit_id).status=='COMPLETED'
        assert db.scalar(select(ExitObservation)).state=='AUTO_CONFIRMED'


def test_test_reference_hydration_without_live_automatic_exit(env):
    import cv2
    c,vector,visit_id,entry_id,source_id,video_id=records(env)
    with env[1]() as db:
        snapshot=db.get(Snapshot,db.get(Event,entry_id).snapshot_id);snapshot.embedding_encrypted=None;ident=snapshot.id
        ok,image=cv2.imencode('.jpg',np.full((100,80,3),120,np.uint8));assert ok
        env[2].state.storage.path(snapshot.path).write_bytes(image.tobytes());db.commit()
    worker=env[2].state.worker;worker.pipeline=SimpleNamespace(face=SimpleNamespace(single_snapshot_embedding=lambda frame:vector))
    worker.hydrate_active_embeddings()
    with env[1]() as db:assert json.loads(reveal(db.get(Snapshot,ident).embedding_encrypted,c))==vector


def test_identical_live_face_is_excluded_from_test_gallery(env):
    c,vector,visit_id,entry_id,source_id,video_id=records(env,duplicate=True)
    with env[1]() as db:
        other=db.scalar(select(Visit).where(Visit.id!=visit_id));other.historical=False;other.entry_at=now()-timedelta(minutes=1);db.flush()
        assert samples(db,source_id,vector,c)==[False,False,True];db.commit()
        assert other.status=='ENTRY_RECORDED'
