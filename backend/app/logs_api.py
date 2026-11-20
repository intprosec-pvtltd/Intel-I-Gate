from datetime import datetime
from fastapi import APIRouter,Depends,Request,HTTPException,Query
from pydantic import BaseModel,Field
from typing import Literal
from sqlalchemy import select,or_,func
from sqlalchemy.orm import aliased
from .api import session,event_json
from .security import current,admin
from .models import Event,Visit,VisitAlert,Audit,Camera,Video,ExitObservation,now
from .visit_sessions import response,utc
router=APIRouter(prefix='/api')

def alert_json(a,v,e):
    return {'id':a.id,'visit_id':v.id,'event_id':e.id,'flat':v.flat,'resident_name':v.resident_name,'visitor_name':(e.verification or {}).get('visitor_name',''),'purpose':(e.verification or {}).get('visit_purpose','Delivery'),'expected_exit_at':v.expected_exit_at,'created_at':a.created_at,'test_mode':v.historical,'sms_state':a.sms_state,'response':a.response,'responded_at':a.responded_at,'last_error':a.last_error}

@router.get('/visit-alerts')
def alerts(user=Depends(current),db=Depends(session)):
    rows=db.execute(select(VisitAlert,Visit,Event).join(Visit,Visit.id==VisitAlert.visit_id).join(Event,Event.id==Visit.event_id).where(VisitAlert.state=='OPEN',Visit.status=='ENTRY_RECORDED').order_by(VisitAlert.created_at.desc()).limit(100)).all()
    return [alert_json(*row) for row in rows]

CONFIRMED_EXITS=('AUTO_CONFIRMED','GUARD_CONFIRMED')


def source_name(db,event):
    if event.camera_id:
        camera=db.get(Camera,event.camera_id)
        return camera.name if camera else 'Camera unavailable'
    if event.video_id:
        video=db.get(Video,event.video_id)
        return video.filename if video else 'Uploaded video'
    return 'Manual event'


@router.get('/visitor-logs')
def logs(q:str=Query('',max_length=100),status:str=Query('',max_length=40),purpose:str=Query('',max_length=30),source:Literal['all','live','test']='all',camera_id:str=Query('',max_length=36),start:datetime|None=None,end:datetime|None=None,offset:int=Query(0,ge=0),user=Depends(current),db=Depends(session)):
    # Group by the actual saved visit relationship, never by face/name/flat.
    # Exclude linked confirmed exit source rows BEFORE counting and pagination.
    exit_link=aliased(ExitObservation);saved=aliased(Visit)
    linked_exit=select(exit_link.id).join(saved,saved.id==exit_link.visit_id).where(exit_link.track_ref==Event.track_ref,saved.event_id!=Event.id,exit_link.state.in_(CONFIRMED_EXITS)).exists()
    activity=func.coalesce(Visit.completed_at,Event.created_at)
    stmt=select(Event,Visit).join(Visit,Visit.event_id==Event.id).where(Visit.status.in_(('ENTRY_RECORDED','COMPLETED')),~linked_exit)
    if q:stmt=stmt.where(or_(Visit.resident_name.ilike('%'+q+'%'),Visit.flat.ilike('%'+q+'%'),Event.verification['visitor_name'].as_string().ilike('%'+q+'%')))
    if status=='OVERDUE':stmt=stmt.where(Visit.status=='ENTRY_RECORDED',Visit.expected_exit_at<now())
    elif status=='EXIT_CONFIRMED':
        confirmed=select(exit_link.id).where(exit_link.visit_id==Visit.id,exit_link.state.in_(CONFIRMED_EXITS)).exists()
        stmt=stmt.where(or_(Event.state=='EXIT_CONFIRMED',confirmed))
    elif status:stmt=stmt.where(func.coalesce(Visit.status,Event.state)==status)
    if purpose:stmt=stmt.where(Event.verification['visit_purpose'].as_string()==purpose)
    if source!='all':stmt=stmt.where(Event.video_id.is_(None) if source=='live' else Event.video_id.is_not(None))
    if camera_id:
        exit_source=aliased(Event)
        at_exit=select(exit_link.id).join(exit_source,exit_source.track_ref==exit_link.track_ref).where(exit_link.visit_id==Visit.id,exit_link.state.in_(CONFIRMED_EXITS),exit_source.camera_id==camera_id).exists()
        stmt=stmt.where(or_(Event.camera_id==camera_id,at_exit))
    for value in (start,end):
        if value and value.tzinfo is None:raise HTTPException(422,'Date filters require a timezone')
    if start:stmt=stmt.where(activity>=start)
    if end:stmt=stmt.where(activity<=end)
    total=db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows=db.execute(stmt.order_by(activity.desc(),Event.id).offset(offset).limit(50)).all()
    items=[]
    for e,v in rows:
        item=event_json(e,db)
        departure=None
        if v:
            observation=db.scalar(select(ExitObservation).where(ExitObservation.visit_id==v.id,ExitObservation.state.in_(CONFIRMED_EXITS)).order_by(ExitObservation.created_at.desc(),ExitObservation.id).limit(1))
            if observation:departure=db.scalar(select(Event).where(Event.track_ref==observation.track_ref))
        item.update(visit_id=v.id if v else None,state=v.status if v else e.state,expected_exit_at=v.expected_exit_at if v else None,overdue=bool(v and v.status=='ENTRY_RECORDED' and v.expected_exit_at and utc(v.expected_exit_at)<now()),resident_name=v.resident_name if v else (e.verification or {}).get('resident_name'),flat=v.flat if v else (e.verification or {}).get('flat'),visit_details=e.verification or {},entry_camera_name=source_name(db,e) if v else None,exit_camera_name=source_name(db,departure) if departure else None,last_activity_at=(v.completed_at if v and v.completed_at else e.created_at))
        items.append(item)
    return {'total':total,'items':items}


