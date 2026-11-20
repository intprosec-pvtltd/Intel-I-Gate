"""Bounded HTTP(S) JPEG/MJPEG input. Never follows redirects or opens playlists."""
import threading
import time
import httpx

MAX_JPEG_BYTES = 8 * 1024 * 1024
MAX_HEADER_BYTES = 256 * 1024
MAX_PIXELS = 4096 * 2160


class CameraStreamError(RuntimeError):
    """Only sanitized, credential-free messages may be shown to a guard."""
    def __init__(self, message):
        self.public_message = message
        super().__init__(message)


def jpeg_dimensions(data):
    """Check dimensions before allocating a decoded image (SOF0/1/2 JPEG)."""
    if not data.startswith(b'\xff\xd8'):
        raise CameraStreamError('Camera returned an invalid JPEG frame')
    offset = 2
    while offset < min(len(data), MAX_HEADER_BYTES):
        if data[offset] != 0xff:
            raise CameraStreamError('Camera returned an invalid JPEG header')
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xd8, 0x01) or 0xd0 <= marker <= 0xd7:
            continue
        if marker in (0xda, 0xd9) or offset+2 > len(data):
            break
        length = int.from_bytes(data[offset:offset+2], 'big')
        if length < 2 or offset+length > len(data):
            break
        if marker in (0xc0, 0xc1, 0xc2):
            if length < 8:
                break
            height = int.from_bytes(data[offset+3:offset+5], 'big')
            width = int.from_bytes(data[offset+5:offset+7], 'big')
            if not 16 <= width <= 4096 or not 16 <= height <= 4096 or width*height > MAX_PIXELS:
                raise CameraStreamError('Camera JPEG resolution exceeds the supported limit; reduce the phone stream resolution')
            return width, height
        offset += length
    raise CameraStreamError('Camera JPEG header is unsupported or incomplete')


def jpeg_end(data):
    """Skip length-delimited JPEG metadata, including embedded EXIF thumbnails."""
    offset=2
    while offset<min(len(data),MAX_HEADER_BYTES):
        if data[offset]!=0xff:
            raise CameraStreamError('Camera returned an invalid JPEG header')
        while offset<len(data) and data[offset]==0xff:offset+=1
        if offset>=len(data):return None
        marker=data[offset];offset+=1
        if marker in (0xd8,0x01) or 0xd0<=marker<=0xd7:continue
        if marker==0xd9:return offset
        if offset+2>len(data):return None
        length=int.from_bytes(data[offset:offset+2],'big')
        if length<2:raise CameraStreamError('Camera returned an invalid JPEG header')
        if offset+length>len(data):return None
        if marker==0xda:
            end=data.find(b'\xff\xd9',offset+length)
            return end+2 if end>=0 else None
        offset+=length
    if len(data)>=MAX_HEADER_BYTES:
        raise CameraStreamError('Camera JPEG metadata exceeds the size limit')
    return None


class HTTPMJPEGDecoder:
    def __init__(self, source, config):
        from .security import validate_camera_url
        validate_camera_url(source, config, schemes=('http', 'https'))
        self.closed = threading.Event()
        self.last = time.monotonic()
        self.buffer = bytearray()
        self.client = httpx.Client(
            timeout=httpx.Timeout(connect=5, read=8, write=5, pool=5),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            follow_redirects=False, trust_env=False, verify=True,
        )
        self.response = None
        try:
            request = self.client.build_request('GET', source, headers={
                'Accept': 'multipart/x-mixed-replace,image/jpeg',
                'Accept-Encoding': 'identity',
                'User-Agent': 'INTEL-I-Mini-Camera/1.0',
            })
            self.response = self.client.send(request, stream=True)
            status = self.response.status_code
            if 300 <= status < 400:
                raise CameraStreamError('Camera redirects are blocked; enter the direct MJPEG stream URL')
            if status in (401, 403):
                raise CameraStreamError('Camera authentication failed; check the credentials in the stream URL')
            if status == 404:
                raise CameraStreamError('Camera stream path was not found; copy the direct MJPEG URL from the phone app')
            if status != 200:
                raise CameraStreamError(f'Camera stream returned HTTP {status}')
            content_type = self.response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
            if content_type not in ('multipart/x-mixed-replace', 'image/jpeg', 'image/jpg'):
                raise CameraStreamError('This URL does not return JPEG/MJPEG video; use the direct stream URL, not the app web page')
            if self.response.headers.get('content-encoding', 'identity').lower() not in ('identity', ''):
                raise CameraStreamError('Compressed HTTP camera responses are not supported')
            # Raw chunks avoid decompression and do not wait to fill a fixed chunk size.
            self.chunks = self.response.iter_raw()
        except httpx.HTTPError:
            self.close()
            raise CameraStreamError('Cannot open HTTP camera stream; check its address, port, network and HTTPS certificate') from None
        except BaseException:
            self.close()
            raise
        threading.Thread(target=self._watch, daemon=True, name='intel-http-camera-watch').start()

    def _watch(self):
        while not self.closed.wait(.5):
            if time.monotonic()-self.last > 15:
                self.close()
                return

    def touch(self):
        self.last = time.monotonic()

    def read(self):
        from .media import WIDTH, HEIGHT
        import cv2
        import numpy as np
        self.touch()
        deadline = time.monotonic()+15
        junk = 0
        while not self.closed.is_set():
            if time.monotonic() > deadline:
                raise CameraStreamError('No complete camera frame received in time')
            start = self.buffer.find(b'\xff\xd8')
            if start >= 0:
                if start:
                    del self.buffer[:start]
                end = jpeg_end(self.buffer)
                if end is not None:
                    jpeg = bytes(self.buffer[:end])
                    del self.buffer[:end]
                    if len(jpeg) > MAX_JPEG_BYTES:
                        raise CameraStreamError('Camera JPEG frame exceeds the size limit')
                    width, height = jpeg_dimensions(jpeg)
                    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if image is None or image.shape[:2] != (height, width):
                        raise CameraStreamError('Cannot decode camera JPEG frame')
                    scale = min(WIDTH/width, HEIGHT/height)
                    size = (max(1, round(width*scale)), max(1, round(height*scale)))
                    image = cv2.resize(image, size)
                    x, y = (WIDTH-size[0])//2, (HEIGHT-size[1])//2
                    output = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
                    output[y:y+size[1], x:x+size[0]] = image
                    self.touch()
                    return output
                if len(self.buffer) > MAX_JPEG_BYTES:
                    raise CameraStreamError('Camera JPEG frame exceeds the size limit')
            else:
                junk += max(0, len(self.buffer)-1)
                # Preserve a split SOI marker, discard bounded multipart headers.
                self.buffer[:] = self.buffer[-1:]
                if junk > MAX_HEADER_BYTES:
                    raise CameraStreamError('Camera response contains no JPEG frames')
            try:
                chunk = next(self.chunks)
            except StopIteration:
                return None
            except httpx.HTTPError:
                if self.closed.is_set():return None
                raise CameraStreamError('HTTP camera connection was interrupted or timed out') from None
            if len(chunk) > MAX_JPEG_BYTES:
                raise CameraStreamError('Camera network chunk exceeds the size limit')
            self.buffer.extend(chunk)
        return None

    def close(self):
        self.closed.set()
        try:
            if self.response is not None:self.response.close()
        finally:
            self.client.close()
