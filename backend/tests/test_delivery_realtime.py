import threading
import time
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi import HTTPException
from app.delivery import EvidenceWindow, associate_objects, DeliveryWorker
from app.realtime import pin_offer
from app.worker import Source
from app.models import Video, Job, Event


def test_parcel_uniform_person_and_low_scores_cannot_trigger_delivery():
    people={1:[0,0,200,400]}
    scores=[.99,.99,.99,.49]
    labels=['parcel','delivery uniform','person holding a delivery package','food delivery bag']
    boxes=[[30,100,100,200]]*4
    assert associate_objects(scores,labels,boxes,people,.5)=={1:[]}


def test_delivery_requires_specific_bag_with_unique_sensible_owner():
    box=[30,100,100,200]
    assert associate_objects([.8],['food delivery bag'],[box],{1:[0,0,200,400]},.5)[1]
    assert not any(associate_objects([.8],['food delivery bag'],[box],{1:[0,0,200,400],2:[0,0,200,400]},.5).values())
    assert not associate_objects([.99],['courier bag'],[[0,0,200,400]],{1:[0,0,200,400]},.5)[1]


def test_evidence_counts_distinct_requests_requires_span_and_expires():
    e=EvidenceWindow(3,2,15)
    for _ in range(10):e.observe(0,[{}])
    assert not e.possible(0)
    e.observe(1,[{}]);assert not e.possible(1)
    e.observe(2,[{}]);assert e.possible(2)
    assert not e.possible(18)
    e.observe(19,[{}]);e.observe(20,[{}]);e.observe(21,[])
    assert not e.possible(21)


def test_background_delivery_does_not_block_submit_and_queue_is_bounded():
    entered=threading.Event();release=threading.Event()
    def factory(c):
        def infer(frame,people):entered.set();release.wait(3);return {1:[]}
        return infer
    w=DeliveryWorker(SimpleNamespace(max_sources=2),factory)
    image=np.zeros((10,10,3),np.uint8)
    try:
        assert w.submit('one',image,{1:[0,0,1,1]},0)
        assert entered.wait(1)
        assert not w.submit('one',image,{},1)
        assert w.submit('two',image,{},0)
        assert not w.submit('three',image,{},0)
        w.forget('one');release.set()
        end=time.monotonic()+2
        while w.pending('two') and time.monotonic()<end:
            if w.take('two') is not None:break
            time.sleep(.01)
        assert not w.pending('two')
        assert w.take('one') is None
    finally:release.set();w.close()


SDP='v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\na=candidate:1 1 UDP 123 169.254.169.254 50000 typ host\r\na=candidate:2 1 UDP 123 dangerous.local 50001 typ host\r\na=candidate:3 1 UDP 123 10.0.0.2 50002 typ relay\r\n'

def test_webrtc_ice_is_pinned_to_http_caller_without_dns_or_relay():
    result=pin_offer(SDP,'127.0.0.1')
    assert '169.254.169.254' not in result and 'dangerous.local' not in result
    assert 'typ relay' not in result and result.count('127.0.0.1')==2


@pytest.mark.parametrize('sdp',[SDP.replace('recvonly','sendrecv'),SDP+'m=audio 9 RTP/AVP 0\r\n',SDP.replace('50000','80').replace('50001','80')])
def test_webrtc_rejects_sending_media_multiple_tracks_and_low_ports(sdp):
    with pytest.raises(HTTPException):pin_offer(sdp,'127.0.0.1')


def test_realtime_routes_require_auth_and_origin(env,client):
    assert client.post('/api/cameras/missing/webrtc',json={'sdp':'x'*40,'type':'offer'},headers={'origin':'https://evil.test'}).status_code==403
    assert client.post('/api/cameras/missing/webrtc',json={'sdp':'x'*40,'type':'offer'}).status_code==409
    client.post('/api/auth/logout')
    assert client.post('/api/cameras/missing/webrtc',json={'sdp':'x'*40,'type':'offer'}).status_code==401


def test_stale_overlays_clear_without_stopping_video(env):
    w=env[2].state.worker;s=Source('camera:one','one',True,{})
    s.raw=np.zeros((540,960,3),np.uint8);s.raw_at=time.monotonic()
    s.analysis={'camera_id':'one','epoch':s.epoch,'frame_at':time.monotonic()-5,'rows':[{'track_id':1}]}
    w.sources[s.key]=s
    assert w.raw_frame('one') is not None
    assert w.analysis_state()[0]['rows']==[]
    assert w.analysis_state()[0]['stale'] is True
    s.raw_at-=5
    assert w.raw_frame('one') is None


