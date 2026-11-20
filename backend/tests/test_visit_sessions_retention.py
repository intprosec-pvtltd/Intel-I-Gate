from datetime import datetime,timedelta,timezone
import secrets
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from pydantic import SecretStr
from app.models import Visit,Event,Resident,VisitAlert,Snapshot,Audit,User,FileDeletion,ExitObservation,now
from app.security import protect,reveal
from app.visit_sessions import tick,response,utc
from app.retention import cleanup
from tests.test_resident_otp import sms,registered,candidate,approve,dest


def fixture_visit(env,historical=False):
 c=env[2].state.config;c.public_app_url='https://gate.example.test';c.sms_provider='twilio';c.twilio_account_sid='AC'+'1'*32;c.twilio_auth_token=SecretStr('secret');c.twilio_from_number='+12025550100'
 with env[1]() as db:
  guard=db.scalar(select(User).where(User.username=='admin'))
  r=Resident(name='Resident',flat='B-203',phone_encrypted=protect('+919876543210',c));db.add(r)
  s=Snapshot(path=env[2].state.storage.put(b'image'),quality=10,approved=True,created_at=now()-timedelta(days=60));db.add(s);db.flush()
  e=Event(track_ref=secrets.token_hex(10),state='ENTRY_RECORDED',snapshot_id=s.id,verification={'visit_purpose':'Delivery'});db.add(e);db.flush()
  v=Visit(event_id=e.id,resident_id=r.id,guard_id=guard.id,resident_name=r.name,flat=r.flat,entry_at=None if historical else now()-timedelta(minutes=20),historical=historical,expected_exit_at=now()-timedelta(minutes=5));db.add(v);db.commit();return c,v.id,e.id,r.id,s.id


def sent(env,historical=False):
 values=fixture_visit(env,historical);messages=[];tick(env[1],values[0],lambda c,p,m:messages.append(m))
 with env[1]() as db:
  a=db.scalar(select(VisitAlert));token=reveal(a.token_encrypted,values[0]) if a.token_encrypted else None
 return values,messages,token


def test_unique_alert_and_single_sms(env,client):
 (c,vid,eid,rid,sid),messages,token=sent(env);tick(env[1],c,lambda *args:messages.append('duplicate'))
 assert len(messages)==1 and '/resident-response#'+token in messages[0]
 with env[1]() as db:
  a=db.scalar(select(VisitAlert));assert a.sms_state=='SUBMITTED' and a.attempts==1
 assert len(client.get('/api/visit-alerts').json())==1
 assert client.get('/api/visitor-logs?status=OVERDUE').json()['total']==1


@pytest.mark.parametrize('answer',['left','present'])
def test_resident_reply_single_use_updates_logs(env,client,answer):
 (c,vid,eid,rid,sid),messages,token=sent(env);client.cookies.clear()
 r=client.post('/api/resident-response',json={'token':token,'answer':answer});assert r.status_code==200,r.text
 assert client.post('/api/resident-response',json={'token':token,'answer':answer}).status_code==410
 with env[1]() as db:
  v=db.get(Visit,vid);a=db.scalar(select(VisitAlert));assert a.response==answer and a.token_digest is None and a.token_encrypted is None
  if answer=='left':
   assert v.status=='COMPLETED' and v.exit_at and v.completed_at and a.state=='RESOLVED'
   assert db.get(Event,eid).evidence['exit_completion']['method']=='RESIDENT_CONFIRMED'
  else:assert v.status=='ENTRY_RECORDED' and a.state=='OPEN'


@pytest.mark.parametrize('reason',['expired','changed_phone','completed','test_mode'])
def test_invalid_response_rejected(env,reason):
 (c,vid,eid,rid,sid),messages,token=sent(env)
 with env[1]() as db:
  a=db.scalar(select(VisitAlert))
  if reason=='expired':a.expires_at=now()-timedelta(seconds=1)
  if reason=='changed_phone':db.get(Resident,rid).revision+=1
  if reason=='completed':db.get(Visit,vid).status='COMPLETED'
  if reason=='test_mode':db.get(Visit,vid).historical=True
  db.commit()
  with pytest.raises(HTTPException) as exc:response(db,token,'left',c)
  assert exc.value.status_code==410


def test_uploaded_overdue_never_sends_sms(env):
 (c,*_),messages,token=sent(env,True);assert messages==[] and token is None
 with env[1]() as db:assert db.scalar(select(VisitAlert)).sms_state=='TEST_ONLY'


def test_uncertain_network_submission_not_repeated(env):
 c,*_=fixture_visit(env);calls=[]
 def fail(*args):calls.append(1);raise TimeoutError()
 tick(env[1],c,fail);tick(env[1],c,fail);assert calls==[1]
 with env[1]() as db:assert db.scalar(select(VisitAlert)).sms_state=='UNKNOWN'


