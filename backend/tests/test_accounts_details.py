from sqlalchemy import select
from app.models import User,Event,Visit

def test_change_password_requires_current_and_invalidates_session(env,client):
 assert client.post('/api/account/password',json={'current_password':'wrong','new_password':'replacement-password-123'}).status_code==403
 assert client.post('/api/account/password',json={'current_password':'test-password-123','new_password':'replacement-password-123'}).status_code==200
 assert client.get('/api/auth/me').status_code==401
 assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'replacement-password-123'}).status_code==200

def test_admin_edit_reset_and_guard_authorization(env,client):
 with env[1]() as db:guard=db.scalar(select(User).where(User.role=='guard'));gid=guard.id
 assert client.put('/api/users/'+gid,json={'email':'changed@example.test','role':'guard','active':False}).status_code==200
 assert client.post('/api/users/'+gid+'/reset-password',json={'new_password':'replacement-password-123'}).status_code==200
 assert client.put('/api/users/'+gid,json={'email':'changed@example.test','role':'guard','active':True}).status_code==200
 client.cookies.clear();assert client.post('/api/auth/login',json={'email':'changed@example.test','password':'replacement-password-123'}).status_code==200
 assert client.put('/api/users/'+gid,json={'email':'changed@example.test','role':'admin','active':True}).status_code==403

def test_self_demotion_and_disable_rejected(env,client):
 uid=client.get('/api/auth/me').json()['id']
 assert client.put('/api/users/'+uid,json={'email':'admin@example.test','role':'guard','active':True}).status_code==409
 assert client.post('/api/users/'+uid+'/disable').status_code==409

def test_detail_requires_auth_and_has_timeline(env,client):
 with env[1]() as db:
  u=db.scalar(select(User).where(User.role=='admin'));e=Event(track_ref='details',state='ENTRY_RECORDED');db.add(e);db.flush();v=Visit(event_id=e.id,guard_id=u.id,resident_name='Test',flat='A-1');db.add(v);db.commit();vid=v.id
 data=client.get('/api/visits/'+vid);assert data.status_code==200;assert data.json()['flat']=='A-1';assert data.json()['timeline']
 client.cookies.clear();assert client.get('/api/visits/'+vid).status_code==401

def test_dedup_overlap():
 from app.dedup import overlap
 assert overlap([0,0,100,100],[0,0,100,100])==1
 assert overlap([0,0,10,10],[20,20,30,30])==0

def test_recovery_requires_recent_same_camera_clear_match(env):
 import json
 from app.models import Camera,Snapshot,now
 from app.security import protect
 from app.dedup import recover
 c=env[2].state.config;c.biometric_enabled=True;vector=[1.]+[0.]*127
 with env[1]() as db:
  camera=Camera(name='dedup',location='gate',purpose='Entry Gate',rtsp_encrypted='test',fingerprint='dedup');db.add(camera)
  snap=Snapshot(path='temporary/example.jpg',quality=1,embedding_encrypted=protect(json.dumps(vector),c));db.add(snap);db.flush()
  event=Event(camera_id=camera.id,track_ref='dedup',snapshot_id=snap.id,evidence={'last_seen_epoch':now().timestamp(),'box':[0,0,100,100]});db.add(event);db.commit()
  assert recover(db,camera.id,vector,[0,0,100,100],c).id==event.id
  assert recover(db,camera.id,vector,[200,200,300,300],c) is None
  event.evidence={**event.evidence,'last_seen_epoch':0};db.commit()
  assert recover(db,camera.id,vector,[0,0,100,100],c) is None
