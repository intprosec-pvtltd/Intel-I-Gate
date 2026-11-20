from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import hasher
from app.main import create_app
@pytest.fixture
def env(tmp_path):
    c=Settings(_env_file=None,secret_key='isolated-test-secret-'*3,encryption_key=Fernet.generate_key().decode(),storage_dir=tmp_path/'storage',model_dir=tmp_path/'models',ai_enabled=False,camera_allow_cidrs='192.168.1.50/32')
    engine=create_engine('sqlite:///'+str(tmp_path/'test.db'),connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def fk(conn,record):conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine);sessions=sessionmaker(engine,expire_on_commit=False)
    with sessions() as db:
        db.add_all([User(username='admin',email='admin@example.test',password_hash=hasher.hash('test-password-123'),role='admin'),User(username='guard',email='guard@example.test',password_hash=hasher.hash('test-password-123'),role='guard')]);db.commit()
    app=create_app(c,sessions,start_worker=False)
    with TestClient(app) as client:
        client.headers.update({'Origin':'http://localhost:5173','X-Intel-Request':'1'})
        yield client,sessions,app
    engine.dispose()
@pytest.fixture
def client(env):
    c=env[0];assert c.post('/api/auth/login',json={'email':'admin@example.test','password':'test-password-123'}).status_code==200;return c
