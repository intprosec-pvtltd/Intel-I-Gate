from sqlalchemy import select
from datetime import timedelta
from fastapi import HTTPException
from .models import Event,Visit,Resident,Snapshot,Audit,ExitObservation,Video,now
EDITABLE={'PENDING_VERIFICATION','CONFIRMED','NEEDS_REVIEW'}
def audit(db,user,event,action,**details):db.add(Audit(actor_id=user.id if user else None,event_id=event.id if event else None,action=action,details=details))
def lock(db,ident):
    e=db.scalar(select(Event).where(Event.id==ident).with_for_update().execution_options(populate_existing=True))
    if not e:raise HTTPException(404,'Event not found')
    return e
def verify(db,e,data,user,c=None):
    if e.video_id and (video:=db.get(Video,e.video_id)) and video.test_role=='exit':raise HTTPException(409,'Review exit test observations in Visit history; do not create a new entry')
    if e.state not in EDITABLE:raise HTTPException(409,'Event cannot be verified in its current state')
    if data.resident_id:
        r=db.get(Resident,data.resident_id)
        if not r or not r.active or r.name!=data.resident_name or r.flat!=data.flat:raise HTTPException(422,'Resident and flat do not match')
    if c is not None:
        from .otp import require_verified
        approval=require_verified(db,e,data,user,c)
    if c is not None and not e.video_id and data.visit_purpose!='Delivery' and (data.expected_exit_at is None or data.expected_exit_at<=now()):
        raise HTTPException(422,'Enter a future expected exit date and time')
    old=e.state;e.state='CONFIRMED';e.candidate_status='GUARD_CONFIRMED_DELIVERY' if data.visit_purpose=='Delivery' else 'GUARD_CONFIRMED_VISIT'
    e.verification=data.model_dump(mode='json');e.verified_by=user.id
    if c is not None:e.verification={**e.verification,'resident_approval':{'method':'SMS_OTP','resident_id':approval.resident_id,'guard_id':user.id,'verified_at':approval.verified_at.isoformat()}}
    audit(db,user,e,'VERIFY',previous=old,state=e.state)
def save(db,ident,data,user,c=None):
    e=lock(db,ident)
    existing=db.scalar(select(Visit).where(Visit.event_id==ident))
    if existing:return existing
    if c is not None and (e.state!='CONFIRMED' or e.verified_by!=user.id or any((e.verification or {}).get(k)!=v for k,v in data.model_dump(mode='json').items())):
        raise HTTPException(409,'Confirm Visit with these destination details before Save Event')
    verify(db,e,data,user,c)
    if e.snapshot_id:
        s=db.get(Snapshot,e.snapshot_id)
        if s and not s.deleted:s.approved=True
    v=Visit(event_id=e.id,guard_id=user.id,resident_id=data.resident_id,resident_name=data.resident_name,flat=data.flat,company=data.company,notes=f'Visit purpose: {data.visit_purpose}\n{data.notes}'.rstrip(),entry_at=(e.captured_at if e.video_id else (e.captured_at or now())),historical=bool(e.video_id))
    if c is not None:
        from .otp import consume
        consume(db,e)
    v.expected_exit_at=now()+timedelta(minutes=15) if data.visit_purpose=='Delivery' else data.expected_exit_at
    db.add(v);e.state='ENTRY_RECORDED';audit(db,user,e,'SAVE_EVENT',flat=data.flat)
    db.flush();return v
def transition(db,e,target,user):
    if e.state not in EDITABLE:raise HTTPException(409,'Event cannot be changed in its current state')
    old=e.state;e.state=target;e.candidate_status='NOT_DELIVERY' if target=='NOT_DELIVERY' else 'NEEDS_REVIEW'
    from .otp import invalidate
    invalidate(db,e)
    e.verification=None;e.verified_by=None;audit(db,user,e,target,previous=old)
def complete(db,e,data,user):
    v=db.scalar(select(Visit).where(Visit.event_id==e.id).with_for_update())
    if not v:raise HTTPException(409,'Save the visit first')
    if v.status=='COMPLETED':return v
    entry_video=db.get(Video,e.video_id) if e.video_id else None
    if v.historical and (not entry_video or entry_video.test_role!='entry'):
        raise HTTPException(409,'Only an Entry-labelled test recording can use video test exit review')
    if v.historical and not data.observation_id:
        raise HTTPException(422,'Select an Exit-labelled video observation for this test visit')
    when=now()
    if data.observation_id:
        x=db.scalar(select(ExitObservation).where(ExitObservation.id==data.observation_id).with_for_update())
        if not x or x.state!='NEEDS_REVIEW':raise HTTPException(422,'Exit observation unavailable')
        if bool(x.video_id)!=bool(v.historical):raise HTTPException(409,'Live and recorded-video visits must be reviewed separately')
        if x.video_id:
            video=db.get(Video,x.video_id)
            if not video or video.test_role!='exit':raise HTTPException(409,'Use an Exit-labelled recording')
        if x.visit_id and x.visit_id!=v.id:raise HTTPException(409,'This observation is linked to another visit')
        if not v.historical and v.entry_at and x.created_at<v.entry_at:raise HTTPException(422,'Exit observation predates arrival')
        x.visit_id=v.id;x.state='GUARD_CONFIRMED';when=x.created_at
        # The source event is evidence, not another visitor entry.
        if x.video_id:
            source=db.scalar(select(Event).where(Event.track_ref==x.track_ref).with_for_update())
            if source:source.state='EXIT_CONFIRMED'
    v.completed_at=now()
    v.status=e.state='COMPLETED'
    v.exit_at=None if v.historical else when
    e.evidence={**(e.evidence or {}),'exit_completion':{'method':'GUARD_CONFIRMED','confirmed_at':now().isoformat()}}
    from .visit_sessions import resolve_alert
    resolve_alert(db,v)
    audit(db,user,e,'COMPLETE_TEST' if v.historical else 'COMPLETE',reason=data.reason,observation_id=data.observation_id)
    return v
