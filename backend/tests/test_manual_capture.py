import numpy as np
from app.models import Camera, Event, Snapshot

def test_capture_frame_is_bound_to_guard_and_event_and_saves_manual_crop(client,env,monkeypatch):
    with env[1]() as db:
        camera=Camera(name='Test',location='Gate',purpose='Entry Gate',rtsp_encrypted='fixture',fingerprint='test-fingerprint')
        db.add(camera);db.flush();event=Event(camera_id=camera.id,track_ref='test-capture',evidence={});db.add(event);db.commit();event_id=event.id
    monkeypatch.setattr(env[2].state.worker,'raw_frame',lambda ident:(np.full((100,120,3),120,dtype=np.uint8),0,'epoch'))
    result=client.post(f'/api/events/{event_id}/manual-capture');assert result.status_code==200,result.text
    token=result.json()['token'];url=f'/api/events/{event_id}/manual-capture/{token}'
    assert client.get(url).status_code==200
    assert client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'}).status_code==200
    assert client.get(url).status_code==404
    assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'test-password-123'}).status_code==200
    crop={'token':token,'left':.1,'top':.1,'right':.8,'bottom':.9}
    saved=client.post(f'/api/events/{event_id}/manual-snapshot',json=crop)
    assert saved.status_code==200,saved.text
    with env[1]() as db:
        e=db.get(Event,event_id);s=db.get(Snapshot,e.snapshot_id)
        assert e.evidence['manual_snapshot'] and s.metrics['source']=='guard_live_camera' and s.embedding_encrypted is None
    assert client.get(url).status_code==404

def test_manual_capture_requires_a_live_camera(client):
    event=client.post('/api/events/manual',json={'reason':'No associated camera'}).json()['id']
    assert client.post(f'/api/events/{event}/manual-capture').status_code==409


from tests.test_resident_otp import registered,sms,approve,dest

def test_retake_keeps_resident_otp_and_visit_confirmation(client,env,registered,sms,monkeypatch):
    with env[1]() as db:
        camera=Camera(name='Retake',location='Gate',purpose='Entry Gate',rtsp_encrypted='fixture',fingerprint='retake-fixture')
        db.add(camera);db.flush();event=Event(camera_id=camera.id,track_ref='retake-proof',evidence={});db.add(event);db.commit();ident=event.id
    approve(client,ident,registered,sms)
    assert client.post(f'/api/events/{ident}/verify',json=dest(registered)).status_code==200
    monkeypatch.setattr(env[2].state.worker,'raw_frame',lambda _: (np.full((100,120,3),120,dtype=np.uint8),0,'epoch'))
    token=client.post(f'/api/events/{ident}/manual-capture').json()['token']
    response=client.post(f'/api/events/{ident}/manual-snapshot',json={'token':token,'left':0,'top':0,'right':1,'bottom':1})
    assert response.status_code==200,response.text
    assert response.json()['state']=='CONFIRMED'
    assert client.get(f'/api/events/{ident}/otp').json()['verified']
    assert client.post(f'/api/events/{ident}/save',json=dest(registered)).status_code==200
