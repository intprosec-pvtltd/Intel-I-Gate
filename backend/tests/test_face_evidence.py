from app.models import Camera,Event,Snapshot
from app.worker import Source
from app.security import protect
from sqlalchemy import select


def test_face_can_arrive_after_guard_confirmation_and_saved_snapshot_is_frozen(env):
    _,sessions,app=env
    with sessions() as db:
        c=Camera(name='Face gate',location='Lobby',purpose='Entry Gate',rtsp_encrypted=protect('rtsp://192.168.1.50/live',app.state.config),fingerprint='face-fixture');db.add(c);db.flush();ident=c.id;db.commit()
    source=Source('camera:'+ident,ident,True,{})
    row={'track_id':1,'box':[10,10,100,200],'face':None,'objects':[],'possible':False,'entry':False,'exit':False,'face_reason':'FACE_TOO_SMALL'}
    app.state.worker.persist(source,[row],1,None,source.epoch)
    with sessions() as db:
        e=db.scalar(select(Event));assert e.evidence['face_reason']=='FACE_TOO_SMALL';e.state='CONFIRMED';e.candidate_status='GUARD_CONFIRMED_DELIVERY';db.commit();event_id=e.id
    row['face']={'jpeg':b'jpeg-fixture','embedding':None,'quality':5,'metrics':{'sharpness':100}}
    app.state.worker.persist(source,[row],2,None,source.epoch)
    with sessions() as db:
        e=db.get(Event,event_id);assert e.snapshot_id is not None;assert e.candidate_status=='GUARD_CONFIRMED_DELIVERY';first=e.snapshot_id;e.state='ENTRY_RECORDED';db.get(Snapshot,first).approved=True;db.commit()
    app.state.worker.persist(source,[{**row,'face':{**row['face'],'quality':10}}],3,None,source.epoch)
    with sessions() as db:assert db.get(Event,event_id).snapshot_id==first


def test_saved_event_without_face_can_receive_first_real_snapshot(env):
    _,sessions,app=env
    with sessions() as db:
        c=Camera(name='Late gate',location='Lobby',purpose='Entry Gate',rtsp_encrypted='fixture',fingerprint='late');db.add(c);db.flush();ident=c.id;db.commit()
    source=Source('camera:'+ident,ident,True,{})
    with sessions() as db:
        e=Event(camera_id=ident,track_ref=f'{source.key}:{source.epoch}:1',state='ENTRY_RECORDED');db.add(e);db.commit();event_id=e.id
    row={'track_id':1,'box':[0,0,100,200],'face':{'jpeg':b'late-fixture','embedding':None,'quality':5,'metrics':{}},'objects':[],'possible':False,'entry':False,'exit':False}
    app.state.worker.persist(source,[row],2,None,source.epoch)
    with sessions() as db:
        e=db.get(Event,event_id);assert db.get(Snapshot,e.snapshot_id).approved
