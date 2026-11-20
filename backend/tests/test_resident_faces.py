import json
from types import SimpleNamespace
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app.models import Resident,ResidentFace,User,Camera,Event,Snapshot,Visit,now
from app.security import protect
from app.resident_faces import match_resident
from app.worker import Manager
from app.retention import cleanup

VECTOR=[1.]+[0.]*127

def fixture(env):
 c=env[2].state.config;c.biometric_enabled=True
 with env[1]() as db:
  u=db.scalar(select(User).where(User.username=='admin'))
  r=Resident(name='Fixture resident',flat='B-203');db.add(r)
  cam=Camera(name='Entry',location='gate',purpose='Entry Gate',rtsp_encrypted='unused',fingerprint='resident-test');db.add(cam)
  s=Snapshot(path=env[2].state.storage.put(b'fixture-photo'),quality=10,created_at=now()-timedelta(days=60));db.add(s);db.flush()
  e=Event(camera_id=cam.id,track_ref='enroll-me',snapshot_id=s.id,state='PENDING_VERIFICATION');db.add(e);db.commit()
  return c,r.id,s.id,e.id,cam.id,u.id

def enroll_mock(env,monkeypatch):
 monkeypatch.setattr('cv2.imdecode',lambda *a:object())
 monkeypatch.setattr('app.vision.FaceService',lambda c:SimpleNamespace(single_snapshot_embedding=lambda frame:VECTOR))
 env[2].state.worker.pipeline=SimpleNamespace()

def body(rid):return {'resident_id':rid,'consent':True,'confirmed_identity':True}

def test_enrollment_and_remove(env,client,monkeypatch):
 c,rid,sid,eid,cam,uid=fixture(env);enroll_mock(env,monkeypatch)
 assert client.post('/api/events/'+eid+'/resident',json=body(rid)).status_code==200
 with env[1]() as db:
  assert match_resident(db,VECTOR,c)==rid
  assert db.get(Event,eid).state=='RESIDENT'
  assert db.scalar(select(func.count()).select_from(Visit))==0
 assert client.get('/api/events/pending').json()==[]
 assert client.get('/api/dashboard/recent-events').json()==[]
 assert client.get('/api/resident-faces').json()[0]['active']
 assert client.delete('/api/resident-faces/'+rid).status_code==200
 with env[1]() as db:assert match_resident(db,VECTOR,c) is None

@pytest.mark.parametrize('condition',['consent','identity','biometrics','test_video','completed','missing_photo','no_face'])
def test_invalid_enrollments_rejected(env,client,monkeypatch,condition):
 c,rid,sid,eid,cam,uid=fixture(env);enroll_mock(env,monkeypatch);data=body(rid)
 if condition=='consent':data['consent']=False
 if condition=='identity':data['confirmed_identity']=False
 if condition=='biometrics':c.biometric_enabled=False
 if condition=='no_face':monkeypatch.setattr('app.vision.FaceService',lambda c:SimpleNamespace(single_snapshot_embedding=lambda f:None))
 with env[1]() as db:
  e=db.get(Event,eid)
  if condition=='test_video':e.camera_id=None
  if condition=='completed':e.state='COMPLETED'
  if condition=='missing_photo':e.snapshot_id=None
  db.commit()
 assert client.post('/api/events/'+eid+'/resident',json=data).status_code in (409,422)


def test_ambiguous_invalid_and_disabled_matches_are_not_suppressed(env):
 c,rid,sid,eid,cam,uid=fixture(env)
 with env[1]() as db:
  db.add(ResidentFace(resident_id=rid,snapshot_id=sid,embedding_encrypted=protect(json.dumps(VECTOR),c),enrolled_by=uid));db.commit()
  assert match_resident(db,VECTOR,c)==rid
  assert match_resident(db,[0.]*128,c) is None
  assert match_resident(db,[float('nan')]*128,c) is None
  assert match_resident(db,[0.,1.]+[0.]*126,c) is None
  c.resident_recognition_enabled=False;assert match_resident(db,VECTOR,c) is None;c.resident_recognition_enabled=True
  other=Resident(name='Other',flat='B-204');db.add(other);db.flush()
  db.add(ResidentFace(resident_id=other.id,embedding_encrypted=protect(json.dumps(VECTOR),c),enrolled_by=uid));db.commit()
  assert match_resident(db,VECTOR,c) is None


