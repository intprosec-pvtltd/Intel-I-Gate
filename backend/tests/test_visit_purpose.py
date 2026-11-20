import pytest
from datetime import datetime,timedelta,timezone
def deadline():return (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
from tests.test_resident_otp import sms, registered, candidate, approve, dest

@pytest.mark.parametrize('purpose',['Delivery','Relation','Maid/Caretaker'])
def test_purpose_saved_with_otp(client,env,registered,sms,purpose):
    e=candidate(client);approve(client,e,registered,sms)
    payload={**dest(registered),'visit_purpose':purpose,'notes':'Test visit'}
    if purpose != 'Delivery':payload.update(visitor_name='Test Visitor',visit_reason='Family visit',expected_exit_at=deadline())
    assert client.post(f'/api/events/{e}/verify',json=payload).status_code==200
    response=client.post(f'/api/events/{e}/save',json=payload)
    assert response.status_code==200,response.text
    visits=client.get('/api/visits').json()
    row=next(v for v in visits if v['event_id']==e)
    assert row['event']['verification']['visit_purpose']==purpose
    assert row['notes']==f'Visit purpose: {purpose}\nTest visit'

def test_invalid_purpose_rejected(client,registered):
    e=candidate(client)
    assert client.post(f'/api/events/{e}/verify',json={**dest(registered),'visit_purpose':'Other'}).status_code==422

def test_purpose_change_requires_reconfirmation(client,registered,sms):
    e=candidate(client);approve(client,e,registered,sms)
    payload={**dest(registered),'visit_purpose':'Relation','visitor_name':'Test Visitor','visit_reason':'Family visit','expected_exit_at':deadline()}
    assert client.post(f'/api/events/{e}/verify',json=payload).status_code==200
    assert client.post(f'/api/events/{e}/save',json={**payload,'visit_purpose':'Maid/Caretaker'}).status_code==409


@pytest.mark.parametrize('purpose',['Relation','Maid/Caretaker'])
def test_visitor_details_required(client,registered,purpose):
    e=candidate(client);base={**dest(registered),'visit_purpose':purpose}
    for fields in ({},{'visitor_name':'Visitor'},{'visit_reason':'Visit'},{'visitor_name':'  ','visit_reason':'Visit'}):
        assert client.post(f'/api/events/{e}/verify',json={**base,**fields}).status_code==422

def test_visitor_details_saved_and_change_requires_reconfirmation(client,registered,sms):
    e=candidate(client);approve(client,e,registered,sms)
    payload={**dest(registered),'visit_purpose':'Relation','visitor_name':'Ravi','visit_reason':'Family visit','expected_exit_at':deadline()}
    assert client.post(f'/api/events/{e}/verify',json=payload).status_code==200
    assert client.post(f'/api/events/{e}/save',json={**payload,'visit_reason':'Other'}).status_code==409
    response=client.post(f'/api/events/{e}/save',json=payload)
    assert response.status_code==200,response.text
    assert response.json()['event']['verification']['visitor_name']=='Ravi'
    assert response.json()['event']['verification']['visit_reason']=='Family visit'
