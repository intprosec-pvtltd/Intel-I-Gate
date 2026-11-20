"""Test-only app. Do not use for deployment."""
from pathlib import Path
import os
from cryptography.fernet import Fernet
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from app.models import Base,User
from app.security import hasher
from app.config import Settings
from app.main import create_app
root=Path(os.environ['INTEL_TEST_DIRECTORY']).resolve();root.mkdir(parents=True,exist_ok=True)
engine=create_engine('sqlite:///'+str(root/'test.db'),connect_args={'check_same_thread':False});Base.metadata.create_all(engine);sessions=sessionmaker(engine,expire_on_commit=False)
with sessions() as db:
    if not db.scalar(select(User).where(User.username=='e2e-admin')):db.add(User(username='e2e-admin',password_hash=hasher.hash(os.environ['E2E_PASSWORD']),role='admin'));db.commit()
c=Settings(_env_file=None,secret_key='browser-test-only-secret-'*3,encryption_key=Fernet.generate_key().decode(),storage_dir=root/'storage',ai_enabled=False)
app=create_app(c,sessions,start_worker=False)
