"""Overdue visit outbox and single-use resident responses; no SMS for video tests."""
from datetime import timedelta,timezone
import hashlib,secrets,threading
from sqlalchemy import select,text,or_
from fastapi import HTTPException
from .models import Visit,VisitAlert,Event,Resident,now
from .security import protect,reveal
from . import otp
from .events import audit,lock
_guard=threading.Lock()

def utc(v):return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v

def resolve_alert(db,visit):
    a=db.scalar(select(VisitAlert).where(VisitAlert.visit_id==visit.id).with_for_update())
    if a:
        a.state='RESOLVED';a.resolved_at=now();a.token_digest=None;a.token_encrypted=None

def tick(sessions,c,sender=None):
    if not _guard.acquire(blocking=False):return
    try:
        moment=now()
        with sessions() as db:
            if db.bind.dialect.name=='postgresql' and not db.scalar(text('SELECT pg_try_advisory_xact_lock(701924119)')):return
            for v in db.scalars(select(Visit).where(Visit.status=='ENTRY_RECORDED',Visit.expected_exit_at.is_(None))):
                # Existing non-delivery records are not assigned an invented deadline.
                e=db.get(Event,v.event_id)
                if (e.verification or {}).get('visit_purpose','Delivery')=='Delivery':v.expected_exit_at=utc(v.created_at)+timedelta(minutes=15)
            db.flush()
            for v in db.scalars(select(Visit).where(Visit.status=='ENTRY_RECORDED',Visit.expected_exit_at<=moment)):
                if not db.scalar(select(VisitAlert.id).where(VisitAlert.visit_id==v.id)):
                    a=VisitAlert(visit_id=v.id,sms_state='TEST_ONLY' if v.historical else 'PENDING');db.add(a)
                    audit(db,None,db.get(Event,v.event_id),'VISIT_OVERDUE',test_mode=v.historical,expected_exit_at=v.expected_exit_at.isoformat())
            for a in db.scalars(select(VisitAlert).where(VisitAlert.state=='OPEN')):
                v=db.get(Visit,a.visit_id)
                if not v or v.status!='ENTRY_RECORDED':resolve_alert(db,v) if v else None
                elif a.sms_state=='SENDING' and (moment-utc(a.next_attempt_at or a.created_at)).total_seconds()>300:
                    a.sms_state='UNKNOWN';a.last_error='Submission interrupted; check provider logs before resending'
            db.commit()
            ids=list(db.scalars(select(VisitAlert.id).where(VisitAlert.state=='OPEN',VisitAlert.sms_state.in_(['PENDING','RETRY']),VisitAlert.attempts<3,or_(VisitAlert.next_attempt_at.is_(None),VisitAlert.next_attempt_at<=moment)).order_by(VisitAlert.created_at)))
        for ident in ids[:3]:
            with sessions() as db:
                a=db.get(VisitAlert,ident)
                if not a:continue
                v=db.get(Visit,a.visit_id)
                if not v:continue
                e=lock(db,v.event_id)
                v=db.scalar(select(Visit).where(Visit.id==v.id).with_for_update().execution_options(populate_existing=True))
                a=db.scalar(select(VisitAlert).where(VisitAlert.id==ident).with_for_update().execution_options(populate_existing=True))
                if not a or a.state!='OPEN' or a.sms_state not in ('PENDING','RETRY') or v.status!='ENTRY_RECORDED' or v.historical:continue
                if a.next_attempt_at and utc(a.next_attempt_at)>now():continue
                r=db.get(Resident,v.resident_id) if v.resident_id else None
                if not c.public_app_url or not otp.configured(c) or not r or not r.active or not r.phone_encrypted:
                    a.last_error='Configure public HTTPS URL, SMS sender and active resident contact';a.next_attempt_at=now()+timedelta(minutes=5);db.commit();continue
                recent=list(db.scalars(select(VisitAlert.id).where(VisitAlert.id!=a.id,VisitAlert.destination_digest==otp.destination(c,r),VisitAlert.created_at>now()-timedelta(hours=1),VisitAlert.sms_state.in_(['SUBMITTED','SENDING']))))
                if len(recent)>=5:
                    a.last_error='Resident notification limit reached; retry scheduled';a.next_attempt_at=now()+timedelta(minutes=10);db.commit();continue
                token=reveal(a.token_encrypted,c) if a.token_encrypted else secrets.token_urlsafe(32)
                a.token_digest=hashlib.sha256(token.encode()).hexdigest();a.token_encrypted=protect(token,c)
                a.expires_at=now()+timedelta(hours=c.visit_response_hours);a.destination_digest=otp.destination(c,r)
                a.sms_state='SENDING';a.attempts+=1;a.next_attempt_at=now();a.last_error=None
                phone=reveal(r.phone_encrypted,c);message=f'INTEL-I GATE: The visitor to {v.flat} is overdue for exit. Please confirm whether they have left or are still present: {c.public_app_url.rstrip("/")}/resident-response#{token}'
                db.commit()
            error=None
            try:(sender or otp.send_message)(c,phone,message)
            except Exception as exc:error=exc
            with sessions() as db:
                a=db.scalar(select(VisitAlert).where(VisitAlert.id==ident).with_for_update())
                if not a or a.state!='OPEN' or a.sms_state!='SENDING':continue
                if error:
                    # An HTTP rejection is definite; transport errors are uncertain and are not auto-retried.
                    definite=isinstance(error,HTTPException) and 'did not accept' in str(error.detail)
                    a.sms_state='RETRY' if definite and a.attempts<3 else ('FAILED' if definite else 'UNKNOWN')
                    a.next_attempt_at=now()+timedelta(minutes=5*a.attempts);a.last_error='Provider rejected SMS' if definite else 'Submission unconfirmed; inspect provider logs'
                else:a.sms_state='SUBMITTED';audit(db,None,db.get(Event,db.get(Visit,a.visit_id).event_id),'OVERDUE_SMS_SUBMITTED')
                db.commit()
    finally:_guard.release()

