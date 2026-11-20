"""Visit-scoped automatic exit matching. No permanent watchlist enrollment."""
from datetime import datetime, timedelta, timezone
import json
import math
from functools import lru_cache
from cryptography.fernet import Fernet
import numpy as np
from sqlalchemy import select
from .models import Camera, Event, Visit, Snapshot, ExitObservation, Video, now
from .security import reveal
from .events import audit


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def vector(value):
    try:
        result=np.asarray(value,dtype=np.float64)
        if result.shape!=(128,) or not np.isfinite(result).all():return None
        norm=float(np.linalg.norm(result))
        return result/norm if math.isfinite(norm) and norm>1e-9 else None
    except (TypeError,ValueError):return None


@lru_cache(maxsize=512)
def reference_vector(cipher,key):
    return vector(json.loads(Fernet(key.encode()).decrypt(cipher.encode()).decode()))


def active_match(db,embedding,c,captured,test_mode=False,margin=None):
    query=vector(embedding)
    if query is None:return None
    statement=select(Visit,Event,Snapshot).join(Event,Event.id==Visit.event_id).join(Snapshot,Snapshot.id==Event.snapshot_id).where(Visit.status=='ENTRY_RECORDED',Visit.historical.is_(test_mode),Event.state=='ENTRY_RECORDED',Snapshot.approved.is_(True),Snapshot.deleted.is_(False),Snapshot.embedding_encrypted.is_not(None),Snapshot.approved.is_(True))
    if test_mode:
        statement=statement.join(Video,Video.id==Event.video_id).where(Video.test_role=='entry',Event.camera_id.is_(None))
    rows=db.execute(statement).all()
    scores=[]
    for visit,event,snapshot in rows:
        try:reference=reference_vector(snapshot.embedding_encrypted,c.encryption_key)
        except Exception:continue
        if reference is None:continue
        scores.append((float(query@reference),visit,event,snapshot))
    scores.sort(key=lambda item:item[0],reverse=True)
    if not scores or scores[0][0]<c.auto_exit_threshold:return None
    if len(scores)>1 and scores[0][0]-scores[1][0]<(c.auto_exit_margin if margin is None else margin):return None
    best=scores[0]
    # A new duplicate entry must not be ignored in favour of an older record.
    if not test_mode and (captured-utc(best[1].entry_at or best[1].created_at)).total_seconds()<c.auto_exit_min_entry_seconds:return None
    return best


def observe(db,event,embedding,seconds,captured,c,crossed=False):
    """Called only from the serialized live inference thread, within its DB transaction."""
    if not c.auto_exit_enabled or not c.biometric_enabled or not event.camera_id or event.video_id:return False
    if event.state in {'COMPLETED','EXIT_CONFIRMED','CANCELLED','NOT_DELIVERY'} or captured is None:return False
    captured=utc(captured)
    age=(now()-captured).total_seconds()
    if age< -1 or age>c.auto_exit_max_frame_age:return False
    camera=db.get(Camera,event.camera_id)
    if not camera or not camera.enabled or camera.purpose not in {'Exit Gate','Entry and Exit'}:return False
    dedicated_exit=camera.purpose=='Exit Gate'
    if not dedicated_exit and not (camera.zones or {}).get('exit'):return False
    evidence=dict(event.evidence or {})
    if crossed:evidence['auto_exit_crossed_at']=captured.isoformat()
    if embedding is None:
        event.evidence=evidence;return False
    previous=evidence.get('auto_exit_candidate') or {}
    if seconds<=previous.get('last_seconds',float('-inf')):
        event.evidence=evidence;return False
    match=active_match(db,embedding,c,captured)
    if match is None:
        evidence.pop('auto_exit_candidate',None);event.evidence=evidence;return False
    score,visit,entry,snapshot=match
    if previous.get('visit_id')!=visit.id or previous.get('snapshot_id')!=snapshot.id or captured.timestamp()-previous.get('first_at',0)>c.auto_exit_window:
        previous={'visit_id':visit.id,'snapshot_id':snapshot.id,'hits':0,'first_at':captured.timestamp(),'minimum_similarity':score}
    previous={**previous,'hits':previous['hits']+1,'last_seconds':float(seconds),'minimum_similarity':min(previous['minimum_similarity'],score)}
    evidence['auto_exit_candidate']=previous;event.evidence=evidence
    fast=dedicated_exit and c.auto_exit_fast_enabled and score>=c.auto_exit_fast_threshold
    if fast:
        # Recheck all active references against the stronger margin before one-frame completion.
        fast=active_match(db,embedding,c,captured,margin=max(c.auto_exit_margin,c.auto_exit_fast_margin)) is not None
    if not fast and (previous['hits']<c.auto_exit_confirmations or captured.timestamp()-previous['first_at']<c.auto_exit_min_span):return False
    if dedicated_exit:
        crossing=captured  # Recognition time, not a physical boundary crossing.
    else:
        try:crossing=utc(datetime.fromisoformat(evidence.get('auto_exit_crossed_at','')))
        except (ValueError,TypeError):return False
        if not 0<=(captured-crossing).total_seconds()<=c.auto_exit_window:return False
    # Serialize with manual completion and snapshot replacement: entry event, then visit.
    entry=db.scalar(select(Event).where(Event.id==entry.id).with_for_update().execution_options(populate_existing=True))
    visit=db.scalar(select(Visit).where(Visit.id==visit.id).with_for_update().execution_options(populate_existing=True))
    snapshot=db.get(Snapshot,previous['snapshot_id'])
    if not entry or not visit or visit.status!='ENTRY_RECORDED' or visit.historical or entry.snapshot_id!=previous['snapshot_id'] or not snapshot or snapshot.deleted or not snapshot.approved:return False
    if crossing<utc(visit.entry_at or visit.created_at):return False
    observation=db.scalar(select(ExitObservation).where(ExitObservation.track_ref==event.track_ref).with_for_update())
    if observation and (observation.state!='NEEDS_REVIEW' or observation.visit_id not in (None,visit.id)):return False
    if observation is None:
        observation=ExitObservation(camera_id=camera.id,track_ref=event.track_ref,evidence={});db.add(observation)
    details={'method':'AUTO_FACE_EXIT','camera_id':camera.id,'source_event_id':event.id,'similarity':round(score,6),'minimum_similarity':round(previous['minimum_similarity'],6),'samples':previous['hits'],'fast_match':fast,'threshold':c.auto_exit_fast_threshold if fast else c.auto_exit_threshold,'exit_time_basis':'FACE_RECOGNITION' if dedicated_exit else 'LINE_CROSSING','recognized_at':captured.isoformat(),**({'crossed_at':crossing.isoformat()} if not dedicated_exit else {}),'review_required':False}
    observation.visit_id=visit.id;observation.state='AUTO_CONFIRMED';observation.evidence={**(observation.evidence or {}),**details}
    visit.completed_at=now()
    visit.status='COMPLETED';visit.exit_at=crossing;entry.state='COMPLETED'
    from .visit_sessions import resolve_alert
    resolve_alert(db,visit)
    entry.evidence={**(entry.evidence or {}),'exit_completion':details}
    if event.id!=entry.id:event.state='EXIT_CONFIRMED';event.candidate_status='EXIT_CONFIRMED'
    event.evidence={**(event.evidence or {}),'auto_exit_completed':details}
    audit(db,None,entry,'AUTO_COMPLETE_EXIT',visit_id=visit.id,**details)
    return True


