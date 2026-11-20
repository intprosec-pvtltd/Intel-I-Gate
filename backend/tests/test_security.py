import pytest
from fastapi import HTTPException
from app.security import validate_rtsp,reveal
from app.vision import crossing
def test_auth_required(env):
    for p in ['/api/cameras','/api/events','/api/visits','/api/system/models','/api/snapshots/unknown']:
        assert env[0].get(p).status_code==401
def test_csrf(client):
    assert client.post('/api/events/manual',json={'reason':'test fixture'},headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/events/manual',json={'reason':'test fixture'},headers={'X-Intel-Request':''}).status_code==403
def test_logout_revokes_token(client):
    token=client.cookies.get('intel_session');client.post('/api/auth/logout');client.cookies.set('intel_session',token)
    assert client.get('/api/auth/me').status_code==401
def test_guard_permissions(env):
    c=env[0];c.post('/api/auth/login',json={'email':'guard@example.test','password':'test-password-123'})
    assert c.get('/api/users').status_code==403
    assert c.post('/api/cameras',json={'name':'Gate','location':'Lobby','purpose':'Entry Gate','rtsp_url':'rtsp://192.168.1.50/live'}).status_code==403
    assert c.post('/api/events/manual',json={'reason':'test fixture'}).status_code==201
@pytest.mark.parametrize('url',['http://192.168.1.50/x','rtsp://127.0.0.1/x','rtsp://169.254.169.254/x','rtsp://localhost/x','rtsp://192.168.1.51/x','rtsp://192.168.1.50:22/x','file:///etc/passwd'])
def test_ssrf(env,url):
    with pytest.raises(HTTPException):validate_rtsp(url,env[2].state.config)
def test_credentials_encrypted_and_redacted(client,env):
    url='rtsp://cameraUser:cameraSecret@192.168.1.50/live';data={'name':'Gate','location':'Lobby','purpose':'Entry Gate','rtsp_url':url}
    r=client.post('/api/cameras',json=data);assert r.status_code==201,r.text;assert 'cameraSecret' not in r.text and 'rtsp' not in r.text
    from app.models import Camera
    with env[1]() as db:
        c=db.get(Camera,r.json()['id']);assert 'cameraSecret' not in c.rtsp_encrypted;assert reveal(c.rtsp_encrypted,env[2].state.config)==url
    assert client.post('/api/cameras',json={**data,'name':'Duplicate stream'}).status_code==409
def test_validation_does_not_echo_secrets(client):
    r=client.post('/api/auth/login',json={'email':'admin@example.test','password':'x'*201});assert r.status_code==422 and 'x'*50 not in r.text
def test_traversal_blocked(env):
    with pytest.raises(ValueError):env[2].state.storage.path('../../escape')
def test_corrupt_video(client):
    r=client.post('/api/videos/upload',files={'file':('fake.mp4',b'not video','video/mp4')});assert r.status_code==422,r.text
    assert client.get('/api/videos').json()==[]
def test_empty_dashboard(client):
    assert client.get('/api/dashboard/summary').json()=={'cameras':0,'connected':0,'pending':0,'active_visits':0,'saved_visits':0,'completed':0}
def test_crossing_direction_and_finite_segment():
    line=[.2,.5,.8,.5];assert crossing((.5,.4),(.5,.6),line)
    assert not crossing((.5,.6),(.5,.4),line)
    assert not crossing((.9,.4),(.9,.6),line)
    assert not crossing(None,(.5,.6),line)
def test_websocket_origin(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/events',headers={'origin':'https://evil.test'}):pass
