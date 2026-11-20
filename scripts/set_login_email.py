"""Assign an email to a legacy login without changing its password or records."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select,func
from app.config import Settings
from app.database import database
from app.models import User
from app.schemas import normalize_email
from app import events

if __name__=='__main__':
    current=input('Existing login username: ').strip()
    try:email=normalize_email(input('New login email: '))
    except ValueError as exc:raise SystemExit(str(exc))
    engine,sessions=database(Settings().database_url)
    try:
        with sessions.begin() as db:
            user=db.scalar(select(User).where(User.username==current).with_for_update())
            if user is None:raise SystemExit('Login account not found. Nothing changed.')
            other=db.scalar(select(User).where(User.id!=user.id,func.lower(User.email)==email))
            if other:raise SystemExit('Email already belongs to another account. Nothing changed.')
            user.email=email;user.token_version+=1
            events.audit(db,user,None,'SET_LOGIN_EMAIL',user_id=user.id)
        print('Login email updated. Keep using the same password.')
    finally:engine.dispose()
