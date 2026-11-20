import json,subprocess,threading,time
WIDTH,HEIGHT=960,540
def probe(path,c):
    try:
        r=subprocess.run([c.ffprobe,'-v','error','-protocol_whitelist','file,pipe','-show_format','-show_streams','-of','json',str(path)],capture_output=True,check=True,timeout=15)
        d=json.loads(r.stdout);streams=[s for s in d['streams'] if s['codec_type']=='video'];duration=float(d['format']['duration'])
        if not streams or not set(d['format']['format_name'].split(','))&{'mov','mp4','m4a','3gp','3g2','mj2','avi'} or not 0<duration<=86400:raise ValueError()
        s=streams[0]
        if not 16<=s['width']<=7680 or not 16<=s['height']<=4320:raise ValueError()
        return {'duration':duration,'width':s['width'],'height':s['height']}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):raise ValueError('Unsupported/corrupt video or FFprobe unavailable') from None
class FFmpegDecoder:
    def __init__(self,source,c,live):
        self.closed=threading.Event();self.last=time.monotonic()
        args=[c.ffmpeg,'-hide_banner','-loglevel','error','-nostdin']
        args+=['-fflags','nobuffer','-flags','low_delay','-rtsp_transport','tcp','-rw_timeout','8000000','-protocol_whitelist','rtsp,tcp'] if live else ['-protocol_whitelist','file,pipe']
        rate=max(c.inference_fps,c.preview_fps) if live else c.inference_fps
        args+=['-i',str(source),'-an','-sn','-dn','-vf',f'fps={rate},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2','-pix_fmt','bgr24','-f','rawvideo','pipe:1']
        self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=WIDTH*HEIGHT*3)
        threading.Thread(target=self._watch,daemon=True).start()
    def _watch(self):
        while not self.closed.wait(.5):
            if time.monotonic()-self.last>15:self.close();return
    def touch(self):self.last=time.monotonic()
    def read(self):
        import numpy as np
        self.touch();remaining=WIDTH*HEIGHT*3;parts=[]
        while remaining and not self.closed.is_set():
            b=self.process.stdout.read(remaining)
            if not b:return None
            parts.append(b);remaining-=len(b)
        self.touch()
        return None if remaining else np.frombuffer(b''.join(parts),np.uint8).reshape(HEIGHT,WIDTH,3).copy()
    def close(self):
        self.closed.set()
        if self.process.poll() is None:self.process.kill()
        try:self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:pass
def Decoder(source,c,live):
    if live:
        from .security import validate_camera_url
        from urllib.parse import urlsplit
        validate_camera_url(source,c)
        if urlsplit(source).scheme in ('http','https'):
            from .http_camera import HTTPMJPEGDecoder
            return HTTPMJPEGDecoder(source,c)
    return FFmpegDecoder(source,c,live)

def test_connection(url,c):
    d=Decoder(url,c,True)
    try:return d.read() is not None
    finally:d.close()
