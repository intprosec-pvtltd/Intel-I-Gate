"""Resident approval codes: hashed, expiring, event/guard/destination bound."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta, timezone
from uuid import uuid4
import httpx
from fastapi import HTTPException
from sqlalchemy import select,func,text
from .models import DeliveryOTP,OTPSend,Resident,Event,now
from .security import reveal
from .events import audit,lock,EDITABLE


def digest(c,*parts):
    value=json.dumps(parts,separators=(',',':'),ensure_ascii=True).encode()
    return hmac.new(c.secret_key.encode(),value,hashlib.sha256).hexdigest()


def utc(value):return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def destination(c,r):return digest(c,'resident',r.id,r.revision,r.name,r.flat,r.phone_encrypted,r.active)


def configured(c):
    return bool(c.sms_provider=='twilio' and re.fullmatch(r'AC[0-9a-fA-F]{32}',c.twilio_account_sid)
        and c.twilio_auth_token.get_secret_value()
        and (re.fullmatch(r'MG[0-9a-fA-F]{32}',c.twilio_messaging_service_sid) if c.twilio_messaging_service_sid
             else re.fullmatch(r'\+[1-9][0-9]{7,14}',c.twilio_from_number)))


def send_sms(c,phone,code,flat):
    """Fixed TLS endpoint; no redirect/proxy or credential-bearing error output."""
    return send_message(c,phone,f'INTEL-I GATE: Visit approval for flat {flat}. Code {code}. Valid for {c.otp_expiry_seconds//60} minutes. Share only with your security guard if you expect this visit.')

def send_message(c,phone,message):
    if not configured(c):raise HTTPException(503,'SMS is not configured')
    body={'To':phone,'Body':message}
    if c.twilio_messaging_service_sid:body['MessagingServiceSid']=c.twilio_messaging_service_sid
    else:body['From']=c.twilio_from_number
    try:
        with httpx.Client(timeout=httpx.Timeout(10,connect=5),trust_env=False,follow_redirects=False) as client:
            response=client.post(f'https://api.twilio.com/2010-04-01/Accounts/{c.twilio_account_sid}/Messages.json',data=body,auth=(c.twilio_account_sid,c.twilio_auth_token.get_secret_value()))
            if response.status_code!=201:raise HTTPException(502,'SMS provider did not accept the message. Check provider configuration before resending.')
            result=response.json()
            if result.get('status') in ('failed','undelivered') or not result.get('sid'):raise HTTPException(502,'SMS provider did not accept the message.')
    except (httpx.HTTPError,ValueError):raise HTTPException(502,'SMS submission could not be confirmed. Wait before resending.') from None


def resident(db,ident):
    r=db.scalar(select(Resident).where(Resident.id==ident).with_for_update().execution_options(populate_existing=True))
    if not r or not r.active:raise HTTPException(422,'Select an active registered resident')
    if not r.phone_encrypted:raise HTTPException(422,'This resident needs a phone number. Ask the administrator to update the directory.')
    return r


def challenge(db,e):return db.scalar(select(DeliveryOTP).where(DeliveryOTP.event_id==e.id).with_for_update().execution_options(populate_existing=True))


def invalidate(db,e):
    o=challenge(db,e)
    if o:o.state='INVALIDATED';o.code_digest=None;o.verified_at=None


def request_code(db,event_id,data,user,c,sender=send_sms):
    if not configured(c):raise HTTPException(503,'SMS is not configured. Ask the administrator to configure the SMS provider.')
    e=lock(db,event_id)
    if e.state not in EDITABLE:raise HTTPException(409,'This event cannot request approval')
    # Serialize SMS reservations across app processes, including shared phone numbers.
    if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(701924113)'))
    r=resident(db,data.resident_id);phone=reveal(r.phone_encrypted,c);when=now();recipient=digest(c,'phone',phone)
    recent=list(db.scalars(select(OTPSend).where(OTPSend.created_at>when-timedelta(hours=1),OTPSend.recipient_digest==recipient)))
    if recent and (when-utc(max(x.created_at for x in recent))).total_seconds()<c.otp_resend_seconds:
        raise HTTPException(429,f'Wait {c.otp_resend_seconds} seconds between SMS requests to this number')
    count=db.scalar(select(func.count()).select_from(OTPSend).where(OTPSend.actor_id==user.id,OTPSend.created_at>when-timedelta(hours=1)))
    if len(recent)>=c.otp_recipient_hourly_limit or count>=c.otp_guard_hourly_limit:raise HTTPException(429,'Hourly SMS limit reached. Try later.')
    o=challenge(db,e)
    if o and (when-utc(o.sent_at)).total_seconds()<c.otp_resend_seconds:raise HTTPException(429,'Wait before requesting another code for this event')
    ident=str(uuid4());code=f'{secrets.randbelow(1000000):06d}'
    if o is None:o=DeliveryOTP(event_id=e.id);db.add(o)
    o.id=ident;o.created_at=when;o.resident_id=r.id;o.requested_by=user.id;o.destination_digest=destination(c,r)
    o.code_digest=digest(c,'otp',ident,code);o.expires_at=when+timedelta(seconds=c.otp_expiry_seconds)
    o.sent_at=when;o.attempts=0;o.verified_at=None;o.consumed_at=None;o.state='PENDING'
    e.verification=None;e.verified_by=None;e.state='PENDING_VERIFICATION'
    e.candidate_status='NEEDS_REVIEW'
    db.add(OTPSend(recipient_digest=recipient,actor_id=user.id))
    audit(db,user,e,'OTP_REQUESTED',resident_id=r.id,challenge_id=ident)
    # Reservation survives timeout/crash, so retries cannot flood the recipient.
    flat=r.flat;db.commit()
    try:sender(c,phone,code,flat)
    except Exception:
        e=lock(db,event_id);o=challenge(db,e)
        if o and o.id==ident:o.state='FAILED';o.code_digest=None;audit(db,user,e,'OTP_SEND_FAILED',challenge_id=ident)
        db.commit()
        raise HTTPException(502,'SMS submission failed or could not be confirmed. Wait before resending.') from None
    e=lock(db,event_id);o=challenge(db,e);r=resident(db,data.resident_id)
    if not o or o.id!=ident or o.state!='PENDING' or e.state not in EDITABLE or o.destination_digest!=destination(c,r):
        if o and o.id==ident:o.state='INVALIDATED';o.code_digest=None
        db.commit();raise HTTPException(409,'Destination changed. Request a new code.')
    o.state='SENT';audit(db,user,e,'OTP_SUBMITTED',resident_id=r.id,challenge_id=ident);db.commit()
    return {'challenge_id':ident,'state':'SENT','expires_at':o.expires_at,'resend_after_seconds':c.otp_resend_seconds,'phone_masked':'••••••'+phone[-4:],'message':'SMS provider accepted the request. Ask the resident for the code once it arrives.'}


def check_code(db,event_id,data,user,c):
    e=lock(db,event_id);o=challenge(db,e)
    if e.state not in EDITABLE:raise HTTPException(409,'This event cannot be verified')
    if not o or o.id!=data.challenge_id or o.requested_by!=user.id:raise HTTPException(422,'Code request does not match this event and guard')
    r=resident(db,o.resident_id)
    if o.destination_digest!=destination(c,r):raise HTTPException(409,'Resident details changed. Request a new code.')
    if o.state not in ('SENT','VERIFIED') or o.consumed_at or utc(o.expires_at)<=now():raise HTTPException(409,'Code expired or unavailable. Request a new code.')
    if o.state=='VERIFIED':return {'verified':True,'resident_id':r.id,'verified_at':o.verified_at,'expires_at':o.expires_at}
    if o.attempts>=c.otp_max_attempts:raise HTTPException(429,'Too many incorrect codes. Request a new code after the cooldown.')
    o.attempts+=1
    if not o.code_digest or not hmac.compare_digest(o.code_digest,digest(c,'otp',o.id,data.code)):
        if o.attempts>=c.otp_max_attempts:o.state='LOCKED';o.code_digest=None
        audit(db,user,e,'OTP_INCORRECT',challenge_id=o.id,attempt=o.attempts);db.commit()
        raise HTTPException(422,'Incorrect code')
    o.state='VERIFIED';o.verified_at=now();o.code_digest=None
    audit(db,user,e,'OTP_VERIFIED',challenge_id=o.id,resident_id=r.id);db.commit()
    return {'verified':True,'resident_id':r.id,'verified_at':o.verified_at,'expires_at':o.expires_at}


def require_verified(db,e,data,user,c):
    if not data.resident_id:raise HTTPException(422,'Select a registered resident and verify their OTP')
    r=resident(db,data.resident_id);o=challenge(db,e)
    if r.name!=data.resident_name or r.flat!=data.flat:raise HTTPException(422,'Resident and flat do not match')
    if (not o or o.state!='VERIFIED' or o.requested_by!=user.id or o.resident_id!=r.id
            or o.destination_digest!=destination(c,r) or o.consumed_at or utc(o.expires_at)<=now()):
        raise HTTPException(409,'Resident OTP approval is required or has expired. Request and verify a new code.')
    return o


def consume(db,e):
    o=challenge(db,e);o.state='CONSUMED';o.consumed_at=now();o.code_digest=None