def test_reanalysis_preserves_old_events_and_uses_fresh_track_epoch(client,env,monkeypatch):
    _,sessions,app=env
    with sessions() as db:
        v=Video(filename='test.mp4',path='uploads/test.video',size=1,duration=1,status='COMPLETED');db.add(v);db.flush()
        e=Event(video_id=v.id,track_ref='old-track');db.add(e);db.commit();ident=v.id
    app.state.storage.path('uploads/test.video').write_bytes(b'fixture')
    app.state.config.ai_enabled=True
    monkeypatch.setattr(app.state.worker,'decode',lambda *a:None)
    assert client.post(f'/api/videos/{ident}/analyze',json={'test_role':'entry'}).status_code==200
    source=app.state.worker.sources['video:'+ident]
    assert source.epoch!=ident
    with sessions() as db:assert db.query(Event).filter_by(track_ref='old-track').count()==1
    source.thread.join()
    assert client.post(f'/api/videos/{ident}/cancel').status_code==200


def test_two_actual_webrtc_peers_receive_video_and_revocation_closes_them(client,env,monkeypatch):
    """Real SRTP negotiation/decoding; synthetic pixels, no model benchmark."""
    import asyncio
    import aioice.ice
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
    from app.realtime import Offer
    # The test sandbox has only loopback, excluded by aioice's normal discovery.
    monkeypatch.setattr(aioice.ice,'get_host_addresses',lambda use_ipv4,use_ipv6:['127.0.0.1'])
    _,sessions,app=env
    token=client.cookies.get('intel_session')
    for ident in ('one','two'):
        s=Source('camera:'+ident,ident,True,{})
        s.raw=np.full((540,960,3),100,np.uint8);s.raw_at=time.monotonic()
        app.state.worker.sources[s.key]=s
    request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),cookies={'intel_session':token})
    from app.security import authenticate
    user=authenticate(token,app)
    async def run():
        peers=[];tracks=[]
        try:
            for ident in ('one','two'):
                pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));peers.append(pc)
                pc.addTransceiver('video',direction='recvonly')
                @pc.on('track')
                def got(track):tracks.append(track)
                await pc.setLocalDescription(await pc.createOffer())
                answer=await app.state.preview_peers.create(ident,Offer(type='offer',sdp=pc.localDescription.sdp),request,user)
                await pc.setRemoteDescription(RTCSessionDescription(type=answer['type'],sdp=answer['sdp']))
            assert len(tracks)==2
            async with asyncio.timeout(8):
                for track in tracks:
                    frame=await track.recv();assert (frame.width,frame.height)==(960,540)
            # Revoking the auth token must close both long-lived media sessions.
            from app.models import User
            with sessions() as db:db.get(User,user.id).token_version+=1;db.commit()
            async with asyncio.timeout(5):
                while app.state.preview_peers.peers:await asyncio.sleep(.1)
            assert all(pc.connectionState in ('connected','closed') for pc in peers)
        finally:
            await app.state.preview_peers.close()
            for pc in peers:await pc.close()
    asyncio.run(run())


def test_offline_eof_waits_for_delivery_and_flushes_final_evidence(env):
    """A video cannot complete while its last DINO request is still outstanding."""
    from app import vision
    from app.worker import Manager
    _,sessions,app=env
    with sessions() as db:
        v=Video(filename='last.mp4',path='uploads/final.video',size=1,duration=1,status='RUNNING');db.add(v);db.flush();ident=v.id;db.add(Job(video_id=ident,status='RUNNING'));db.commit()
    w=app.state.worker;w.c.ai_enabled=True
    source=Source('video:'+ident,ident,False,{})
    source.eof=True;source.last_packet=(np.zeros((540,960,3),np.uint8),.8,None,source.epoch)
    source.last_rows=[{'track_id':1,'box':[0,0,100,200],'possible':False}]
    w.sources[source.key]=source
    release=threading.Event();flushed=threading.Event()
    class FakePipeline:
        delivery_worker=SimpleNamespace(state='READY')
        def __init__(self):self.waiting=True
        def poll_delivery(self,key,live):
            if self.waiting and release.is_set():
                self.waiting=False
                return [{'track_id':1,'box':[0,0,100,200],'face':None,'objects':[{'label':'food delivery bag','confidence':.8}],'possible':True,'entry':False,'exit':False}]
            return []
        def pending_delivery(self,key):return self.waiting
        def forget(self,key):flushed.set()
        def close(self):pass
    w.pipeline=FakePipeline();w.model_state='READY';w.thread.start()
    try:
        time.sleep(.15)
        with sessions() as db:assert db.get(Video,ident).status=='RUNNING'
        release.set();assert flushed.wait(2)
        with sessions() as db:
            assert db.get(Video,ident).status=='COMPLETED'
            assert db.query(Event).filter_by(video_id=ident,candidate_status='POSSIBLE_DELIVERY').count()==1
        assert w.video_preview(ident) is not None
    finally:w.close()
