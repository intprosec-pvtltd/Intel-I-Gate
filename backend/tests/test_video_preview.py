import time
import numpy as np
import cv2
from app.models import Video


def add_video(sessions, status='RUNNING'):
    with sessions() as db:
        v=Video(filename='fixture.mp4',path='uploads/preview-fixture.video',size=100,duration=10,status=status)
        db.add(v);db.commit();return v.id


def test_preview_requires_login(env):
    client,_,_=env
    assert client.get('/api/videos/missing/preview').status_code==401


def test_preview_is_analyzed_jpeg_with_metadata_and_survives_completion(client,env):
    _,sessions,app=env;ident=add_video(sessions);worker=app.state.worker
    assert client.get(f'/api/videos/{ident}/preview').status_code==204
    original=np.zeros((720,1280,3),dtype=np.uint8)
    worker.publish_video_preview(ident,original,[{'track_id':7,'box':[100,100,400,650],'possible':True}],2.5)
    with sessions() as db:
        db.get(Video,ident).status='COMPLETED';db.commit()
    r=client.get(f'/api/videos/{ident}/preview')
    assert r.status_code==200 and r.headers['content-type']=='image/jpeg'
    assert r.headers['x-frame-seconds']=='2.5' and r.headers['x-preview-sequence']
    assert r.headers['cache-control']=='no-store'
    decoded=cv2.imdecode(np.frombuffer(r.content,dtype=np.uint8),cv2.IMREAD_COLOR)
    assert decoded.shape==(540,960,3) and decoded.max()>0
    assert original.max()==0  # Overlay must not mutate inference input.
    assert client.get('/api/videos/missing/preview').status_code==404
    with sessions() as db:
        db.get(Video,ident).status='EXPIRED';db.commit()
    assert client.get(f'/api/videos/{ident}/preview').status_code==410


def test_preview_cache_is_bounded_and_expires(env):
    worker=env[2].state.worker;frame=np.zeros((80,120,3),dtype=np.uint8)
    for index in range(20):worker.publish_video_preview(str(index),frame,[],float(index))
    assert len(worker.video_previews)==16
    assert worker.video_preview('0') is None
    jpeg,seconds,sequence,_=worker.video_previews['19']
    worker.video_previews['19']=(jpeg,seconds,sequence,time.monotonic()-901)
    assert worker.video_preview('19') is None
