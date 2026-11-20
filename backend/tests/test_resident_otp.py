from datetime import timedelta
import json
import pytest
from sqlalchemy import select
from pydantic import SecretStr
from app import otp
from app.models import Resident,DeliveryOTP,Event,Visit,Audit,OTPSend,now

@pytest.fixture
def sms(env,monkeypatch):
    c=env[2].state.config;c.sms_provider='twilio';c.twilio_account_sid='AC'+'1'*32;c.twilio_auth_token=SecretStr('test-token');c.twilio_from_number='+15005550006'
    captured=[]
    monkeypatch.setattr(otp,'send_sms',lambda c,phone,code,flat:captured.append((phone,code,flat)))
    return captured

@pytest.fixture
def registered(client):
    r=client.post('/api/residents',json={'name':'Test Resident','flat':'a-101','phone':'9876543210'});assert r.status_code==201,r.text
    return r.json()

def candidate(client):return client.post('/api/events/manual',json={'reason':'Test arrival at gate'}).json()['id']

def dest(r):return {'delivery_confirmed':True,'flat':r['flat'],'resident_name':r['name'],'resident_id':r['id']}

def approve(client,e,r,sms):
    response=client.post(f'/api/events/{e}/otp/request',json={'resident_id':r['id'],'delivery_confirmed':True});assert response.status_code==200,response.text
    challenge=response.json()['challenge_id'];code=sms[-1][1]
    response=client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':challenge,'code':code});assert response.status_code==200,response.text
    return challenge

def test_resident_crud_and_normalization(client,env,registered):
    r=registered;assert r['phone']=='+919876543210' and r['flat']=='A-101'
    with env[1]() as db:assert '+919876543210' not in db.get(Resident,r['id']).phone_encrypted
    assert client.get('/api/residents?flat=a-101').json()==[r]
    edited=client.put('/api/residents/'+r['id'],json={'name':'Updated','flat':'b-102','phone':'+919876543211'});assert edited.status_code==200
    assert edited.json()['flat']=='B-102'
    assert client.delete('/api/residents/'+r['id']).status_code==200
    assert client.get('/api/residents').json()==[]
    with env[1]() as db:assert db.get(Resident,r['id']).phone_encrypted is None
    assert client.post('/api/residents',json={'name':'Updated','flat':'B-102','phone':'9876543211'}).status_code==201

@pytest.mark.parametrize('phone',['invalid','1234567890','+0123456789','98765<script>','123'])
def test_bad_phone_rejected(client,phone):
    assert client.post('/api/residents',json={'name':'Test','flat':'A1','phone':phone}).status_code==422

def test_guard_cannot_change_residents(client,registered):
    assert client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'}).status_code==200
    assert client.get('/api/residents').status_code==200
    data={'name':'Other','flat':'A1','phone':'9876543211'}
    assert client.post('/api/residents',json=data).status_code==403
    assert client.put('/api/residents/'+registered['id'],json=data).status_code==403
    assert client.delete('/api/residents/'+registered['id']).status_code==403

def test_disabled_sms_and_save_bypass_blocked(client,registered):
    e=candidate(client)
    assert client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True}).status_code==503
    assert client.post(f'/api/events/{e}/verify',json=dest(registered)).status_code==409
    assert client.post(f'/api/events/{e}/save',json=dest(registered)).status_code==409

def test_full_approval_and_idempotent_save(client,env,registered,sms):
    e=candidate(client);d=dest(registered);challenge=approve(client,e,registered,sms)
    assert client.post(f'/api/events/{e}/save',json=d).status_code==409
    assert client.post(f'/api/events/{e}/verify',json=d).status_code==200
    a=client.post(f'/api/events/{e}/save',json=d);assert a.status_code==200,a.text
    b=client.post(f'/api/events/{e}/save',json=d);assert a.json()['id']==b.json()['id']
    assert a.json()['event']['verification']['resident_approval']['method']=='SMS_OTP'
    with env[1]() as db:
        o=db.get(DeliveryOTP,challenge);assert o.state=='CONSUMED' and o.code_digest is None
        history=json.dumps([x.details for x in db.scalars(select(Audit))]);assert sms[-1][1] not in history and registered['phone'] not in history
    client.delete('/api/residents/'+registered['id'])
    assert client.get('/api/visits').json()[0]['resident_name']=='Test Resident'

@pytest.mark.parametrize('change',['expiry','resident_edit','resident_delete','other_guard','other_event'])
def test_binding_and_invalidation(client,env,registered,sms,change):
    e=candidate(client);challenge=approve(client,e,registered,sms)
    if change=='expiry':
        with env[1]() as db:db.get(DeliveryOTP,challenge).expires_at=now()-timedelta(seconds=1);db.commit()
    elif change=='resident_edit':client.put('/api/residents/'+registered['id'],json={'name':registered['name'],'flat':registered['flat'],'phone':'9876543211'})
    elif change=='resident_delete':client.delete('/api/residents/'+registered['id'])
    elif change=='other_guard':client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'})
    else:e=candidate(client)
    assert client.post(f'/api/events/{e}/verify',json=dest(registered)).status_code in (409,422)

