from pathlib import Path
import sys,getpass
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import select
from app.config import Settings
from app.database import database
from app.models import User
from app.security import hasher
_,sessions=database(Settings().database_url)
username=input('Administrator username: ').strip();password=getpass.getpass('Administrator password (12+ characters): ')
if len(username)<3 or len(password)<12:raise SystemExit('Username >=3 and password >=12 characters required')
if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ')
with sessions() as db:
    if db.scalar(select(User).where(User.username==username)):raise SystemExit('User exists; no change made')
    db.add(User(username=username,password_hash=hasher.hash(password),role='admin'));db.commit()
print('Administrator created')
