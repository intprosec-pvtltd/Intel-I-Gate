from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.models import Visit,Event,Snapshot,Audit,User,now,Video
from app.schemas import Destination
from app import events
from .test_resident_otp import registered,sms,approve,dest
DEST={'delivery_confirmed':True,'flat':'A-101','resident_name':'Test Resident'}
def candidate(c):
    r=c.post('/api/events/manual',json={'reason':'Test fixture: guard saw arrival'});assert r.status_code==201,r.text;return r.json()['id']
def test_verify_does_not_create_visit(client,registered,sms):
    ident=candidate(client);approve(client,ident,registered,sms);data=dest(registered)
    assert client.post(f'/api/events/{ident}/verify',json=data).status_code==200
    assert client.get('/api/visits').json()==[]
    r=client.post(f'/api/events/{ident}/save',json=data);assert r.status_code==200,r.text
    assert r.json()['entry_at'] is not None
    assert client.get('/api/events/'+ident).json()['state']=='ENTRY_RECORDED'
def test_save_idempotent(client,env,registered,sms):
    ident=candidate(client);approve(client,ident,registered,sms);data=dest(registered);assert client.post(f'/api/events/{ident}/verify',json=data).status_code==200
    a=client.post(f'/api/events/{ident}/save',json=data).json();b=client.post(f'/api/events/{ident}/save',json=data).json();assert a['id']==b['id']
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Visit))==1
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='SAVE_EVENT'))==1
@pytest.mark.parametrize('patch',[{'delivery_confirmed':False},{'flat':''},{'resident_name':''}])
def test_required_fields(client,patch):
    ident=candidate(client);assert client.post(f'/api/events/{ident}/save',json={**DEST,**patch}).status_code==422
    assert client.get('/api/visits').json()==[]
@pytest.mark.parametrize('action',['reject','cancel'])
def test_terminal_candidate_cannot_save(client,action):
    ident=candidate(client);assert client.post(f'/api/events/{ident}/{action}').status_code==200
    assert client.post(f'/api/events/{ident}/save',json=DEST).status_code==409
def test_manual_exit_requires_confirmation(client,registered,sms):
    ident=candidate(client);approve(client,ident,registered,sms);data=dest(registered);client.post(f'/api/events/{ident}/verify',json=data);client.post(f'/api/events/{ident}/save',json=data)
    assert client.post(f'/api/events/{ident}/complete',json={'confirmed':False,'reason':'Test guard saw exit'}).status_code==422
    r=client.post(f'/api/events/{ident}/complete',json={'confirmed':True,'reason':'Test guard saw exit'});assert r.status_code==200,r.text
    assert r.json()['status']=='COMPLETED' and r.json()['exit_at']
def test_resident_mismatch_rejected(client):
    r=client.post('/api/residents',json={'name':'Test Resident','flat':'A-101','phone':'9876543210'}).json();ident=candidate(client)
    assert client.post(f'/api/events/{ident}/save',json={**DEST,'resident_id':r['id'],'flat':'B-202'}).status_code==409
def test_transaction_rollback(client,env):
    ident=candidate(client)
    with env[1]() as db:
        s=Snapshot(path='temporary/test.jpg',quality=1,metrics={});db.add(s);db.flush();sid=s.id;db.get(Event,ident).snapshot_id=sid;db.commit()
    with env[1]() as db:
        u=db.scalar(select(User).where(User.username=='admin'));events.save(db,ident,Destination(**DEST),u);db.rollback()
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Visit))==0
        assert not db.get(Snapshot,sid).approved
        assert db.get(Event,ident).state=='PENDING_VERIFICATION'
def test_snapshot_approval_in_save_transaction(client,env,registered,sms):
    ident=candidate(client);key=env[2].state.storage.put(b'test fixture, not an image')
    with env[1]() as db:
        s=Snapshot(path=key,quality=1,metrics={});db.add(s);db.flush();sid=s.id;db.get(Event,ident).snapshot_id=sid;db.commit()
    approve(client,ident,registered,sms);data=dest(registered);client.post(f'/api/events/{ident}/verify',json=data)
    assert client.post(f'/api/events/{ident}/save',json=data).status_code==200
    with env[1]() as db:assert db.get(Snapshot,sid).approved
    assert env[2].state.storage.path(key).exists()
def test_biometrics_opt_in(client,registered,sms):
    ident=candidate(client);approve(client,ident,registered,sms);data=dest(registered);client.post(f'/api/events/{ident}/verify',json=data);v=client.post(f'/api/events/{ident}/save',json=data).json()
    assert client.get('/api/profiles').json()==[]
    assert client.post(f'/api/visits/{v["id"]}/enroll',json={'authorized':True,'authorization':'Test authorization reference','retention_days':30}).status_code==409
def test_retention(env):
    from app.retention import cleanup
    _,sessions,app=env;key=app.state.storage.put(b'test fixture')
    with sessions() as db:
        s=Snapshot(path=key,quality=1,metrics={},created_at=now()-timedelta(days=2));db.add(s);db.commit();sid=s.id
    cleanup(sessions,app.state.storage,app.state.config)
    assert not app.state.storage.path(key).exists()
    with sessions() as db:assert db.get(Snapshot,sid) is None
def test_historical_video_not_live_occupancy(client,env,registered,sms):
    with env[1]() as db:
        v=Video(filename='test.mp4',path='uploads/test.video',duration=1,size=1);db.add(v);db.flush()
        e=Event(video_id=v.id,track_ref='test-historical',frame_seconds=.5,evidence={});db.add(e);db.commit();ident=e.id
    approve(client,ident,registered,sms);data=dest(registered);client.post(f'/api/events/{ident}/verify',json=data);assert client.post(f'/api/events/{ident}/save',json=data).status_code==200
    assert client.get('/api/dashboard/summary').json()['active_visits']==0
    assert client.post(f'/api/events/{ident}/complete',json={'confirmed':True,'reason':'Test historical departure'}).status_code==409