def test_explicit_rejection_retries_with_limit(env):
 c,*_=fixture_visit(env);calls=[]
 def fail(*args):calls.append(1);raise HTTPException(502,'SMS provider did not accept the message')
 for _ in range(5):
  tick(env[1],c,fail)
  with env[1]() as db:
   a=db.scalar(select(VisitAlert));a.next_attempt_at=now()-timedelta(minutes=1);db.commit()
 assert len(calls)==3
 with env[1]() as db:assert db.scalar(select(VisitAlert)).sms_state=='FAILED'


def test_unconfigured_public_url_keeps_dashboard_alert(env):
 c,*_=fixture_visit(env);c.public_app_url='';calls=[];tick(env[1],c,lambda *args:calls.append(1));assert calls==[]
 with env[1]() as db:assert db.scalar(select(VisitAlert)).state=='OPEN'


def test_delivery_deadline_from_save(client,env,registered,sms):
 e=candidate(client);approve(client,e,registered,sms);data=dest(registered)
 assert client.post('/api/events/'+e+'/verify',json=data).status_code==200
 before=now();r=client.post('/api/events/'+e+'/save',json=data);assert r.status_code==200
 assert 899<(utc(datetime.fromisoformat(r.json()['expected_exit_at']))-before).total_seconds()<902


def test_guest_requires_future_aware_deadline(client,registered,sms):
 e=candidate(client);approve(client,e,registered,sms);p={**dest(registered),'visit_purpose':'Relation','visitor_name':'Guest','visit_reason':'Visit'}
 assert client.post('/api/events/'+e+'/verify',json=p).status_code==422
 for time in [(now()-timedelta(minutes=1)).isoformat(),(now()+timedelta(hours=2)).replace(tzinfo=None).isoformat()]:
  p['expected_exit_at']=time;assert client.post('/api/events/'+e+'/verify',json=p).status_code==422


def test_daily_cleanup_protects_active_face_and_current_day(env,monkeypatch):
 c,vid,eid,rid,sid=fixture_visit(env);moment=datetime(2026,11,1,0,0,5,tzinfo=timezone(timedelta(hours=5,minutes=30)));monkeypatch.setattr('app.retention.now',lambda:moment)
 with env[1]() as db:
  old=Event(track_ref='old',created_at=moment-timedelta(days=1));current=Event(track_ref='today',created_at=moment);db.add_all([old,current]);db.commit();oldid=old.id;newid=current.id
 cleanup(env[1],env[2].state.storage,c)
 with env[1]() as db:
  assert db.get(Event,oldid) is None and db.get(Event,newid)
  assert db.get(Event,eid) and db.get(Snapshot,sid) and not db.get(Snapshot,sid).deleted


def test_monthly_cleanup_completed_graph(env,monkeypatch):
 c,vid,eid,rid,sid=fixture_visit(env);moment=datetime(2026,11,1,0,0,5,tzinfo=timezone(timedelta(hours=5,minutes=30)))
 with env[1]() as db:
  v=db.get(Visit,vid);v.status='COMPLETED';v.completed_at=v.exit_at=moment-timedelta(days=1);db.get(Event,eid).state='COMPLETED';db.add(Audit(event_id=eid,action='FIXTURE',details={}))
  db.add(ExitObservation(track_ref='exit-track',visit_id=vid,evidence={}));db.add(Event(track_ref='exit-track',state='EXIT_CONFIRMED',created_at=moment-timedelta(days=1)));path=db.get(Snapshot,sid).path;db.commit()
 monkeypatch.setattr('app.retention.now',lambda:moment);cleanup(env[1],env[2].state.storage,c)
 with env[1]() as db:
  assert db.get(Visit,vid) is None and db.get(Event,eid) is None and db.get(Snapshot,sid) is None
  assert db.scalar(select(func.count()).select_from(ExitObservation))==0
  assert db.get(Resident,rid) and db.scalar(select(func.count()).select_from(User))==2
 assert not env[2].state.storage.path(path).exists()


def test_locked_file_retries(env,monkeypatch):
 c=env[2].state.config;storage=env[2].state.storage;path=storage.put(b'orphan')
 with env[1]() as db:db.add(Snapshot(path=path,quality=1,created_at=now()-timedelta(days=2)));db.commit()
 original=storage.remove
 def fail(key):raise PermissionError()
 monkeypatch.setattr(storage,'remove',fail);cleanup(env[1],storage,c)
 with env[1]() as db:assert db.scalar(select(FileDeletion))
 monkeypatch.setattr(storage,'remove',original);cleanup(env[1],storage,c);assert not storage.path(path).exists()
 with env[1]() as db:assert db.scalar(select(FileDeletion)) is None


