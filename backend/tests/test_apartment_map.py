from tests.test_resident_otp import sms, registered, candidate, approve, dest

def test_map_positions_access_and_validation(client,registered):
    assert client.put('/api/apartment-map/point',json={'flat':'missing','x':0.5,'y':0.5}).status_code==400
    assert client.put('/api/apartment-map/point',json={'flat':registered['flat'],'x':2,'y':0.5}).status_code==422
    point={'flat':registered['flat'],'x':0.5,'y':0.7}
    assert client.put('/api/apartment-map/point',json=point).status_code==200
    assert client.get('/api/apartment-map').json()['points']==[point]
    assert client.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'}).status_code==200
    assert client.get('/api/apartment-map').status_code==200
    assert client.put('/api/apartment-map/point',json=point).status_code==403
    assert client.post('/api/apartment-map/remove',json={'flat':registered['flat']}).status_code==403

def test_map_shows_saved_active_visit_until_completed(client,registered,sms):
    point={'flat':registered['flat'],'x':0.5,'y':0.5}
    assert client.put('/api/apartment-map/point',json=point).status_code==200
    e=candidate(client);approve(client,e,registered,sms)
    data={**dest(registered),'visit_purpose':'Relation','visitor_name':'Ravi','visit_reason':'Family visit','expected_exit_at':(__import__('datetime').datetime.now(__import__('datetime').timezone.utc)+__import__('datetime').timedelta(hours=2)).isoformat()}
    assert client.post(f'/api/events/{e}/verify',json=data).status_code==200
    assert client.post(f'/api/events/{e}/save',json=data).status_code==200
    visits=client.get('/api/apartment-map').json()['visits']
    assert len(visits)==1 and visits[0]['visitor_name']=='Ravi' and visits[0]['visit_reason']=='Family visit'
    assert client.post(f'/api/events/{e}/complete',json={'confirmed':True,'reason':'Visitor has left'}).status_code==200
    assert client.get('/api/apartment-map').json()['visits']==[]