def observe_test(db,event,embedding,seconds,c):
    """Match labelled upload tests only; footage seconds are never calendar exit times."""
    if not c.auto_test_exit_enabled or not c.biometric_enabled or embedding is None:return False
    if not event.video_id or event.camera_id or event.state!='EXIT_REVIEW':return False
    video=db.get(Video,event.video_id)
    if not video or video.test_role!='exit':return False
    try:seconds=float(seconds)
    except (ValueError,TypeError):return False
    if not math.isfinite(seconds) or seconds<0:return False
    evidence=dict(event.evidence or {})
    previous=evidence.get('auto_test_exit_candidate') or {}
    # Ignore duplicate samples (including asynchronous delivery-model updates).
    if seconds<=previous.get('last_seconds',float('-inf')):return False
    match=active_match(db,embedding,c,now(),test_mode=True)
    if match is None:
        evidence.pop('auto_test_exit_candidate',None);event.evidence=evidence;return False
    score,visit,entry,snapshot=match
    if previous.get('visit_id')!=visit.id or previous.get('snapshot_id')!=snapshot.id or seconds-previous.get('first_seconds',0)>c.auto_exit_window:
        previous={'visit_id':visit.id,'snapshot_id':snapshot.id,'hits':0,'first_seconds':seconds,'minimum_similarity':score}
    previous={**previous,'hits':previous['hits']+1,'last_seconds':seconds,'minimum_similarity':min(previous['minimum_similarity'],score)}
    evidence['auto_test_exit_candidate']=previous;event.evidence=evidence
    if previous['hits']<c.auto_exit_confirmations or seconds-previous['first_seconds']<c.auto_exit_min_span:return False
    # Same lock order as manual completion and photo replacement.
    entry=db.scalar(select(Event).where(Event.id==entry.id).with_for_update().execution_options(populate_existing=True))
    visit=db.scalar(select(Visit).where(Visit.id==visit.id).with_for_update().execution_options(populate_existing=True))
    snapshot=db.get(Snapshot,previous['snapshot_id'])
    entry_video=db.get(Video,entry.video_id) if entry and entry.video_id else None
    if not entry or entry.camera_id or entry.state!='ENTRY_RECORDED' or not entry_video or entry_video.test_role!='entry':return False
    if not visit or not visit.historical or visit.status!='ENTRY_RECORDED' or entry.snapshot_id!=previous['snapshot_id'] or not snapshot or snapshot.deleted or not snapshot.approved:return False
    observation=db.scalar(select(ExitObservation).where(ExitObservation.track_ref==event.track_ref).with_for_update())
    if observation and (observation.state!='NEEDS_REVIEW' or observation.visit_id not in (None,visit.id) or observation.video_id!=video.id or observation.camera_id):return False
    if observation is None:
        observation=ExitObservation(video_id=video.id,camera_id=None,track_ref=event.track_ref,evidence={});db.add(observation)
    details={'method':'AUTO_TEST_FACE_EXIT','test_mode':True,'source_event_id':event.id,'video_id':video.id,'video_seconds':seconds,'first_video_seconds':previous['first_seconds'],'similarity':round(score,6),'minimum_similarity':round(previous['minimum_similarity'],6),'samples':previous['hits'],'threshold':c.auto_exit_threshold,'review_required':False}
    observation.visit_id=visit.id;observation.state='AUTO_CONFIRMED';observation.evidence={**(observation.evidence or {}),**details}
    visit.completed_at=now()
    visit.status='COMPLETED';visit.exit_at=None;entry.state='COMPLETED'
    from .visit_sessions import resolve_alert
    resolve_alert(db,visit)
    entry.evidence={**(entry.evidence or {}),'exit_completion':details}
    event.state='EXIT_CONFIRMED';event.candidate_status='EXIT_CONFIRMED'
    event.evidence={**evidence,'auto_test_exit_completed':details}
    audit(db,None,entry,'AUTO_COMPLETE_TEST_EXIT',visit_id=visit.id,**details)
    return True