def response(db,token,answer,c):
    digest=hashlib.sha256(token.encode()).hexdigest()
    a=db.scalar(select(VisitAlert).where(VisitAlert.token_digest==digest))
    if not a:raise HTTPException(410,'This link is unavailable or has already been used')
    v=db.get(Visit,a.visit_id)
    if not v:raise HTTPException(410,'This visit is unavailable')
    e=lock(db,v.event_id)
    v=db.scalar(select(Visit).where(Visit.id==v.id).with_for_update().execution_options(populate_existing=True))
    a=db.scalar(select(VisitAlert).where(VisitAlert.id==a.id).with_for_update().execution_options(populate_existing=True))
    r=db.get(Resident,v.resident_id) if v.resident_id else None
    if not a or a.token_digest!=digest or a.state!='OPEN' or not a.expires_at or utc(a.expires_at)<=now() or v.status!='ENTRY_RECORDED' or v.historical or not r or not r.active or otp.destination(c,r)!=a.destination_digest:
        raise HTTPException(410,'This link is expired or the visit has changed')
    a.response=answer;a.responded_at=now();a.token_digest=None;a.token_encrypted=None
    if answer=='left':
        v.status=e.state='COMPLETED';v.exit_at=v.completed_at=now()
        e.evidence={**(e.evidence or {}),'exit_completion':{'method':'RESIDENT_CONFIRMED','confirmed_at':v.exit_at.isoformat(),'exit_time_basis':'RESIDENT_RESPONSE'}}
        resolve_alert(db,v)
    audit(db,None,e,'RESIDENT_REPORTED_EXIT' if answer=='left' else 'RESIDENT_STILL_PRESENT',resident_id=r.id)
    db.commit();return {'message':'Visit marked as exited. Thank you.' if answer=='left' else 'Response recorded. Security has been notified.'}
