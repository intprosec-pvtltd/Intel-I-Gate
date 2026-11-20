from sqlalchemy import select
from app.models import User
from app.security import hasher


def test_email_is_required_normalized_and_password_is_verified(env):
    client=env[0]
    assert client.post('/api/auth/login',json={'username':'admin','password':'test-password-123'}).status_code==422
    assert client.post('/api/auth/login',json={'email':'not-email','password':'test-password-123'}).status_code==422
    wrong=client.post('/api/auth/login',json={'email':'admin@example.test','password':'wrong'})
    missing=client.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'})
    assert wrong.status_code==missing.status_code==401 and wrong.json()==missing.json()
    success=client.post('/api/auth/login',json={'email':'  ADMIN@EXAMPLE.TEST  ','password':'test-password-123'})
    assert success.status_code==200 and success.json()['email']=='admin@example.test'
    assert 'password' not in success.text
    assert 'HttpOnly' in success.headers['set-cookie'] and 'SameSite=strict' in success.headers['set-cookie']


def test_email_user_creation_duplicates_and_disabled_login(client,env):
    new={'email':'Guard.New@Example.test','password':'a-test-password-123','role':'guard'}
    added=client.post('/api/users',json=new);assert added.status_code==201,added.text
    assert added.json()['email']=='guard.new@example.test'
    assert client.post('/api/users',json={**new,'email':'guard.new@example.test'}).status_code==409
    ident=added.json()['id']
    assert client.post(f'/api/users/{ident}/disable').status_code==200
    assert client.post('/api/auth/login',json={'email':'guard.new@example.test','password':new['password']}).status_code==401


def test_password_whitespace_is_not_silently_changed(client):
    password='  real-password-123  '
    created=client.post('/api/users',json={'email':'space@example.test','password':password,'role':'guard'})
    assert created.status_code==201,created.text
    assert client.post('/api/auth/login',json={'email':'space@example.test','password':password.strip()}).status_code==401
    assert client.post('/api/auth/login',json={'email':'space@example.test','password':password}).status_code==200
