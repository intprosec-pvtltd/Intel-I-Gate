from sqlalchemy import select
from app.models import Camera,Event,Visit,ExitObservation,User

def test_observation_linked_to_another_visit_is_not_reassigned(client,env):
    with env[1]() as db:
        guard=db.scalar(select(User).where(User.username=='admin'))
        cam=Camera(name='Exit',location='Gate',purpose='Exit Gate',rtsp_encrypted='fixture',fingerprint='fixture-exit')
        db.add(cam);db.flush()
        a=Event(track_ref='event-a',camera_id=cam.id,evidence={});b=Event(track_ref='event-b',camera_id=cam.id,evidence={})
        db.add_all([a,b]);db.flush()
        v1=Visit(event_id=a.id,guard_id=guard.id,resident_name='Resident A',flat='A-1',notes='',company='')
        v2=Visit(event_id=b.id,guard_id=guard.id,resident_name='Resident B',flat='B-2',notes='',company='')
        db.add_all([v1,v2]);db.flush()
        x=ExitObservation(camera_id=cam.id,track_ref='exit-track',visit_id=v1.id,evidence={})
        db.add(x);db.commit();event_id=b.id;obs_id=x.id
    response=client.post(f'/api/events/{event_id}/complete',json={'confirmed':True,'reason':'Guard checked exit','observation_id':obs_id})
    assert response.status_code==409
    with env[1]() as db:
        assert db.get(ExitObservation,obs_id).state=='NEEDS_REVIEW'
        assert db.scalar(select(Visit).where(Visit.event_id==event_id)).status=='ENTRY_RECORDED'