@router.get('/visitor-logs/{ident}')
def timeline(ident:str,user=Depends(current),db=Depends(session)):
    e=db.get(Event,ident)
    if not e:raise HTTPException(404,'Event not found')
    timing=event_json(e,db).get('visit_timing')
    visit=db.get(Visit,timing['visit_id']) if timing else None
    related={e.id:e}
    entry=db.get(Event,visit.event_id) if visit else e
    related[entry.id]=entry
    if visit:
        tracks=list(db.scalars(select(ExitObservation.track_ref).where(ExitObservation.visit_id==visit.id,ExitObservation.state.in_(CONFIRMED_EXITS))))
        for other in db.scalars(select(Event).where(Event.track_ref.in_(tracks))):related[other.id]=other
    records=[];observations=[]
    from .models import Snapshot
    for item in sorted(related.values(),key=lambda x:utc(x.created_at)):
        role='Entry' if visit and item.id==entry.id else 'Exit' if visit else 'Observation'
        camera=source_name(db,item)
        records.append({'action':'DETECTED' if item.id==entry.id else 'EXIT_OBSERVED','created_at':item.captured_at or item.created_at,'details':{'source':camera,'role':role}})
        photo=db.get(Snapshot,item.snapshot_id) if item.snapshot_id else None
        if photo and photo.deleted:photo=None
        if photo:records.append({'action':'CURRENT_PHOTO_CAPTURED','created_at':photo.created_at,'details':{'source':camera,'role':role}})
        observations.append({'event_id':item.id,'role':role,'camera_name':camera,'snapshot_id':photo.id if photo else None,'state':item.state,'test_mode':bool(item.video_id),'frame_seconds':item.frame_seconds,'observed_at':item.captured_at or item.created_at})
    records.extend({'action':a.action,'created_at':a.created_at,'details':{k:v for k,v in (a.details or {}).items() if k in ('method','test_mode','expected_exit_at','confirmed_at','exit_time_basis')}} for a in db.scalars(select(Audit).where(Audit.event_id.in_(list(related))).order_by(Audit.created_at)))
    return {'event':event_json(entry,db),'observations':observations,'timeline':sorted(records,key=lambda a:utc(a['created_at']))}

class ResidentReply(BaseModel):
    token:str=Field(min_length=40,max_length=100)
    answer:Literal['left','present']

@router.post('/resident-response')
def reply(data:ResidentReply,request:Request,db=Depends(session)):
    import time
    key=('resident-reply',request.client.host if request.client else '')
    attempts=request.app.state.attempts[key];moment=time.monotonic()
    while attempts and moment-attempts[0]>60:attempts.popleft()
    if len(attempts)>=10:raise HTTPException(429,'Too many requests. Please wait.')
    attempts.append(moment)
    return response(db,data.token,data.answer,request.app.state.config)


@router.post('/visits/{ident}/simulate-overdue')
def simulate_overdue(ident:str,user=Depends(admin),db=Depends(session)):
    from .events import lock,audit
    from datetime import timedelta
    v=db.get(Visit,ident)
    if not v:raise HTTPException(404,'Visit not found')
    e=lock(db,v.event_id)
    v=db.scalar(select(Visit).where(Visit.id==ident).with_for_update().execution_options(populate_existing=True))
    if not v.historical or v.status!='ENTRY_RECORDED':raise HTTPException(409,'Only an active uploaded test visit can simulate a deadline')
    v.expected_exit_at=now()-timedelta(seconds=1)
    audit(db,user,e,'SIMULATE_OVERDUE',test_mode=True);db.commit()
    return {'message':'Test deadline elapsed. The alert will appear on the next maintenance check. No resident SMS will be sent.'}
