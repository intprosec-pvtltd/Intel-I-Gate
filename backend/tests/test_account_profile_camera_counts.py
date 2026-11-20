from sqlalchemy import select
from app.models import User,Camera

def profile(name='Lake View Apartments',email='admin@example.test',**extra):
 return {'apartment_name':name,'email':email,**extra}

def test_legacy_admin_adds_name_without_password_or_recreating_account(env,client):
 before=client.get('/api/auth/me').json();assert before['apartment_name'] is None
 response=client.put('/api/account/profile',json=profile());assert response.status_code==200
 assert response.json()['sign_in_required'] is False
 after=client.get('/api/auth/me').json();assert after['id']==before['id'] and after['apartment_name']=='Lake View Apartments'
 assert 'password_hash' not in after and 'current_password' not in response.text
 assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'test-password-123'}).json()['apartment_name']=='Lake View Apartments'

def test_email_change_requires_current_password_and_invalidates_old_sessions(env,client):
 assert client.put('/api/account/profile',json=profile(email='new@example.test')).status_code==403
 assert client.put('/api/account/profile',json=profile(email='new@example.test',current_password='wrong')).status_code==403
 assert client.get('/api/auth/me').json()['email']=='admin@example.test'
 response=client.put('/api/account/profile',json=profile(email=' New@Example.Test ',current_password='test-password-123'))
 assert response.status_code==200 and response.json()['sign_in_required'] is True
 assert client.get('/api/auth/me').status_code==401
 assert client.post('/api/auth/login',json={'email':'admin@example.test','password':'test-password-123'}).status_code==401
 assert client.post('/api/auth/login',json={'email':'new@example.test','password':'test-password-123'}).status_code==200

def test_profile_rejects_duplicate_email_blank_name_and_privilege_escalation(env,client):
 assert client.put('/api/account/profile',json=profile(email='guard@example.test',current_password='test-password-123')).status_code==409
 assert client.put('/api/account/profile',json=profile(name='   ')).status_code==422
 assert client.put('/api/account/profile',json=profile(role='guard')).status_code==422
 assert client.put('/api/account/profile',json=profile(email='invalid')).status_code==422
 with env[1]() as db:assert db.scalar(select(User).where(User.role=='admin')).apartment_name is None

def test_guard_can_edit_own_profile_but_not_others(env,client):
 admin_id=client.get('/api/auth/me').json()['id'];client.cookies.clear()
 assert client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'}).status_code==200
 assert client.put('/api/account/profile',json=profile(name='Guard desk',email='guard@example.test')).status_code==200
 assert client.get('/api/auth/me').json()['role']=='guard'
 assert client.put('/api/users/'+admin_id,json={'email':'admin@example.test','role':'guard','active':False}).status_code==403
 client.cookies.clear();assert client.put('/api/account/profile',json=profile()).status_code==401

def test_profile_email_attempts_rate_limited(env,client):
 for _ in range(5):assert client.put('/api/account/profile',json=profile(email='new@example.test',current_password='wrong')).status_code==403
 assert client.put('/api/account/profile',json=profile(email='new@example.test',current_password='wrong')).status_code==429

def test_configured_cameras_are_not_counted_as_connected_until_streaming(env,client):
 with env[1]() as db:
  db.add_all([Camera(name='cam '+str(i),location='Gate',purpose='Entry Gate',rtsp_encrypted='test',fingerprint='cam'+str(i),status='STOPPED') for i in range(2)]);db.commit()
 data=client.get('/api/dashboard/summary').json();assert data['cameras']==2 and data['connected']==0
 assert all(x['status']=='STOPPED' for x in client.get('/api/cameras').json())
 with env[1]() as db:
  for row in db.scalars(select(Camera)):row.enabled=True;row.status='CONNECTED'
  db.commit()
 assert client.get('/api/dashboard/summary').json()['connected']==2
 with env[1]() as db:
  db.scalar(select(Camera)).status='RECONNECTING';db.commit()
 assert client.get('/api/dashboard/summary').json()['connected']==1

def test_account_name_migration_preserves_existing_admin(tmp_path):
 import importlib.util
 from sqlalchemy import create_engine,text,inspect
 from alembic.migration import MigrationContext
 from alembic.operations import Operations
 from pathlib import Path
 path=Path(__file__).parents[1]/'migrations/versions/0007_account_apartment_name.py'
 spec=importlib.util.spec_from_file_location('account_name_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'))
 try:
  with engine.begin() as conn:
   conn.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(100), password_hash TEXT)'))
   conn.execute(text("INSERT INTO users VALUES ('existing','admin@example.test','existing-hash')"))
   module.op=Operations(MigrationContext.configure(conn));module.upgrade()
   assert conn.execute(text('SELECT email,password_hash,apartment_name FROM users')).one()==('admin@example.test','existing-hash',None)
   assert 'apartment_name' in {x['name'] for x in inspect(conn).get_columns('users')}
 finally:engine.dispose()
