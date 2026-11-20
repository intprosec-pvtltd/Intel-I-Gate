import time
import cv2
import numpy as np
from app.models import Camera
from app.worker import Source


def test_frame_endpoint_auth_freshness_and_camera_lookup(client,env):
    with env[1]() as db:
        camera=Camera(name='Frame camera',location='Gate',purpose='Entry Gate',rtsp_encrypted='fixture',fingerprint='fresh-frame-fixture')
        db.add(camera);db.commit();ident=camera.id
    assert client.get('/api/cameras/missing/frame').status_code==404
    assert client.get(f'/api/cameras/{ident}/frame').status_code==204
    source=Source('camera:'+ident,ident,True,{})
    ok,jpeg=cv2.imencode('.jpg',np.full((40,60,3),120,dtype=np.uint8));assert ok
    source.preview=jpeg.tobytes();source.last_frame=time.monotonic();env[2].state.worker.sources[source.key]=source
    response=client.get(f'/api/cameras/{ident}/frame')
    assert response.status_code==200 and response.content==source.preview and response.headers['cache-control']=='no-store'
    source.last_frame-=10
    assert client.get(f'/api/cameras/{ident}/frame').status_code==204
    client.post('/api/auth/logout')
    assert client.get(f'/api/cameras/{ident}/frame').status_code==401
