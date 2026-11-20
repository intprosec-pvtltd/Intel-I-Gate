import pytest
from sqlalchemy import select
from app.models import Video,Event,Snapshot,User,Visit,Camera,ExitObservation
from app.worker import Source
from .test_resident_otp import sms,registered,approve,dest


def add_video(env,role):
    with env[1]() as db:
        video=Video(filename=f'{role}.mp4',path=f'uploads/{role}.video',size=10,duration=10,test_role=role)
        db.add(video);db.commit();return video.id


def persist_person(env,video_id,role):
    source=Source('video:'+video_id,video_id,False,{})
    source.test_role=role
    import cv2,numpy as np
    image=np.full((100,80,3),120,dtype=np.uint8);ok,jpeg=cv2.imencode('.jpg',image);assert ok
    row={'track_id':1,'box':[10,10,100,200],'face':{'jpeg':jpeg.tobytes(),'quality':10,'metrics':{'framing':'test_fixture'},'embedding':None},'face_reason':'FACE_NOT_DETECTED','objects':[],'possible':False,'entry':False,'exit':False}
    env[2].state.worker.persist(source,[row],2.0,None,source.epoch)
    with env[1]() as db:return db.scalar(select(Event).where(Event.video_id==video_id)).id


def test_uploaded_entry_exit_flow_is_separate_from_live_occupancy(client,env,registered,sms):
    entry_id=add_video(env,'entry');event=persist_person(env,entry_id,'entry')
    assert client.get('/api/apartment-map').json()['visits']==[]
    approve(client,event,registered,sms)
    assert client.post(f'/api/events/{event}/verify',json=dest(registered)).status_code==200
    saved=client.post(f'/api/events/{event}/save',json=dest(registered));assert saved.status_code==200,saved.text
    pin=client.get('/api/apartment-map').json()['visits'][0]
    assert pin['snapshot_id'] and client.get('/api/snapshots/'+pin['snapshot_id']).status_code==200
    assert pin['test_mode'] is True and pin['video_seconds']==2.0 and pin['flat']==registered['flat']
    assert client.get('/api/dashboard/summary').json()['active_visits']==0
    exit_id=add_video(env,'exit');exit_event=persist_person(env,exit_id,'exit')
    assert client.get(f'/api/events/{exit_event}').json()['state']=='EXIT_REVIEW'
    assert client.post(f'/api/events/{exit_event}/verify',json=dest(registered)).status_code==409
    assert not any(e['id']==exit_event for e in client.get('/api/events/pending').json())
    observations=client.get('/api/exit-observations').json()
    assert len(observations)==1 and observations[0]['test_mode'] and observations[0]['camera_id'] is None
    assert client.post(f'/api/events/{event}/complete',json={'confirmed':True,'reason':'Compared entry and exit photos'}).status_code==422
    done=client.post(f'/api/events/{event}/complete',json={'confirmed':True,'reason':'Guard compared test evidence','observation_id':observations[0]['id']})
    assert done.status_code==200,done.text
    assert done.json()['status']=='COMPLETED' and done.json()['exit_at'] is None and done.json()['historical']
    assert client.get('/api/apartment-map').json()['visits']==[]
    assert client.get('/api/exit-observations').json()==[]
    assert client.get('/api/dashboard/summary').json()['completed']==0


def test_live_and_test_observations_cannot_be_mixed(client,env,registered,sms):
    video_id=add_video(env,'entry');event=persist_person(env,video_id,'entry');approve(client,event,registered,sms)
    assert client.post(f'/api/events/{event}/verify',json=dest(registered)).status_code==200
    assert client.post(f'/api/events/{event}/save',json=dest(registered)).status_code==200
    with env[1]() as db:
        camera=Camera(name='Exit',location='Gate',purpose='Exit Gate',rtsp_encrypted='fixture',fingerprint='test-mixing');db.add(camera);db.flush()
        observation=ExitObservation(camera_id=camera.id,track_ref='live-mixing',evidence={});db.add(observation);db.commit();ident=observation.id
    response=client.post(f'/api/events/{event}/complete',json={'confirmed':True,'reason':'Must not mix test and live','observation_id':ident})
    assert response.status_code==409


def test_analysis_requires_a_label_and_cannot_relabel_a_recording(client,env,monkeypatch):
    video_id=add_video(env,'entry');env[2].state.storage.path('uploads/entry.video').write_bytes(b'fixture');env[2].state.config.ai_enabled=True
    monkeypatch.setattr(env[2].state.worker,'add',lambda *args:None)
    assert client.post(f'/api/videos/{video_id}/analyze').status_code==422
    assert client.post(f'/api/videos/{video_id}/analyze',json={'test_role':'other'}).status_code==422
    assert client.post(f'/api/videos/{video_id}/analyze',json={'test_role':'exit'}).status_code==409
    assert client.post(f'/api/videos/{video_id}/analyze',json={'test_role':'entry'}).status_code==200
