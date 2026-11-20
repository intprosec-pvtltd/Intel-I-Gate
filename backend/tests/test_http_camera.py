import threading
import time
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import shutil
import cv2
import numpy as np
import httpx
import pytest
from fastapi import HTTPException
from app.http_camera import HTTPMJPEGDecoder, CameraStreamError, jpeg_dimensions
from app.media import Decoder, test_connection as check_connection
from app.security import validate_camera_url, validate_rtsp, fingerprint, reveal
from app.models import Camera


URL='http://192.168.1.50:8080/video'


def config(env):
    c=env[2].state.config;c.camera_ports='554,8554,8080,443';return c


def jpeg(color=100):
    ok,encoded=cv2.imencode('.jpg',np.full((240,320,3),color,np.uint8));assert ok
    return encoded.tobytes()


class BytesStream(httpx.SyncByteStream):
    def __init__(self, chunks):self.chunks=chunks;self.closed=False
    def __iter__(self):yield from self.chunks
    def close(self):self.closed=True


def mock_camera(monkeypatch, *, status=200, content_type='multipart/x-mixed-replace; boundary=frame', chunks=None, headers=None):
    import app.http_camera as module
    calls=[];options=[];client_class=httpx.Client
    stream=BytesStream(chunks if chunks is not None else [b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg()+b'\r\n--frame--\r\n'])
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers={'Content-Type':content_type,**(headers or {})},stream=stream)
    def factory(**kwargs):
        options.append(kwargs)
        return client_class(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr(module.httpx,'Client',factory)
    return calls,options,stream


def test_http_decode_fragmented_mjpeg_two_frames_without_ffmpeg(env,monkeypatch):
    first,second=jpeg(80),jpeg(170)
    body=b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+first+b'\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n'+second+b'\r\n--frame--\r\n'
    calls,options,stream=mock_camera(monkeypatch,chunks=[body[i:i+17] for i in range(0,len(body),17)])
    monkeypatch.setattr('app.media.subprocess.Popen',lambda *a,**k:pytest.fail('HTTP must not invoke FFmpeg'))
    decoder=Decoder(URL,config(env),True)
    try:
        a,b=decoder.read(),decoder.read()
        assert a.shape==b.shape==(540,960,3)
        assert 70<a[270,480,0]<90 and 160<b[270,480,0]<180
        assert a[:,0].max()==0  # Correct letterboxing for 4:3 input.
    finally:decoder.close()
    assert stream.closed and len(calls)==1
    assert options[0]['trust_env'] is False and options[0]['follow_redirects'] is False and options[0]['verify'] is True


def test_snapshot_jpeg_and_https_dispatch_are_supported(env,monkeypatch):
    mock_camera(monkeypatch,content_type='image/jpeg',chunks=[jpeg()])
    decoder=Decoder('https://192.168.1.50/image.jpg',config(env),True)
    try:assert decoder.read().shape==(540,960,3)
    finally:decoder.close()


@pytest.mark.parametrize('status,kind,headers,expected',[
    (302,'text/html',{'Location':'http://169.254.169.254/latest/meta-data'},'redirects'),
    (200,'text/html',{},'direct stream'),
    (401,'image/jpeg',{},'authentication'),
    (403,'image/jpeg',{},'authentication'),
    (404,'image/jpeg',{},'not found'),
    (200,'image/jpeg',{'Content-Encoding':'gzip'},'Compressed'),
    (500,'image/jpeg',{},'HTTP 500'),
])
def test_http_rejects_redirects_html_bad_status_and_compression(env,monkeypatch,status,kind,headers,expected):
    calls,_,stream=mock_camera(monkeypatch,status=status,content_type=kind,headers=headers)
    with pytest.raises(CameraStreamError,match=expected):Decoder(URL,config(env),True)
    assert len(calls)==1 and stream.closed


def test_jpeg_dimensions_reject_bombs_before_image_allocation():
    bomb=b'\xff\xd8\xff\xc0\x00\x11\x08\xff\xff\xff\xff\x03'+b'\x01\x11\x00'*3+b'\xff\xd9'
    with pytest.raises(CameraStreamError,match='resolution'):jpeg_dimensions(bomb)
    assert jpeg_dimensions(jpeg())==(320,240)


def test_http_size_limit_rejects_incomplete_frame(env,monkeypatch):
    import app.http_camera as module
    monkeypatch.setattr(module,'MAX_JPEG_BYTES',100)
    mock_camera(monkeypatch,chunks=[b'\xff\xd8'+b'x'*99])
    d=Decoder(URL,config(env),True)
    try:
        with pytest.raises(CameraStreamError,match='size limit'):d.read()
    finally:d.close()


@pytest.mark.parametrize('url',[
    'http://127.0.0.1:8080/video','http://169.254.169.254:8080/video',
    'http://localhost:8080/video','http://192.168.1.51:8080/video',
    'http://192.168.1.50:22/video','http://192.168.1.50:8080t/video',
    'file:///etc/passwd','ftp://192.168.1.50:8080/video',
    'http://192.168.1.50:8080/video#fragment','http://192.168.1.50:8080/a\\b',
    'http://192.168.1.50:8080/video\r\nHeader: secret',
])
def test_http_url_security(env,url):
    with pytest.raises(HTTPException):validate_camera_url(url,config(env))


def test_rtsp_compatibility_and_fingerprints(env):
    c=config(env)
    assert validate_camera_url(URL,c)==URL
    with pytest.raises(HTTPException):validate_rtsp(URL,c)
    assert validate_rtsp('rtsp://192.168.1.50/live',c)
    assert fingerprint('rtsp://192.168.1.50/live',c)==fingerprint('rtsp://user:password@192.168.1.50:554/live',c)
    assert fingerprint('http://192.168.1.50:443/video',c)!=fingerprint('https://192.168.1.50:443/video',c)


def test_http_camera_api_encrypts_credentials_and_test_decodes_frame(client,env,monkeypatch):
    c=config(env);calls,_,_=mock_camera(monkeypatch)
    url='http://phoneuser:phoneSecret@192.168.1.50:8080/video'
    test=client.post('/api/cameras/test',json={'rtsp_url':url})
    assert test.status_code==200 and test.json()['connected'] is True
    data={'name':'Phone test','location':'Lobby','purpose':'Entry Gate','rtsp_url':url}
    response=client.post('/api/cameras',json=data)
    assert response.status_code==201
    assert 'phoneSecret' not in response.text and url not in response.text
    with env[1]() as db:
        camera=db.get(Camera,response.json()['id'])
        assert 'phoneSecret' not in camera.rtsp_encrypted
        assert reveal(camera.rtsp_encrypted,c)==url
    assert calls[0].headers.get('authorization','').startswith('Basic ')
    assert client.post('/api/cameras',json={**data,'name':'Duplicate phone'}).status_code==409


def test_http_redirect_error_does_not_echo_camera_secret(client,env,monkeypatch):
    config(env)
    calls,_,_=mock_camera(monkeypatch,status=302,headers={'Location':'http://169.254.169.254/'})
    response=client.post('/api/cameras/test',json={'rtsp_url':'http://u:phoneSecret@192.168.1.50:8080/video'})
    assert response.status_code==200 and not response.json()['connected']
    assert 'redirects' in response.json()['message']
    assert 'phoneSecret' not in response.text and '169.254' not in response.text and len(calls)==1


def test_allow_camera_script_deduplicates_and_preserves_settings(tmp_path):
    root=Path(__file__).resolve().parents[2]
    (tmp_path/'scripts').mkdir();(tmp_path/'backend').mkdir()
    shutil.copy2(root/'scripts/allow_camera.py',tmp_path/'scripts/allow_camera.py')
    path=tmp_path/'backend/.env'
    path.write_text('SECRET_KEY=private-fixture\nCAMERA_ALLOW_CIDRS=\nCAMERA_PORTS=554,8554\nCAMERA_ALLOW_CIDRS=192.168.1.50/32\nCAMERA_PORTS=554,8554\n')
    result=subprocess.run([sys.executable,str(tmp_path/'scripts/allow_camera.py'),'--ip','192.168.0.3','--port','8080'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    text=path.read_text()
    assert text.count('CAMERA_ALLOW_CIDRS=')==text.count('CAMERA_PORTS=')==1
    assert '192.168.0.3/32' in text and '192.168.1.50/32' in text
    assert 'SECRET_KEY=private-fixture' in text and 'private-fixture' not in result.stdout
    assert 'CAMERA_PORTS=554,8554,8080' in text


def test_mjpeg_handles_embedded_exif_thumbnail(env,monkeypatch):
    thumbnail=jpeg(30)
    app1=b'Exif\x00\x00'+thumbnail
    outer=jpeg(180)
    with_exif=outer[:2]+b'\xff\xe1'+(len(app1)+2).to_bytes(2,'big')+app1+outer[2:]
    mock_camera(monkeypatch,chunks=[with_exif[i:i+57] for i in range(0,len(with_exif),57)])
    d=Decoder(URL,config(env),True)
    try:assert d.read()[270,480,0]>160
    finally:d.close()


def test_real_http_mjpeg_socket_reaches_live_worker(client,env,monkeypatch):
    """Local fixture transport redirects only test traffic, never production input."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    config(env)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            assert self.path=='/video'
            self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame');self.end_headers()
            try:
                for index in range(20):
                    image=jpeg(80+index)
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(image)).encode()+b'\r\n\r\n'+image+b'\r\n');self.wfile.flush();time.sleep(.03)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original=httpx.Client
    class FixtureTransport(httpx.HTTPTransport):
        def handle_request(self,request):
            assert request.url.host=='192.168.1.50' and request.url.port==8080
            local=httpx.Request(request.method,request.url.copy_with(host='127.0.0.1',port=server.server_port),headers=request.headers)
            return super().handle_request(local)
    monkeypatch.setattr('app.http_camera.httpx.Client',lambda **kwargs:original(transport=FixtureTransport(),**kwargs))
    ident=None
    try:
        response=client.post('/api/cameras/test',json={'rtsp_url':URL})
        assert response.json()['connected'] is True
        response=client.post('/api/cameras',json={'name':'Real HTTP fixture','location':'Lab','purpose':'Entry Gate','rtsp_url':URL})
        assert response.status_code==201;ident=response.json()['id']
        assert client.post(f'/api/cameras/{ident}/start').status_code==200
        end=time.monotonic()+3
        while env[2].state.worker.raw_frame(ident) is None and time.monotonic()<end:time.sleep(.02)
        packet=env[2].state.worker.raw_frame(ident)
        assert packet is not None and packet[0].shape==(540,960,3)
    finally:
        if ident:env[2].state.worker.remove(ident)
        server.shutdown();server.server_close();thread.join(timeout=2)
