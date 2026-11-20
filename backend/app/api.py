import asyncio,os,time,shutil
from datetime import datetime,timedelta
from uuid import uuid4
from fastapi import APIRouter,Depends,Request,Response,HTTPException,UploadFile,File,Query
from fastapi.responses import FileResponse,StreamingResponse
from sqlalchemy import select,func,or_
from . import schemas as S,events as service,otp
from .models import User,Camera,Resident,Video,Job,Event,Visit,Snapshot,Detection,FaceProfile,ExitObservation,Audit,ApartmentMapPoint,now
from .security import current,admin,hasher,password_matches,dummy,issue,authenticate,protect,reveal,validate_camera_url,fingerprint
from .media import test_connection,probe
from .http_camera import CameraStreamError
from .manual_capture import captures
from .visit_timing import visit_timing
from pydantic import BaseModel, Field, ConfigDict, model_validator
router=APIRouter(prefix='/api')
def session(request:Request):
    with request.app.state.sessions() as db:yield db
def get(db,model,ident):
    row=db.get(model,ident)
    if row is None or (model is Video and row.status=='DELETED'):raise HTTPException(404,'Record not found')
    return row
def camera_json(c):return {k:getattr(c,k) for k in ('id','name','location','purpose','enabled','status','error','zones')}
def event_json(e,db):
    video=db.get(Video,e.video_id) if e.video_id else None
    camera=db.get(Camera,e.camera_id) if e.camera_id else None;snap=db.get(Snapshot,e.snapshot_id) if e.snapshot_id else None
    return {**{k:getattr(e,k) for k in ('id','camera_id','video_id','track_ref','state','candidate_status','evidence','created_at','frame_seconds','captured_at','verification')},'visit_timing':visit_timing(db,e),'test_role':video.test_role if video else None,'camera_name':camera.name if camera else ('Uploaded video' if e.video_id else 'Manual event'),'snapshot_id':snap.id if snap and not snap.deleted else None,'snapshot_framing':snap.metrics.get('framing','legacy') if snap and not snap.deleted else None,'face_reason':e.evidence.get('face_reason','FACE_NOT_DETECTED'),'face_status':'CAPTURED' if snap and not snap.deleted else 'No Suitable Face Captured — Guard Review Required'}
def visit_json(v,db):return {**{k:getattr(v,k) for k in ('id','event_id','resident_name','flat','guard_id','company','notes','entry_at','exit_at','status','historical','created_at','expected_exit_at','completed_at')},'exit_method':(db.get(Event,v.event_id).evidence or {}).get('exit_completion',{}).get('method'),'event':event_json(db.get(Event,v.event_id),db)}

@router.post('/auth/login')
def login(data:S.Login,request:Request,response:Response,db=Depends(session)):
    key=(request.client.host if request.client else '',data.email);attempts=request.app.state.attempts;t=time.monotonic()
    if len(attempts)>5000:attempts.clear()
    recent=attempts[key]
    while recent and t-recent[0]>300:recent.popleft()
    if len(recent)>=10:raise HTTPException(429,'Too many attempts; retry in five minutes')
    recent.append(t);u=db.scalar(select(User).where(User.email==data.email));valid=password_matches(u.password_hash if u else dummy,data.password)
    if not u or not valid or not u.active:raise HTTPException(401,'Invalid credentials')
    attempts.pop(key,None);c=request.app.state.config
    response.set_cookie('intel_session',issue(u,c),httponly=True,secure=c.cookie_secure,samesite='strict',max_age=c.session_hours*3600,path='/')
    return {'id':u.id,'username':u.username,'email':u.email,'role':u.role,'apartment_name':u.apartment_name}
@router.get('/auth/me')
def me(u=Depends(current)):return {'id':u.id,'username':u.username,'email':u.email,'role':u.role,'apartment_name':u.apartment_name}
@router.post('/auth/logout')
def logout(response:Response,u=Depends(current),db=Depends(session)):
    db.get(User,u.id).token_version+=1;db.commit();response.delete_cookie('intel_session',path='/');return {'ok':True}
@router.get('/users')
def users(u=Depends(admin),db=Depends(session)):return [{'id':r.id,'username':r.username,'email':r.email,'role':r.role,'active':r.active} for r in db.scalars(select(User))]
@router.post('/users',status_code=201)
def new_user(data:S.NewUser,u=Depends(admin),db=Depends(session)):
    if db.scalar(select(User.id).where(or_(User.email==data.email,func.lower(func.trim(User.username))==data.email))):raise HTTPException(409,'This email is already registered')
    r=User(username=data.email,email=data.email,password_hash=hasher.hash(data.password),role=data.role);db.add(r);service.audit(db,u,None,'CREATE_USER',username=data.email,role=data.role);db.commit();return {'id':r.id,'username':r.username,'email':r.email,'role':r.role}