def test_one_pass_strong_match_resolves_alert(env):
 from tests.test_dedicated_exit import dedicated
 from tests.test_auto_exit import sample
 c,vector,vid,eid,sourceid,cameraid=dedicated(env);c.auto_exit_fast_enabled=True
 with env[1]() as db:
  db.add(VisitAlert(visit_id=vid));db.commit();assert sample(db,sourceid,vector,c,0);db.commit()
  assert db.get(Event,eid).evidence['exit_completion']['fast_match']
  assert db.scalar(select(VisitAlert)).state=='RESOLVED'


def test_logs_authorization_filter_and_pagination(env,client):
 c,vid,eid,rid,sid=fixture_visit(env)
 assert client.get('/api/visitor-logs?q=B-203').json()['total']==1
 assert client.get('/api/visitor-logs?source=test').json()['total']==0
 assert client.get('/api/visitor-logs?offset=50').json()['items']==[]
 assert any(x['action']=='DETECTED' for x in client.get('/api/visitor-logs/'+eid).json()['timeline'])
 client.cookies.clear();assert client.get('/api/visitor-logs').status_code==401


def test_unverified_shared_snapshot_survives_daily_cleanup(env,monkeypatch):
 c,vid,eid,rid,sid=fixture_visit(env)
 with env[1]() as db:
  db.add(Event(track_ref='unused-pending',snapshot_id=sid,created_at=now()-timedelta(days=2)));db.commit()
 cleanup(env[1],env[2].state.storage,c)
 with env[1]() as db:assert db.get(Snapshot,sid) and db.get(Event,eid)


def test_active_old_reference_remains_matchable(env):
 from tests.test_dedicated_exit import dedicated
 from app.auto_exit import active_match
 c,vector,vid,eid,sourceid,cameraid=dedicated(env)
 with env[1]() as db:
  db.get(Snapshot,db.get(Event,eid).snapshot_id).created_at=now()-timedelta(days=100);db.flush()
  assert active_match(db,vector,c,now()) is not None


def test_fast_mode_does_not_complete_ambiguous_faces(env):
 from tests.test_auto_exit import fixture_records,sample
 from app.models import Camera
 c,vector,vid,eid,sourceid,cameraid=fixture_records(env,True);c.auto_exit_fast_enabled=True
 with env[1]() as db:
  camera=db.get(Camera,cameraid);camera.purpose='Exit Gate';camera.zones={};db.flush()
  assert not sample(db,sourceid,vector,c,0)


def test_single_frame_below_fast_threshold_waits_for_repeated_confirmation(env):
 from tests.test_dedicated_exit import dedicated
 from tests.test_auto_exit import sample
 c,vector,vid,eid,sourceid,cameraid=dedicated(env);c.auto_exit_fast_enabled=True
 vector=[.75,(1-.75**2)**.5]+[0.]*126
 with env[1]() as db:
  assert not sample(db,sourceid,vector,c,0)
  assert not sample(db,sourceid,vector,c,1)
  assert sample(db,sourceid,vector,c,2)


def test_response_rejects_wrong_origin_and_does_not_use_get(env):
 (c,*_),messages,token=sent(env)
 assert env[0].get('/api/resident-response').status_code==405
 assert env[0].post('/api/resident-response',json={'token':token,'answer':'left'},headers={'Origin':'https://attacker.example'}).status_code==403



def test_simulated_test_deadline_cannot_affect_live_visit(client,env):
 c,vid,eid,rid,sid=fixture_visit(env)
 assert client.post('/api/visits/'+vid+'/simulate-overdue').status_code==409
 with env[1]() as db:db.get(Visit,vid).historical=True;db.commit()
 assert client.post('/api/visits/'+vid+'/simulate-overdue').status_code==200
 calls=[];tick(env[1],c,lambda *args:calls.append(1));assert calls==[]


def test_current_month_completed_visit_is_retained(env,monkeypatch):
 c,vid,eid,rid,sid=fixture_visit(env)
 moment=datetime(2026,11,2,tzinfo=timezone.utc)
 with env[1]() as db:
  v=db.get(Visit,vid);v.status='COMPLETED';v.completed_at=moment-timedelta(hours=1);db.get(Event,eid).state='COMPLETED';db.commit()
 monkeypatch.setattr('app.retention.now',lambda:moment);cleanup(env[1],env[2].state.storage,c)
 with env[1]() as db:assert db.get(Visit,vid) and db.get(Event,eid) and db.get(Snapshot,sid)
