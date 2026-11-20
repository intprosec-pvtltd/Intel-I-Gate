"""Consent-based resident enrollment; live-only conservative recognition."""
import json
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from typing import Literal
from sqlalchemy import select
from .models import ResidentFace,Resident,Snapshot,Event,Visit,ExitObservation,now
from .security import current,admin,protect,reveal
from .api import session
from .events import audit,lock
from .auto_exit import vector
router=APIRouter(prefix='/api')


def match_resident(db,embedding,c):
    if not c.biometric_enabled or not c.resident_recognition_enabled:return None
    probe=vector(embedding)
    if probe is None:return None
    scores=[]
    for face in db.scalars(select(ResidentFace).join(Resident,Resident.id==ResidentFace.resident_id).where(ResidentFace.active.is_(True),Resident.active.is_(True),ResidentFace.embedding_encrypted.is_not(None))):
        try:reference=vector(json.loads(reveal(face.embedding_encrypted,c)))
        except Exception:continue
        if reference is not None:scores.append((float(probe@reference),face.resident_id))
    scores.sort(reverse=True)
    if not scores or scores[0][0]<c.resident_match_threshold:return None
    if len(scores)>1 and scores[0][0]-scores[1][0]<c.resident_match_margin:return None
    return scores[0][1]

class Enrollment(BaseModel):
    resident_id:str=Field(min_length=1,max_length=36)
    consent:Literal[True]
    confirmed_identity:Literal[True]

@router.post('/events/{ident}/resident')
def enroll(ident:str,data:Enrollment,request:Request,u=Depends(current),db=Depends(session)):
    c=request.app.state.config
    if not c.biometric_enabled:raise HTTPException(409,'Enable BIOMETRIC_ENABLED before enrolling a resident')
    e=lock(db,ident)
    if e.video_id or not e.camera_id:raise HTTPException(409,'Enroll only from a live camera observation')
    if e.state not in ('PENDING_VERIFICATION','NEEDS_REVIEW','CONFIRMED','EXIT_REVIEW') or db.scalar(select(Visit.id).where(Visit.event_id==e.id)):
        raise HTTPException(409,'This observation cannot be enrolled as a resident')
    r=db.scalar(select(Resident).where(Resident.id==data.resident_id,Resident.active.is_(True)).with_for_update())
    if not r:raise HTTPException(404,'Active resident not found')
    s=db.get(Snapshot,e.snapshot_id) if e.snapshot_id else None
    if not s or s.deleted:raise HTTPException(409,'Capture a clear face snapshot first')
    # Recheck the actual photo, including manual retakes: never trust a stale embedding.
    import cv2,numpy as np
    worker=request.app.state.worker
    if not worker.pipeline:raise HTTPException(503,'Face models are not ready')
    try:frame=cv2.imdecode(np.frombuffer(request.app.state.storage.path(s.path).read_bytes(),dtype=np.uint8),cv2.IMREAD_COLOR)
    except (OSError,ValueError,cv2.error):raise HTTPException(422,'Snapshot is unavailable; retake the photo')
    from .vision import FaceService
    # A separate detector avoids mutating the live inference thread's OpenCV state.
    embedding=FaceService(c).single_snapshot_embedding(frame) if frame is not None else None
    if vector(embedding) is None:raise HTTPException(422,'Use a clear photo containing exactly one detectable face')
    face=db.scalar(select(ResidentFace).where(ResidentFace.resident_id==r.id).with_for_update())
    if not face:face=ResidentFace(resident_id=r.id,enrolled_by=u.id);db.add(face)
    face.snapshot_id=s.id;face.embedding_encrypted=protect(json.dumps(list(map(float,embedding))),c);face.active=True;face.enrolled_by=u.id;face.consent_at=now()
    observation=db.scalar(select(ExitObservation).where(ExitObservation.track_ref==e.track_ref,ExitObservation.visit_id.is_(None)))
    if observation:observation.state='RESIDENT'
    s.approved=True;e.state='RESIDENT';e.verification={'resident_id':r.id,'resident_name':r.name,'flat':r.flat}
    audit(db,u,None,'ENROLL_RESIDENT_FACE',resident_id=r.id,consent=True);db.commit()
    return {'ok':True,'message':'Resident enrolled. Future confident live matches will not create visitor events.'}

@router.get('/resident-faces')
def directory(u=Depends(current),db=Depends(session)):
    return [{'resident_id':f.resident_id,'snapshot_id':f.snapshot_id,'active':f.active,'consent_at':f.consent_at} for f in db.scalars(select(ResidentFace).join(Resident,Resident.id==ResidentFace.resident_id).where(Resident.active.is_(True)))]

@router.delete('/resident-faces/{ident}')
def remove(ident:str,u=Depends(admin),db=Depends(session)):
    r=db.scalar(select(Resident).where(Resident.id==ident).with_for_update())
    if not r:raise HTTPException(404,'Resident not found')
    face=db.scalar(select(ResidentFace).where(ResidentFace.resident_id==ident).with_for_update())
    if face:face.active=False;face.embedding_encrypted=None;face.snapshot_id=None
    audit(db,u,None,'REMOVE_RESIDENT_FACE',resident_id=ident);db.commit();return {'ok':True}