def test_live_match_writes_no_new_event_snapshot_or_detection(env):
 c,rid,sid,eid,cam,uid=fixture(env)
 with env[1]() as db:
  db.add(ResidentFace(resident_id=rid,snapshot_id=sid,embedding_encrypted=protect(json.dumps(VECTOR),c),enrolled_by=uid));db.commit()
 source=SimpleNamespace(key='camera:'+cam,ident=cam,live=True)
 env[2].state.worker.persist(source,[{'track_id':123,'exit_embedding':VECTOR}],0,now(),'epoch')
 with env[1]() as db:
  assert db.scalar(select(func.count()).select_from(Event))==1
  assert db.scalar(select(func.count()).select_from(Snapshot))==1


def test_resident_removal_erases_reference_and_retention_protects_enrollment(env,client):
 c,rid,sid,eid,cam,uid=fixture(env);c.calendar_cleanup_enabled=True
 with env[1]() as db:
  db.add(ResidentFace(resident_id=rid,snapshot_id=sid,embedding_encrypted=protect(json.dumps(VECTOR),c),enrolled_by=uid));e=db.get(Event,eid);e.created_at=now()-timedelta(days=60);e.state='RESIDENT';db.commit()
 cleanup(env[1],env[2].state.storage,c)
 with env[1]() as db:
  assert db.get(Snapshot,sid) is not None
  assert db.get(Event,eid) is None
 assert client.delete('/api/residents/'+rid).status_code==200
 with env[1]() as db:
  f=db.scalar(select(ResidentFace));assert not f.active and f.embedding_encrypted is None and f.snapshot_id is None


def test_guard_cannot_remove_enrollment_and_anonymous_cannot_list(env,client):
 client.cookies.clear();assert client.get('/api/resident-faces').status_code==401
 assert client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'}).status_code==200
 assert client.delete('/api/resident-faces/any').status_code==403


def test_uploaded_video_is_not_suppressed_by_resident_gallery(env):
 from app.models import Video
 c,rid,sid,eid,cam,uid=fixture(env)
 with env[1]() as db:
  db.add(ResidentFace(resident_id=rid,snapshot_id=sid,embedding_encrypted=protect(json.dumps(VECTOR),c),enrolled_by=uid))
  video=Video(filename='fixture.mp4',path='uploads/fixture.mp4',duration=10,size=10,test_role='entry');db.add(video);db.commit();vid=video.id
 source=SimpleNamespace(key='video:'+vid,ident=vid,live=False,test_role='entry')
 row={'track_id':123,'exit_embedding':VECTOR,'face':None,'objects':[],'possible':False,'box':[0,0,10,10],'entry':False,'exit':False}
 env[2].state.worker.persist(source,[row],0,None,'epoch')
 with env[1]() as db:
  assert db.scalar(select(Event).where(Event.video_id==vid)).state=='PENDING_VERIFICATION'


def test_migration_creates_and_drops_resident_faces(env):
 import importlib.util
 from pathlib import Path
 from alembic.migration import MigrationContext
 from alembic.operations import Operations
 from sqlalchemy import inspect
 path=Path(__file__).parents[1]/'migrations/versions/0006_resident_faces.py'
 spec=importlib.util.spec_from_file_location('resident_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 with env[1]().bind.begin() as conn:
  ResidentFace.__table__.drop(conn)
  with Operations.context(MigrationContext.configure(conn)):
   module.upgrade();assert 'resident_faces' in inspect(conn).get_table_names()
   module.downgrade();assert 'resident_faces' not in inspect(conn).get_table_names()
   module.upgrade()
