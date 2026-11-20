from datetime import timedelta
import hashlib,hmac,ipaddress,secrets
from urllib.parse import urlsplit
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException,Request
from .models import User,now
hasher=PasswordHasher()
dummy=hasher.hash(secrets.token_urlsafe(32))

def password_matches(encoded,password):
    try:return hasher.verify(encoded,password)
    except VerificationError:return False
def protect(value,c):return Fernet(c.encryption_key.encode()).encrypt(value.encode()).decode()
def reveal(value,c):return Fernet(c.encryption_key.encode()).decrypt(value.encode()).decode()
def issue(user,c):
    return jwt.encode({'sub':user.id,'ver':user.token_version,'exp':now()+timedelta(hours=c.session_hours),'iat':now(),'jti':secrets.token_hex(16)},c.secret_key,algorithm='HS256')
def authenticate(token,app):
    try:claims=jwt.decode(token or '',app.state.config.secret_key,algorithms=['HS256'],options={'require':['sub','ver','exp','jti']})
    except jwt.PyJWTError:raise HTTPException(401,'Please sign in')
    with app.state.sessions() as db:
        user=db.get(User,claims['sub'])
        if not user or not user.active or user.token_version!=claims['ver']:raise HTTPException(401,'Session expired')
        return user
def current(request:Request):return authenticate(request.cookies.get('intel_session'),request.app)
def admin(request:Request):
    user=current(request)
    if user.role!='admin':raise HTTPException(403,'Administrator permission required')
    return user
def validate_camera_url(value,c,schemes=('rtsp','http','https')):
    try:
        if not isinstance(value,str) or value!=value.strip() or any(ord(x)<32 or ord(x)==127 for x in value) or chr(92) in value:raise ValueError()
        u=urlsplit(value)
        if u.scheme not in schemes or not u.hostname or u.fragment:raise ValueError()
        ip=ipaddress.ip_address(u.hostname)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified or getattr(ip,'ipv4_mapped',None):raise ValueError()
        nets=[ipaddress.ip_network(s.strip()) for s in c.camera_allow_cidrs.split(',') if s.strip()]
        default={'rtsp':554,'http':80,'https':443}[u.scheme]
        port=u.port if u.port is not None else default
        if not any(ip in net for net in nets) or port not in [int(p.strip()) for p in c.camera_ports.split(',') if p.strip()] or not 1<=port<=65535:raise ValueError()
    except (ValueError,TypeError):raise HTTPException(422,'Camera stream requires RTSP, HTTP or HTTPS, an allowlisted literal camera IP and an approved numeric port') from None
    return value

def validate_rtsp(value,c):
    # Compatibility for callers that explicitly require RTSP only.
    return validate_camera_url(value,c,schemes=('rtsp',))
def fingerprint(value,c):
    u=urlsplit(value)
    port=u.port if u.port is not None else {'rtsp':554,'http':80,'https':443}.get(u.scheme,554)
    identity=f'{u.hostname}:{port}{u.path}?{u.query}'
    if u.scheme!='rtsp':identity=u.scheme+'://'+identity
    return hmac.new(c.secret_key.encode(),identity.encode(),hashlib.sha256).hexdigest()