@router.post('/users/{ident}/disable')
def disable_user(ident:str,u=Depends(admin),db=Depends(session)):
    if ident==u.id:raise HTTPException(409,'Cannot disable your own account')
    from .accounts import locked_users,safe_change
    rows=locked_users(db);r=next((x for x in rows if x.id==ident),None)
    if not r:raise HTTPException(404,'User not found')
    safe_change(rows,r,False,r.role)
    r.active=False;r.token_version+=1;service.audit(db,u,None,'DISABLE_USER',user_id=ident);db.commit();return {'ok':True}
@router.get('/health')
def health(request:Request,response:Response):
    try:
        with request.app.state.sessions() as db:db.execute(select(1))
        return {'status':'ready','database':True}
    except Exception:response.status_code=503;return {'status':'not_ready','database':False}
@router.get('/system/status')
def system(request:Request,u=Depends(current)):
    c=request.app.state.config
    return {**request.app.state.worker.status(),'disk_free_mb':shutil.disk_usage(c.storage_dir).free//1048576,'timezone':c.timezone,'biometric_enabled':c.biometric_enabled,'inference_fps':c.inference_fps,'preview_fps':c.preview_fps,'overlay_ttl':c.overlay_ttl,'retention_days':c.retention_days,'device':c.device,'dino_device':c.dino_device,'sms_configured':otp.configured(c),'resident_otp_required':True,'auto_exit_enabled':c.auto_exit_enabled,'auto_test_exit_enabled':c.auto_test_exit_enabled,'snapshot_format':'passport_v2','update_version':'resident-otp-portrait-v1'}
@router.get('/system/models')
def models(request:Request,u=Depends(current)):
    c=request.app.state.config
    return {'state':request.app.state.worker.model_state,'files':{x:(c.model_dir/x).is_file() for x in ('yolov8m.pt','face_detection_yunet_2023mar.onnx','face_recognition_sface_2021dec.onnx','grounding_dino_tiny/config.json','grounding_dino_tiny/model.safetensors','bytetrack.yaml')}}
@router.get('/system/inference')
def inference(request:Request,u=Depends(current)):return request.app.state.worker.status()

@router.get('/cameras')
def cameras(u=Depends(current),db=Depends(session)):return [camera_json(r) for r in db.scalars(select(Camera).order_by(Camera.created_at.desc()))]
@router.post('/cameras/test')
def test_camera(data:S.CameraTest,request:Request,u=Depends(admin)):
    url=validate_camera_url(data.rtsp_url,request.app.state.config)
    try:ok=test_connection(url,request.app.state.config)
    except CameraStreamError as exc:return {'connected':False,'message':exc.public_message}
    except Exception:ok=False
    return {'connected':ok,'message':'Decoded a real frame' if ok else 'Cannot decode stream; check credentials, address and network'}
@router.post('/cameras',status_code=201)
def add_camera(data:S.CameraInput,request:Request,u=Depends(admin),db=Depends(session)):
    if not data.rtsp_url:raise HTTPException(422,'RTSP URL required')
    c=request.app.state.config;url=validate_camera_url(data.rtsp_url,c)
    r=Camera(name=data.name,location=data.location,purpose=data.purpose,rtsp_encrypted=protect(url,c),fingerprint=fingerprint(url,c));db.add(r);service.audit(db,u,None,'CREATE_CAMERA',name=data.name);db.commit();return camera_json(r)
@router.get('/cameras/{ident}')
@router.get('/cameras/{ident}/status')
def camera(ident:str,u=Depends(current),db=Depends(session)):return camera_json(get(db,Camera,ident))
@router.put('/cameras/{ident}')
def edit_camera(ident:str,data:S.CameraInput,request:Request,u=Depends(admin),db=Depends(session)):
    r=get(db,Camera,ident)
    if r.enabled:raise HTTPException(409,'Stop camera before editing')
    r.name,r.location,r.purpose=data.name,data.location,data.purpose
    if data.rtsp_url:
        c=request.app.state.config;url=validate_camera_url(data.rtsp_url,c);r.rtsp_encrypted=protect(url,c);r.fingerprint=fingerprint(url,c)
    service.audit(db,u,None,'EDIT_CAMERA',camera_id=ident);db.commit();return camera_json(r)
@router.put('/cameras/{ident}/zones')
def zones(ident:str,data:S.Zones,u=Depends(admin),db=Depends(session)):
    r=get(db,Camera,ident)
    if r.enabled:raise HTTPException(409,'Stop camera before changing zones')
    r.zones=data.model_dump(exclude_none=True);service.audit(db,u,None,'SET_ZONES',camera_id=ident,zones=r.zones);db.commit();return camera_json(r)
@router.delete('/cameras/{ident}')
def delete_camera(ident:str,request:Request,u=Depends(admin),db=Depends(session)):
    r=get(db,Camera,ident)
    if db.scalar(select(ExitObservation.id).where(ExitObservation.camera_id==ident).limit(1)):raise HTTPException(409,'Camera has exit evidence; retain it stopped to preserve history')
    request.app.state.worker.remove(ident);db.delete(r);service.audit(db,u,None,'DELETE_CAMERA',camera_id=ident);db.commit();return {'ok':True}
@router.post('/cameras/{ident}/{action}')
def camera_action(ident:str,action:str,request:Request,u=Depends(admin),db=Depends(session)):
    get(db,Camera,ident)
    if action not in ('start','stop','restart'):raise HTTPException(404,'Unknown action')
    try:
        if action in ('stop','restart'):request.app.state.worker.remove(ident)
        if action in ('start','restart'):request.app.state.worker.add(ident,True)
    except ValueError as exc:raise HTTPException(409,str(exc))
    service.audit(db,u,None,'CAMERA_'+action.upper(),camera_id=ident);db.commit();return {'ok':True}
@router.get('/cameras/{ident}/preview')
async def preview(ident:str,request:Request,u=Depends(current)):
    w=request.app.state.worker
    if w.preview(ident) is None:raise HTTPException(503,'No live frame available')
    async def stream():
        while not await request.is_disconnected():
            try:authenticate(request.cookies.get('intel_session'),request.app)
            except HTTPException:break
            frame=w.preview(ident)
            if frame is None:break
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+frame+b'\r\n'
            await asyncio.sleep(1/request.app.state.config.preview_fps)
    return StreamingResponse(stream(),media_type='multipart/x-mixed-replace; boundary=frame',headers={'Cache-Control':'no-store'})

def resident_json(r,c):
    return {'id':r.id,'name':r.name,'flat':r.flat,'phone':reveal(r.phone_encrypted,c) if r.phone_encrypted else '', 'active':r.active}

@router.get('/cameras/{ident}/frame')
def current_camera_frame(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    get(db,Camera,ident)
    frame=request.app.state.worker.preview(ident)
    return Response(content=frame or b'',status_code=200 if frame else 204,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@router.get('/residents')
def residents(request:Request,u=Depends(current),db=Depends(session),flat:str|None=Query(None,max_length=40)):
    query=select(Resident).where(Resident.active)
    if flat is not None:query=query.where(func.upper(Resident.flat)==flat.strip().upper())
    return [resident_json(r,request.app.state.config) for r in db.scalars(query.order_by(Resident.flat,Resident.name))]

@router.post('/residents',status_code=201)
def add_resident(data:S.ResidentInput,request:Request,u=Depends(admin),db=Depends(session)):
    # Restore a removed matching entry rather than breaking its historical FK.
    r=db.scalar(select(Resident).where(Resident.name==data.name,Resident.flat==data.flat).with_for_update())
    if r and r.active:raise HTTPException(409,'This resident already exists in the flat')
    if not r:r=Resident(name=data.name,flat=data.flat,revision=0);db.add(r)
    else:r.revision+=1
    r.active=True;r.phone_encrypted=protect(data.phone,request.app.state.config)
    db.flush();service.audit(db,u,None,'CREATE_RESIDENT',resident_id=r.id,flat=data.flat);db.commit();return resident_json(r,request.app.state.config)

@router.put('/residents/{ident}')
def edit_resident(ident:str,data:S.ResidentInput,request:Request,u=Depends(admin),db=Depends(session)):
    r=db.scalar(select(Resident).where(Resident.id==ident,Resident.active).with_for_update())
    if not r:raise HTTPException(404,'Resident not found')
    r.name,r.flat=data.name,data.flat;r.phone_encrypted=protect(data.phone,request.app.state.config);r.revision+=1
    service.audit(db,u,None,'EDIT_RESIDENT',resident_id=ident,flat=data.flat);db.commit();return resident_json(r,request.app.state.config)

@router.delete('/residents/{ident}')
def delete_resident(ident:str,u=Depends(admin),db=Depends(session)):
    r=db.scalar(select(Resident).where(Resident.id==ident,Resident.active).with_for_update())
    if not r:raise HTTPException(404,'Resident not found')
    r.active=False;r.phone_encrypted=None;r.revision+=1
    from .models import ResidentFace
    face=db.scalar(select(ResidentFace).where(ResidentFace.resident_id==ident).with_for_update())
    if face:face.active=False;face.embedding_encrypted=None;face.snapshot_id=None
    service.audit(db,u,None,'DELETE_RESIDENT',resident_id=ident,history_retained=True);db.commit();return {'ok':True,'history_retained':True}

@router.get('/events/{ident}/otp')
def otp_status(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    e=get(db,Event,ident);o=otp.challenge(db,e);c=request.app.state.config
    base={'sms_configured':otp.configured(c),'verified':False,'state':'NONE'}
    if not o or o.requested_by!=u.id:return base
    r=db.get(Resident,o.resident_id)
    valid=bool(r and r.active and e.state in service.EDITABLE and o.destination_digest==otp.destination(c,r) and otp.utc(o.expires_at)>now() and not o.consumed_at)
    return {**base,'state':o.state if valid else 'EXPIRED','verified':valid and o.state=='VERIFIED','challenge_id':o.id,'resident_id':o.resident_id,'expires_at':o.expires_at,'resend_at':otp.utc(o.sent_at)+timedelta(seconds=c.otp_resend_seconds)}

@router.post('/events/{ident}/otp/request')
def request_otp(ident:str,data:S.OTPRequest,request:Request,u=Depends(current),db=Depends(session)):
    return otp.request_code(db,ident,data,u,request.app.state.config,sender=otp.send_sms)

@router.post('/events/{ident}/otp/verify')
def verify_otp(ident:str,data:S.OTPCheck,request:Request,u=Depends(current),db=Depends(session)):
    return otp.check_code(db,ident,data,u,request.app.state.config)

@router.get('/events/pending')
def pending(u=Depends(current),db=Depends(session),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    return [event_json(r,db) for r in db.scalars(select(Event).where(Event.state.in_(service.EDITABLE)).order_by(Event.created_at.desc()).offset(offset).limit(limit))]
@router.get('/events')
def events(u=Depends(current),db=Depends(session),state:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    q=select(Event)
    if state:q=q.where(Event.state==state)
    return [event_json(r,db) for r in db.scalars(q.order_by(Event.created_at.desc()).offset(offset).limit(limit))]
@router.post('/events/manual',status_code=201)
def manual(data:S.Manual,u=Depends(current),db=Depends(session)):
    if data.camera_id:get(db,Camera,data.camera_id)
    e=Event(camera_id=data.camera_id,track_ref='manual:'+uuid4().hex,evidence={'manual_reason':data.reason,'time_basis':'guard_report'});db.add(e);db.flush();service.audit(db,u,e,'MANUAL_CANDIDATE',reason=data.reason);db.commit();return event_json(e,db)
@router.get('/events/{ident}')
def detail(ident:str,u=Depends(current),db=Depends(session)):return event_json(get(db,Event,ident),db)
@router.post('/events/{ident}/verify')
def verify(ident:str,data:S.Destination,request:Request,u=Depends(current),db=Depends(session)):
    e=service.lock(db,ident);service.verify(db,e,data,u,request.app.state.config);db.commit();return event_json(e,db)
@router.post('/events/{ident}/save')
def save(ident:str,data:S.Destination,request:Request,u=Depends(current),db=Depends(session)):
    v=service.save(db,ident,data,u,request.app.state.config);db.commit();return visit_json(v,db)
@router.post('/events/{ident}/reject')
@router.post('/events/{ident}/review')
@router.post('/events/{ident}/cancel')
def change_state(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    target={'reject':'NOT_DELIVERY','review':'NEEDS_REVIEW','cancel':'CANCELLED'}[request.url.path.rsplit('/',1)[1]];e=service.lock(db,ident);service.transition(db,e,target,u);db.commit();return event_json(e,db)
@router.post('/events/{ident}/complete')
def complete(ident:str,data:S.Completion,u=Depends(current),db=Depends(session)):
    v=service.complete(db,service.lock(db,ident),data,u);db.commit();return visit_json(v,db)
@router.get('/visits')
def visits(u=Depends(current),db=Depends(session),q:str='',status:str|None=None,start:datetime|None=None,end:datetime|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    query=select(Visit)
    if q:query=query.where(or_(Visit.resident_name.ilike('%'+q+'%'),Visit.flat.ilike('%'+q+'%')))
    if status:query=query.where(Visit.status==status)
    if start:query=query.where(Visit.created_at>=start)
    if end:query=query.where(Visit.created_at<=end)
    return [visit_json(v,db) for v in db.scalars(query.order_by(Visit.created_at.desc()).offset(offset).limit(limit))]
@router.get('/exit-observations')
def exits(u=Depends(current),db=Depends(session)):
    rows=db.execute(select(ExitObservation,Camera,Event,Snapshot,Video).outerjoin(Camera,Camera.id==ExitObservation.camera_id).outerjoin(Event,Event.track_ref==ExitObservation.track_ref).outerjoin(Snapshot,Snapshot.id==Event.snapshot_id).outerjoin(Video,Video.id==ExitObservation.video_id).where(ExitObservation.state=='NEEDS_REVIEW').order_by(ExitObservation.created_at.desc()).limit(100)).all()
    return [{**{k:getattr(x,k) for k in ('id','camera_id','visit_id','evidence','created_at')},'camera_name':camera.name if camera else (video.filename if video else 'Unavailable source'),'snapshot_id':snap.id if snap and not snap.deleted else None,'test_mode':bool(x.video_id),'video_seconds':event.frame_seconds if event else None} for x,camera,event,snap,video in rows]
@router.get('/snapshots/{ident}')
def snapshot(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    s=get(db,Snapshot,ident);path=request.app.state.storage.path(s.path)
    if s.deleted or not path.is_file():raise HTTPException(404,'Snapshot expired or unavailable')
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'no-store'})
@router.delete('/snapshots/{ident}')
def delete_snapshot(ident:str,request:Request,u=Depends(admin),db=Depends(session)):
    from .models import ResidentFace
    for face in db.scalars(select(ResidentFace).where(ResidentFace.snapshot_id==ident).with_for_update()):
        face.active=False;face.embedding_encrypted=None;face.snapshot_id=None
    s=get(db,Snapshot,ident);s.deleted=True;s.embedding_encrypted=None;service.audit(db,u,None,'DELETE_SNAPSHOT',snapshot_id=ident);db.commit();request.app.state.storage.remove(s.path);return {'ok':True}
@router.post('/visits/{ident}/enroll')
def enroll(ident:str,data:S.Enrollment,request:Request,u=Depends(admin),db=Depends(session)):
    if not request.app.state.config.biometric_enabled:raise HTTPException(409,'Biometric matching is disabled')
    v=get(db,Visit,ident);e=db.get(Event,v.event_id);s=db.get(Snapshot,e.snapshot_id) if e.snapshot_id else None
    if not s or s.deleted or not s.embedding_encrypted:raise HTTPException(409,'No usable authorized embedding')
    p=FaceProfile(visit_id=v.id,embedding_encrypted=s.embedding_encrypted,authorization=data.authorization,authorized_by=u.id,expires_at=now()+timedelta(days=data.retention_days));db.add(p);service.audit(db,u,e,'ENROLL',authorization=data.authorization,days=data.retention_days);db.commit();return {'id':p.id,'expires_at':p.expires_at}
@router.get('/profiles')
def profiles(u=Depends(admin),db=Depends(session)):return [{k:getattr(p,k) for k in ('id','visit_id','authorization','expires_at')} for p in db.scalars(select(FaceProfile))]
@router.delete('/profiles/{ident}')
def delete_profile(ident:str,u=Depends(admin),db=Depends(session)):
    db.delete(get(db,FaceProfile,ident));service.audit(db,u,None,'DELETE_PROFILE',profile_id=ident);db.commit();return {'ok':True}

@router.get('/videos')
def videos(u=Depends(current),db=Depends(session)):return [{k:getattr(v,k) for k in ('id','filename','size','duration','status','test_role')} for v in db.scalars(select(Video).where(Video.status!='DELETED').order_by(Video.created_at.desc()).limit(100))]
@router.post('/videos/upload',status_code=201)
async def upload(request:Request,file:UploadFile=File(...),u=Depends(current),db=Depends(session)):
    storage=request.app.state.storage;c=request.app.state.config;key='uploads/'+uuid4().hex+'.video';path=storage.path(key);size=0
    try:
        storage.space()
        with path.open('xb') as out:
            while chunk:=await file.read(1048576):
                size+=len(chunk)
                if size>c.max_upload_mb*1048576:raise HTTPException(413,'Upload exceeds configured limit')
                storage.space();out.write(chunk)
            out.flush();os.fsync(out.fileno())
        from starlette.concurrency import run_in_threadpool
        m=await run_in_threadpool(probe,path,c)
        v=Video(filename=(file.filename or 'video').replace('\\','/').split('/')[-1][:250],path=key,size=size,duration=m['duration']);db.add(v);db.commit();return {'id':v.id,'filename':v.filename,'duration':v.duration,'status':v.status}
    except ValueError as exc:path.unlink(missing_ok=True);raise HTTPException(422,str(exc))
    except BaseException:path.unlink(missing_ok=True);raise
    finally:await file.close()
@router.delete('/videos/{ident}')
def delete_video(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    worker=request.app.state.worker
    # Serialize against source admission in this single-worker application.
    with worker.lock:
        v=db.get(Video,ident)
        if v is None:raise HTTPException(404,'Record not found')
        if v.status in ('RUNNING','QUEUED') or 'video:'+ident in worker.sources:
            raise HTTPException(409,'Cancel analysis before deleting this video')
        if v.status!='DELETED':
            v.status='DELETED'
            job=db.scalar(select(Job).where(Job.video_id==ident))
            if job:job.status='DELETED'
            service.audit(db,u,None,'DELETE_VIDEO',video_id=ident,filename=v.filename,evidence_retained=True)
            db.commit()
        worker.video_previews.pop(ident,None)
        try:request.app.state.storage.remove(v.path)
        except OSError:
            # Retention retries removal; the deleted item cannot be analyzed again.
            return {'ok':True,'file_removed':False,'warning':'Video removed from the list; source-file cleanup is pending. Saved evidence is retained.'}
    return {'ok':True,'file_removed':True,'evidence_retained':True}
@router.post('/videos/{ident}/analyze')
def analyze(ident:str,data:S.VideoTest,request:Request,u=Depends(current),db=Depends(session)):
    with request.app.state.worker.lock:
        v=get(db,Video,ident)
        if v.status in ('RUNNING','QUEUED'):raise HTTPException(409,'This video is already being analyzed')
        if data.test_role=='exit' and not v.test_role and db.scalar(select(Visit.id).join(Event,Event.id==Visit.event_id).where(Event.video_id==v.id).limit(1)):raise HTTPException(409,'This recording already has saved entries. Label it Entry or upload a separate Exit recording.')
        if v.test_role and v.test_role!=data.test_role:raise HTTPException(409,'A recording keeps its original test label. Upload a separate copy to change its label.')
        if v.status=='EXPIRED':raise HTTPException(409,'Video expired')
        if not request.app.state.storage.path(v.path).is_file():raise HTTPException(410,'Original video file is unavailable')
        if not request.app.state.config.ai_enabled:raise HTTPException(409,'AI is disabled')
        v.test_role=data.test_role;db.commit()
        try:request.app.state.worker.add(ident,False)
        except ValueError as exc:raise HTTPException(409,str(exc))
        service.audit(db,u,None,'ANALYZE_VIDEO',video_id=ident,history_retained=True);db.commit()
        return {'ok':True}
@router.post('/videos/{ident}/cancel')
def cancel(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    if get(db,Video,ident).status not in ('RUNNING','QUEUED'):raise HTTPException(409,'No active analysis')
    request.app.state.worker.remove(ident,False);return {'ok':True}
@router.get('/videos/{ident}/status')
def video_status(ident:str,u=Depends(current),db=Depends(session)):
    v=get(db,Video,ident);j=db.scalar(select(Job).where(Job.video_id==ident));return {'id':v.id,'status':j.status if j else v.status,'progress':j.progress if j else 0,'error':j.error if j else None,'test_role':v.test_role}
@router.get('/videos/{ident}/preview')
def video_preview(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    v=get(db,Video,ident)
    if v.status=='EXPIRED':raise HTTPException(410,'Video expired')
    packet=request.app.state.worker.video_preview(ident)
    if packet is None:return Response(status_code=204,headers={'Cache-Control':'no-store'})
    jpeg,seconds,sequence=packet
    return Response(content=jpeg,media_type='image/jpeg',headers={
        'Cache-Control':'no-store','X-Frame-Seconds':str(seconds),'X-Preview-Sequence':sequence,
        'Access-Control-Expose-Headers':'X-Frame-Seconds, X-Preview-Sequence'})
@router.get('/videos/{ident}/results')
def results(ident:str,u=Depends(current),db=Depends(session),offset:int=Query(0,ge=0)):
    get(db,Video,ident)
    return {'events':[event_json(e,db) for e in db.scalars(select(Event).where(Event.video_id==ident).order_by(Event.frame_seconds).offset(offset).limit(100))],'timeline':[{'seconds':d.frame_seconds,'evidence':d.evidence} for d in db.scalars(select(Detection).where(Detection.source_key=='video:'+ident).order_by(Detection.frame_seconds).offset(offset).limit(100))]}
@router.get('/dashboard/summary')
def summary(u=Depends(current),db=Depends(session)):
    def count(model,*where):return db.scalar(select(func.count()).select_from(model).where(*where))
    return {'cameras':count(Camera),'connected':count(Camera,Camera.status=='CONNECTED'),'pending':count(Event,Event.state.in_(service.EDITABLE)),'active_visits':count(Visit,Visit.status=='ENTRY_RECORDED',Visit.historical.is_(False)),'saved_visits':count(Visit),'completed':count(Visit,Visit.status=='COMPLETED',Visit.historical.is_(False))}
@router.get('/dashboard/recent-events')
def recent(u=Depends(current),db=Depends(session)):
    # A confirmed exit is evidence of the saved visit, not another dashboard visit.
    # Keep the entry card for combined entry/exit tracks whose event is the same row.
    linked_exit=select(ExitObservation.id).join(Visit,Visit.id==ExitObservation.visit_id).where(ExitObservation.track_ref==Event.track_ref,Visit.event_id!=Event.id,ExitObservation.state.in_(['AUTO_CONFIRMED','GUARD_CONFIRMED'])).exists()
    statement=select(Event).outerjoin(Visit,Visit.event_id==Event.id).where(~linked_exit,Event.state!='RESIDENT').order_by(func.coalesce(Visit.completed_at,Event.created_at).desc(),Event.id.desc()).limit(8)
    return [event_json(e,db) for e in db.scalars(statement)]
@router.get('/audit')
def audits(u=Depends(admin),db=Depends(session),offset:int=Query(0,ge=0)):return [{k:getattr(a,k) for k in ('id','actor_id','event_id','action','details','created_at')} for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).offset(offset).limit(100))]


@router.get('/apartment-map')
def apartment_map(u=Depends(current),db=Depends(session)):
    rows=db.execute(select(Visit,Event,Snapshot,Video).join(Event,Event.id==Visit.event_id).outerjoin(Snapshot,Snapshot.id==Event.snapshot_id).outerjoin(Video,Video.id==Event.video_id).where(Visit.status=='ENTRY_RECORDED',or_(Visit.historical.is_(False),Video.test_role=='entry')).order_by(Visit.created_at.desc()).limit(501)).all()
    active=[]
    for v,e,snap,video in rows[:500]:
        active.append({'id':v.id,'flat':v.flat,'resident_name':v.resident_name,'entry_at':v.entry_at,'snapshot_id':snap.id if snap and not snap.deleted else None,'purpose':(e.verification or {}).get('visit_purpose','Visitor'),'visitor_name':(e.verification or {}).get('visitor_name',''),'visit_reason':(e.verification or {}).get('visit_reason',''),'test_mode':bool(v.historical),'video_seconds':e.frame_seconds,'saved_at':v.created_at})
    points=[{'flat':point.flat,'x':point.x,'y':point.y} for point in db.scalars(select(ApartmentMapPoint).order_by(ApartmentMapPoint.flat))]
    flats=sorted(set(db.scalars(select(Resident.flat).where(Resident.active))))
    return {'points':points,'flats':flats,'visits':active,'truncated':len(rows)>500}

@router.put('/apartment-map/point')
def save_apartment_point(data:S.MapPointInput,u=Depends(admin),db=Depends(session)):
    if not db.scalar(select(Resident.id).where(Resident.active,func.upper(Resident.flat)==data.flat).limit(1)):
        raise HTTPException(400,'Choose a flat with an active resident')
    point=db.scalar(select(ApartmentMapPoint).where(ApartmentMapPoint.flat==data.flat).with_for_update())
    if not point:point=ApartmentMapPoint(flat=data.flat,x=data.x,y=data.y);db.add(point)
    else:point.x=data.x;point.y=data.y
    service.audit(db,u,None,'MAP_POINT_SAVE',flat=data.flat);db.commit()
    return {'flat':point.flat,'x':point.x,'y':point.y}

@router.post('/apartment-map/remove')
def remove_apartment_point(data:S.MapFlat,u=Depends(admin),db=Depends(session)):
    point=db.scalar(select(ApartmentMapPoint).where(ApartmentMapPoint.flat==data.flat).with_for_update())
    if not point:raise HTTPException(404,'Map point not found')
    db.delete(point);service.audit(db,u,None,'MAP_POINT_REMOVE',flat=data.flat);db.commit()
    return {'ok':True}


class ManualCrop(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(pattern=r'^[0-9a-f]{32}$')
    left:float=Field(ge=0,le=1,allow_inf_nan=False)
    top:float=Field(ge=0,le=1,allow_inf_nan=False)
    right:float=Field(ge=0,le=1,allow_inf_nan=False)
    bottom:float=Field(ge=0,le=1,allow_inf_nan=False)
    @model_validator(mode='after')
    def bounds(self):
        if self.right<=self.left or self.bottom<=self.top:raise ValueError('Select a non-empty area')
        return self

def capture_event(db,ident,lock=False):
    event=service.lock(db,ident) if lock else get(db,Event,ident)
    if event.state not in service.EDITABLE | {'ENTRY_RECORDED'}:raise HTTPException(409,'Snapshot cannot be changed for this event')
    if not event.camera_id or event.video_id:raise HTTPException(409,'Manual capture requires the event’s live camera')
    return event

@router.post('/events/{ident}/manual-capture')
def capture_live_frame(ident:str,request:Request,u=Depends(current),db=Depends(session)):
    import cv2
    event=capture_event(db,ident);packet=request.app.state.worker.raw_frame(event.camera_id)
    if packet is None:raise HTTPException(409,'Start the event camera and wait for a live frame')
    frame=packet[0].copy();height,width=frame.shape[:2]
    if not width or not height:raise HTTPException(409,'Live frame unavailable')
    scale=min(1,1280/width,960/height)
    if scale<1:frame=cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale))))
    ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,90])
    if not ok:raise HTTPException(503,'Could not capture the live frame')
    return {'token':captures.create(ident,u.id,jpeg.tobytes())}

@router.get('/events/{ident}/manual-capture/{token}')
def captured_frame(ident:str,token:str,u=Depends(current),db=Depends(session)):
    capture_event(db,ident)
    return Response(captures.read(token,ident,u.id),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

@router.post('/events/{ident}/manual-snapshot')
def save_manual_snapshot(ident:str,data:ManualCrop,request:Request,u=Depends(current),db=Depends(session)):
    import cv2,numpy as np
    jpeg=captures.read(data.token,ident,u.id)
    event=capture_event(db,ident,lock=True)
    frame=cv2.imdecode(np.frombuffer(jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise HTTPException(422,'Captured frame unavailable')
    h,w=frame.shape[:2];left=int(data.left*w);right=int(data.right*w);top=int(data.top*h);bottom=int(data.bottom*h)
    if right-left<24 or bottom-top<24:raise HTTPException(422,'Select a larger face area in the camera frame')
    crop=frame[top:bottom,left:right]
    ok,encoded=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,92])
    if not ok:raise HTTPException(503,'Could not save the selected area')
    storage=request.app.state.storage;path=storage.put(encoded.tobytes())
    try:
        previous=event.snapshot_id
        snap=Snapshot(path=path,quality=0,metrics={'framing':'manual_guard_crop','source':'guard_live_camera','image_width':int(crop.shape[1]),'image_height':int(crop.shape[0])},approved=event.state=='ENTRY_RECORDED',embedding_encrypted=None)
        db.add(snap);db.flush();event.snapshot_id=snap.id
        evidence=dict(event.evidence or {});evidence.pop('identity_suggestion',None);evidence.update(face_reason='CAPTURED',manual_snapshot=True);event.evidence=evidence
        service.audit(db,u,event,'MANUAL_SNAPSHOT',previous_snapshot_id=previous,snapshot_id=snap.id)
        db.commit()
    except Exception:
        db.rollback();storage.remove(path);raise
    captures.discard(data.token)
    return event_json(event,db)

@router.get('/visits/{ident}')
def visit_detail(ident:str,u=Depends(current),db=Depends(session)):
    from .logs_api import timeline
    v=get(db,Visit,ident)
    return {**visit_json(v,db),**timeline(v.event_id,u,db)}
