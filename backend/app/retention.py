"""Calendar retention with reference protection and retryable file deletion."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import threading
from sqlalchemy import select,delete,text
from .models import ResidentFace,Resident,Snapshot,Video,FaceProfile,DeliveryOTP,OTPSend,Event,Visit,ExitObservation,Audit,Detection,VisitAlert,FileDeletion,CleanupRun,now
_guard=threading.Lock()

def cleanup(sessions,storage,c):
    if not c.calendar_cleanup_enabled or not _guard.acquire(blocking=False):return
    try:
        moment=now();local=moment.astimezone(ZoneInfo(c.timezone));day=local.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc);month=local.replace(day=1,hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
        counts={'events':0,'visits':0,'snapshots':0,'files':0,'file_failures':0}
        with sessions() as db:
            if db.bind.dialect.name=='postgresql' and not db.scalar(text('SELECT pg_try_advisory_xact_lock(701924120)')):return
            db.execute(delete(FaceProfile).where(FaceProfile.expires_at<moment))
            protected_visits=set(db.scalars(select(Visit.id).where(Visit.status=='ENTRY_RECORDED')))|set(db.scalars(select(FaceProfile.visit_id)))
            protected_events=set(db.scalars(select(Visit.event_id).where(Visit.id.in_(protected_visits))))
            active=bool(protected_visits)
            for x in db.scalars(select(ExitObservation)):
                if x.visit_id in protected_visits or (active and x.state=='NEEDS_REVIEW'):
                    e=db.scalar(select(Event).where(Event.track_ref==x.track_ref))
                    if e:protected_events.add(e.id)
            visits=list(db.scalars(select(Visit).where(Visit.status=='COMPLETED',Visit.completed_at<month)))
            for v in visits:
                if v.id in protected_visits:continue
                e=db.get(Event,v.event_id)
                # Lock entry before visit, matching completion and resident responses.
                e=db.scalar(select(Event).where(Event.id==v.event_id).with_for_update())
                v=db.scalar(select(Visit).where(Visit.id==v.id).with_for_update().execution_options(populate_existing=True))
                if not v or v.status!='COMPLETED':continue
                for x in db.scalars(select(ExitObservation).where(ExitObservation.visit_id==v.id)):
                    source=db.scalar(select(Event).where(Event.track_ref==x.track_ref))
                    db.delete(x)
                    if source and source.id!=e.id and source.id not in protected_events:
                        erase_event(db,source);counts['events']+=1
                db.execute(delete(VisitAlert).where(VisitAlert.visit_id==v.id))
                db.delete(v);db.flush();erase_event(db,e);counts['events']+=1;counts['visits']+=1
            saved=set(db.scalars(select(Visit.event_id)))
            candidates=list(db.scalars(select(Event).where(Event.created_at<day)))
            for e in candidates:
                if e.id in saved or e.id in protected_events:continue
                # Source evidence belonging to a retained completed visit stays with it.
                linked=db.scalar(select(ExitObservation.id).where(ExitObservation.track_ref==e.track_ref,ExitObservation.visit_id.is_not(None)))
                if linked:continue
                erase_event(db,e);counts['events']+=1
            db.flush()
            refs=set(db.scalars(select(Event.snapshot_id).where(Event.snapshot_id.is_not(None))))
            refs.update(db.scalars(select(ResidentFace.snapshot_id).join(Resident,Resident.id==ResidentFace.resident_id).where(ResidentFace.active.is_(True),Resident.active.is_(True),ResidentFace.snapshot_id.is_not(None))))
            grace=moment-timedelta(minutes=c.orphan_grace_minutes)
            for s in db.scalars(select(Snapshot).where(Snapshot.created_at<grace)):
                if s.id in refs:continue
                if not db.scalar(select(FileDeletion.id).where(FileDeletion.path==s.path)):db.add(FileDeletion(path=s.path))
                db.delete(s);counts['snapshots']+=1
            db.execute(delete(OTPSend).where(OTPSend.created_at<moment-timedelta(days=2)))
            # Remove only expired, consumed/failed OTPs; pending active approvals remain intact.
            db.execute(delete(DeliveryOTP).where(DeliveryOTP.expires_at<moment-timedelta(days=1)))
            db.execute(delete(CleanupRun).where(CleanupRun.created_at<moment-timedelta(days=90)))
            db.commit()
        with sessions() as db:
            refs=set(db.scalars(select(Snapshot.path)))|set(db.scalars(select(Video.path)))
            for item in list(db.scalars(select(FileDeletion).limit(500))):
                if item.path in refs:db.delete(item);continue
                try:storage.remove(item.path);db.delete(item);counts['files']+=1
                except (OSError,ValueError):counts['file_failures']+=1
            # Orphan scan is restricted to generated photo files; uploaded videos are retained.
            for folder in ('temporary','snapshots'):
                for p in (storage.root/folder).iterdir():
                    try:
                        if p.is_symlink() or not p.is_file() or p.suffix.lower() not in ('.jpg','.jpeg','.png','.part'):continue
                        key=p.relative_to(storage.root).as_posix()
                        if key not in refs and p.stat().st_mtime<grace.timestamp():storage.remove(key);counts['files']+=1
                    except (OSError,ValueError):counts['file_failures']+=1
            # Upload deletion is only explicit; retry previously marked deleted videos.
            for v in db.scalars(select(Video).where(Video.status=='DELETED')):
                try:storage.remove(v.path)
                except OSError:counts['file_failures']+=1
            last=db.scalar(select(CleanupRun).order_by(CleanupRun.created_at.desc()).limit(1))
            if any(counts.values()) or last is None or last.created_at.date()!=moment.date():db.add(CleanupRun(counts=counts))
            db.commit()
        if counts['snapshots']:
            from .auto_exit import reference_vector
            reference_vector.cache_clear()
    finally:_guard.release()

def erase_event(db,e):
    db.execute(delete(DeliveryOTP).where(DeliveryOTP.event_id==e.id))
    db.execute(delete(Audit).where(Audit.event_id==e.id))
    db.execute(delete(Detection).where(Detection.track_ref==e.track_ref))
    db.execute(delete(ExitObservation).where(ExitObservation.track_ref==e.track_ref,ExitObservation.visit_id.is_(None)))
    db.delete(e);db.flush()
