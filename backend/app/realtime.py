"""Authenticated LAN WebRTC preview, independent of model inference.

No RTSP URL or camera credential crosses the browser boundary. ICE destinations
are pinned to the authenticated HTTP caller, never taken from untrusted SDP.
"""
import asyncio
import ipaddress
import time
from fractions import Fraction
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from .security import current, authenticate

router = APIRouter(prefix='/api')


class Offer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str = Field(pattern='^offer$')
    sdp: str = Field(min_length=30, max_length=32768)


def pin_offer(sdp, host):
    """Only one receive-only video transport; only UDP host ICE to caller IP."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(400, 'Direct client address required') from None
    networks=('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','::1/128','fc00::/7')
    if not any(address in ipaddress.ip_network(cidr) for cidr in networks):
        raise HTTPException(400,'Local or private LAN preview clients only')
    lines = sdp.replace('\r\n', '\n').splitlines()
    media = [line for line in lines if line.startswith('m=')]
    if len(media) != 1 or not media[0].startswith('m=video ') or 'a=recvonly' not in lines:
        raise HTTPException(422, 'Offer must contain one receive-only video track')
    if any(line in ('a=sendrecv','a=sendonly') or line.startswith('a=remote-candidates:') for line in lines):
        raise HTTPException(422, 'Sending media is not allowed')
    safe = []
    candidates = 0
    for line in lines:
        if line.startswith('a=candidate:'):
            parts = line.split()
            if len(parts) < 8 or parts[2].lower() != 'udp' or parts[6] != 'typ' or parts[7] != 'host':
                continue
            try:
                port = int(parts[5]);component = int(parts[1])
            except ValueError:
                raise HTTPException(422, 'Invalid ICE candidate') from None
            if not 32768 <= port <= 65535 or component != 1:
                continue
            # Browser mDNS candidates are pinned too; no DNS resolution or STUN.
            parts[4] = str(address)
            line = ' '.join(parts[:8])
            candidates += 1
            if candidates > 8:
                raise HTTPException(422, 'Too many ICE candidates')
        elif line.startswith('c='):
            line = f'c=IN IP{address.version} {address}'
        elif line.startswith(('a=rtcp:', 'a=ssrc:', 'a=ssrc-group:')):
            continue
        safe.append(line)
    if not candidates:
        raise HTTPException(422, 'No usable ICE host candidate; use MJPEG fallback')
    return '\r\n'.join(safe)+'\r\n'


class PreviewPeers:
    def __init__(self, app):
        self.app = app
        self.peers = {}
        self.reserved = 0

    async def close_one(self, ident):
        peer = self.peers.pop(ident, None)
        if peer:
            peer['task'].cancel()
            await peer['pc'].close()

    async def close(self):
        for ident in list(self.peers):
            await self.close_one(ident)

    async def create(self, camera_id, offer, request, user):
        try:
            from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, VideoStreamTrack
            from aiortc.mediastreams import MediaStreamError
            from av import VideoFrame
        except ImportError:
            raise HTTPException(503, 'WebRTC dependency missing; install requirements-realtime.txt or use MJPEG') from None
        worker = self.app.state.worker
        initial = worker.raw_frame(camera_id)
        if initial is None:
            raise HTTPException(409, 'Start the camera and wait for its first live frame')
        if len(self.peers)+self.reserved >= self.app.state.config.max_preview_peers:
            raise HTTPException(429, 'Preview capacity reached; close another live view')
        safe_sdp = pin_offer(offer.sdp, request.client.host if request.client else '')
        self.reserved += 1
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        ident = uuid4().hex
        epoch = initial[2]
        token = request.cookies.get('intel_session')
        fps = self.app.state.config.preview_fps

        class CameraTrack(VideoStreamTrack):
            def __init__(self):
                super().__init__()
                self.started = time.monotonic()
                self.next_at = self.started
                self.pts = -1

            async def recv(self):
                await asyncio.sleep(max(0, self.next_at-time.monotonic()))
                self.next_at = max(self.next_at+1/fps, time.monotonic())
                packet = worker.raw_frame(camera_id)
                if packet is None or packet[2] != epoch:
                    self.stop()
                    raise MediaStreamError
                frame = VideoFrame.from_ndarray(packet[0], format='bgr24')
                self.pts = max(self.pts+1, int((time.monotonic()-self.started)*90000))
                frame.pts, frame.time_base = self.pts, Fraction(1, 90000)
                return frame

        async def lifetime():
            started = time.monotonic()
            try:
                while True:
                    await asyncio.sleep(2)
                    await asyncio.to_thread(authenticate, token, self.app)
                    packet = worker.raw_frame(camera_id)
                    if packet is None or packet[2] != epoch or pc.connectionState in ('failed','closed'):
                        break
                    if time.monotonic()-started > 20 and pc.connectionState != 'connected':
                        break
            except (Exception, asyncio.CancelledError):
                pass
            finally:
                entry = self.peers.pop(ident, None)
                if entry:
                    await pc.close()

        try:
            async with asyncio.timeout(12):
                await pc.setRemoteDescription(RTCSessionDescription(sdp=safe_sdp, type='offer'))
                pc.addTrack(CameraTrack())
                await pc.setLocalDescription(await pc.createAnswer())
            self.peers[ident] = {'pc':pc, 'user_id':user.id, 'task':asyncio.create_task(lifetime())}
            return {'id':ident, 'type':pc.localDescription.type, 'sdp':pc.localDescription.sdp}
        except BaseException as exc:
            await pc.close()
            if isinstance(exc,asyncio.CancelledError):raise
            raise HTTPException(422, 'Preview negotiation failed; retry or use MJPEG') from None
        finally:
            self.reserved -= 1


@router.post('/cameras/{ident}/webrtc')
async def offer(ident: str, data: Offer, request: Request, user=Depends(current)):
    # camera id only; no caller-supplied RTSP source or destination URL.
    return await request.app.state.preview_peers.create(ident, data, request, user)


@router.delete('/preview-sessions/{ident}')
async def close(ident: str, request: Request, user=Depends(current)):
    manager = request.app.state.preview_peers
    peer = manager.peers.get(ident)
    if peer and peer['user_id'] != user.id:
        raise HTTPException(403, 'Preview belongs to another user')
    await manager.close_one(ident)
    return {'ok':True}
