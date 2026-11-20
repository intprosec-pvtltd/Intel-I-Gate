from datetime import timedelta
from sqlalchemy import select
from app.models import Video,Job,Event,Visit,Snapshot,User,Audit,now
from app.retention import cleanup
from app import events
from app.schemas import Destination


def video_fixture(env,status='UPLOADED',with_visit=False):
    _,sessions,app=env
    key=app.state.storage.put(b'test-video','uploads','.video')
    with sessions() as db:
        v=Video(filename='test.mp4',path=key,size=10,duration=1,status=status)
        db.add(v);db.flush();ident=v.id
        if status!='UPLOADED':db.add(Job(video_id=ident,status=status))
        snapshot_id=visit_id=None
        if with_visit:
            snap=Snapshot(path=app.state.storage.put(b'face'),quality=1,metrics={})
            db.add(snap);db.flush();snapshot_id=snap.id
            e=Event(video_id=ident,track_ref='delete-test-track',snapshot_id=snapshot_id)
            db.add(e);db.flush();u=db.scalar(select(User).where(User.username=='admin'))
            visit=events.save(db,e.id,Destination(delivery_confirmed=True,flat='A-101',resident_name='Resident'),u)
            visit_id=visit.id
        db.commit()
    return ident,key,snapshot_id,visit_id


def test_delete_upload_removes_file_and_hides_item(client,env):
    ident,key,_,_=video_fixture(env)
    r=client.delete(f'/api/videos/{ident}');assert r.status_code==200 and r.json()['file_removed']
    assert not env[2].state.storage.path(key).exists()
    assert ident not in [v['id'] for v in client.get('/api/videos').json()]
    for suffix in ('status','results','preview'):
        assert client.get(f'/api/videos/{ident}/{suffix}').status_code==404
    assert client.post(f'/api/videos/{ident}/analyze',json={'test_role':'entry'}).status_code==404
    assert client.delete(f'/api/videos/{ident}').status_code==200
    with env[1]() as db:
        assert len(list(db.scalars(select(Audit).where(Audit.action=='DELETE_VIDEO'))))==1


def test_delete_completed_video_preserves_visit_and_face(client,env):
    ident,key,snapshot,visit=video_fixture(env,'COMPLETED',True)
    env[2].state.worker.video_previews[ident]=(b'jpeg',0,'sequence',0)
    assert client.delete(f'/api/videos/{ident}').status_code==200
    assert ident not in env[2].state.worker.video_previews
    with env[1]() as db:
        assert db.get(Visit,visit) is not None
        assert db.get(Snapshot,snapshot).deleted is False
        assert db.get(Job,db.scalar(select(Job.id).where(Job.video_id==ident))).status=='DELETED'
    assert client.get(f'/api/snapshots/{snapshot}').status_code==200
    assert client.get('/api/visits').json()[0]['id']==visit


def test_running_video_requires_cancel(client,env):
    ident,key,_,_=video_fixture(env,'RUNNING')
    assert client.delete(f'/api/videos/{ident}').status_code==409
    assert env[2].state.storage.path(key).exists()


def test_delete_requires_login(env):
    assert env[0].delete('/api/videos/missing').status_code==401


def test_cleanup_retries_pending_file_and_never_resurrects_deleted_video(client,env,monkeypatch):
    ident,key,_,_=video_fixture(env)
    storage=env[2].state.storage;remove=storage.remove
    monkeypatch.setattr(storage,'remove',lambda _:(_ for _ in ()).throw(OSError('locked file')))
    response=client.delete(f'/api/videos/{ident}')
    assert response.status_code==200 and not response.json()['file_removed']
    assert storage.path(key).exists()
    monkeypatch.setattr(storage,'remove',remove)
    with env[1]() as db:db.get(Video,ident).created_at=now()-timedelta(days=100);db.commit()
    cleanup(env[1],storage,env[2].state.config)
    assert not storage.path(key).exists()
    with env[1]() as db:assert db.get(Video,ident).status=='DELETED'
    assert client.get('/api/videos').json()==[]
