"""Authenticated account changes and administrator controls."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field,field_validator
from sqlalchemy import select,func,or_
from .api import session
from .schemas import Input,normalize_email
from .models import User
from .security import current,admin,hasher,password_matches
from .events import audit
router=APIRouter(prefix='/api')
class Password(Input):
    model_config={'extra':'forbid','str_strip_whitespace':False}
    current_password:str=Field(min_length=1,max_length=200)
    new_password:str=Field(min_length=12,max_length=200)
class Reset(Input):
    model_config={'extra':'forbid','str_strip_whitespace':False}
    new_password:str=Field(min_length=12,max_length=200)
class Edit(Input):
    email:str=Field(max_length=100)
    role:Literal['admin','guard']
    active:bool
    _email=field_validator('email')(normalize_email)
def locked_users(db):
    # Serialize account mutations in a stable order, protecting the last admin.
    return list(db.scalars(select(User).order_by(User.id).with_for_update()))
def safe_change(rows,target,active,role):
    if target.active and target.role=='admin' and (not active or role!='admin') and sum(x.active and x.role=='admin' for x in rows)<=1:
        raise HTTPException(409,'Keep at least one active administrator')
@router.post('/account/password')
def change_password(data:Password,request:Request,u=Depends(current),db=Depends(session)):
    import time
    key=('password-change',u.id);attempts=request.app.state.attempts[key];moment=time.monotonic()
    while attempts and moment-attempts[0]>300:attempts.popleft()
    if len(attempts)>=5:raise HTTPException(429,'Too many password changes. Try again later')
    attempts.append(moment)
    rows=locked_users(db);r=next(x for x in rows if x.id==u.id)
    if not password_matches(r.password_hash,data.current_password):raise HTTPException(403,'Current password is incorrect')
    if data.current_password==data.new_password:raise HTTPException(422,'Choose a different new password')
    r.password_hash=hasher.hash(data.new_password);r.token_version+=1;audit(db,u,None,'CHANGE_PASSWORD');db.commit();return {'ok':True,'sign_in_required':True}
@router.put('/users/{ident}')
def edit_user(ident:str,data:Edit,u=Depends(admin),db=Depends(session)):
    rows=locked_users(db);r=next((x for x in rows if x.id==ident),None)
    if not r:raise HTTPException(404,'User not found')
    if ident==u.id and (not data.active or data.role!='admin'):raise HTTPException(409,'Cannot disable or demote your own account')
    safe_change(rows,r,data.active,data.role)
    if any(x.id!=ident and (x.email==data.email or x.username.lower().strip()==data.email) for x in rows):raise HTTPException(409,'Email already registered')
    r.email=r.username=data.email;r.role=data.role;r.active=data.active;r.token_version+=1
    audit(db,u,None,'UPDATE_USER',user_id=ident);db.commit();return {'ok':True}
@router.post('/users/{ident}/reset-password')
def reset_password(ident:str,data:Reset,u=Depends(admin),db=Depends(session)):
    rows=locked_users(db);r=next((x for x in rows if x.id==ident),None)
    if not r:raise HTTPException(404,'User not found')
    r.password_hash=hasher.hash(data.new_password);r.token_version+=1;audit(db,u,None,'RESET_USER_PASSWORD',user_id=ident);db.commit();return {'ok':True}

class Profile(Input):
    apartment_name:str=Field(min_length=1,max_length=120)
    email:str=Field(max_length=100)
    current_password:str|None=Field(default=None,max_length=200)
    _email=field_validator('email')(normalize_email)
    model_config={'extra':'forbid','str_strip_whitespace':False}
    @field_validator('apartment_name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value:raise ValueError('Enter your apartment name')
        return value

@router.put('/account/profile')
def update_profile(data:Profile,request:Request,u=Depends(current),db=Depends(session)):
    from sqlalchemy.exc import IntegrityError
    rows=locked_users(db);r=next(x for x in rows if x.id==u.id)
    email_changed=r.email!=data.email
    if email_changed:
        import time
        key=('profile-email-change',u.id);attempts=request.app.state.attempts[key];moment=time.monotonic()
        while attempts and moment-attempts[0]>300:attempts.popleft()
        if len(attempts)>=5:raise HTTPException(429,'Too many email change attempts. Try again later')
        attempts.append(moment)
        if not data.current_password or not password_matches(r.password_hash,data.current_password):
            raise HTTPException(403,'Enter your correct current password to change the login email')
        if any(x.id!=r.id and (x.email==data.email or x.username.lower().strip()==data.email) for x in rows):
            raise HTTPException(409,'Email already registered')
    r.apartment_name=data.apartment_name
    if email_changed:r.email=r.username=data.email;r.token_version+=1
    audit(db,u,None,'UPDATE_ACCOUNT_PROFILE',email_changed=email_changed)
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Email already registered')
    return {'ok':True,'sign_in_required':email_changed,'user':{'id':r.id,'username':r.username,'email':r.email,'role':r.role,'apartment_name':r.apartment_name}}