def test_wrong_codes_lock_and_persist_attempts(client,env,registered,sms):
    e=candidate(client);r=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True}).json();wrong='000000' if sms[-1][1]!='000000' else '111111'
    for _ in range(5):assert client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':r['challenge_id'],'code':wrong}).status_code==422
    assert client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':r['challenge_id'],'code':sms[-1][1]}).status_code==409
    with env[1]() as db:o=db.get(DeliveryOTP,r['challenge_id']);assert o.attempts==5 and o.state=='LOCKED' and o.code_digest is None

def test_resend_invalidates_previous_code_and_limits_phone(client,env,registered,sms,monkeypatch):
    monkeypatch.setattr(otp.secrets,'randbelow',lambda _:123456)
    e=candidate(client);one=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True}).json()
    other=candidate(client)
    assert client.post(f'/api/events/{other}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True}).status_code==429
    with env[1]() as db:
        db.get(DeliveryOTP,one['challenge_id']).sent_at=now()-timedelta(seconds=61)
        for s in db.scalars(select(OTPSend)):s.created_at=now()-timedelta(seconds=61)
        db.commit()
    monkeypatch.setattr(otp.secrets,'randbelow',lambda _:654321)
    two=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True});assert two.status_code==200,two.text
    assert one['challenge_id']!=two.json()['challenge_id']
    assert client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':one['challenge_id'],'code':'123456'}).status_code==422
    assert client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':two.json()['challenge_id'],'code':'123456'}).status_code==422
    assert client.post(f'/api/events/{e}/otp/verify',json={'challenge_id':two.json()['challenge_id'],'code':'654321'}).status_code==200

def test_sms_failure_never_verifies_or_leaks(client,env,registered,sms,monkeypatch):
    def failed(*args):raise RuntimeError('sensitive-provider-token')
    monkeypatch.setattr(otp,'send_sms',failed);e=candidate(client)
    response=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True});assert response.status_code==502 and 'sensitive' not in response.text
    with env[1]() as db:o=db.scalar(select(DeliveryOTP));assert o.state=='FAILED' and o.code_digest is None
    assert client.post(f'/api/events/{e}/verify',json=dest(registered)).status_code==409

def test_phone_hourly_limit_shared_contacts(client,env,registered,sms):
    c=env[2].state.config;c.otp_recipient_hourly_limit=1
    e=candidate(client);approve(client,e,registered,sms)
    with env[1]() as db:
        for s in db.scalars(select(OTPSend)):s.created_at=now()-timedelta(minutes=2)
        db.commit()
    second=client.post('/api/residents',json={'name':'Other resident','flat':'B-1','phone':'9876543210'}).json()
    assert client.post(f'/api/events/{candidate(client)}/otp/request',json={'resident_id':second['id'],'delivery_confirmed':True}).status_code==429

def test_twilio_transport_uses_fixed_url_tls_and_redacts_failures(env,monkeypatch):
    c=env[2].state.config;c.sms_provider='twilio';c.twilio_account_sid='AC'+'1'*32;c.twilio_auth_token=SecretStr('test-token');c.twilio_from_number='+15005550006'
    calls=[];opts=[]
    class Client:
        def __init__(self,**kwargs):opts.append(kwargs)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append((url,kwargs));return type('Reply',(),{'status_code':201,'json':lambda self:{'sid':'SMfixture','status':'queued'}})()
    monkeypatch.setattr(otp.httpx,'Client',Client)
    otp.send_sms(c,'+919876543210','123456','A1')
    assert opts[0]['trust_env'] is False and opts[0]['follow_redirects'] is False
    assert calls[0][0]==f'https://api.twilio.com/2010-04-01/Accounts/{c.twilio_account_sid}/Messages.json'
    assert calls[0][1]['data']['To']=='+919876543210'

def test_sms_completion_rechecks_resident_after_concurrent_edit(client,env,registered,sms,monkeypatch):
    def update_during_send(*args):
        with env[1]() as db:
            r=db.get(Resident,registered['id']);r.revision+=1;db.commit()
    monkeypatch.setattr(otp,'send_sms',update_during_send)
    e=candidate(client)
    response=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True})
    assert response.status_code==409,response.text
    with env[1]() as db:o=db.scalar(select(DeliveryOTP));assert o.state=='INVALIDATED' and o.code_digest is None

def test_sms_completion_cannot_restore_cancelled_event(client,env,registered,sms,monkeypatch):
    e=candidate(client)
    def cancel_during_send(*args):
        with env[1]() as db:db.get(Event,e).state='CANCELLED';db.commit()
    monkeypatch.setattr(otp,'send_sms',cancel_during_send)
    assert client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True}).status_code==409
    with env[1]() as db:assert db.get(Event,e).state=='CANCELLED'

def test_otp_never_exposed_in_response_and_other_event_cannot_reuse_it(client,registered,sms):
    e=candidate(client);response=client.post(f'/api/events/{e}/otp/request',json={'resident_id':registered['id'],'delivery_confirmed':True})
    assert response.status_code==200 and sms[-1][1] not in response.text
    other=candidate(client)
    assert client.post(f'/api/events/{other}/otp/verify',json={'challenge_id':response.json()['challenge_id'],'code':sms[-1][1]}).status_code==422
