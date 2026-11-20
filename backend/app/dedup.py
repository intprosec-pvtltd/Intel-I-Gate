"""Conservative, camera-local recovery from tracker ID changes."""
import json
from datetime import timedelta
from sqlalchemy import select
from .models import Event,Snapshot,now
from .auto_exit import vector
from .security import reveal

def overlap(a,b):
    if not a or not b or len(a)!=4 or len(b)!=4:return 0
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-area
    return area/union if union>0 else 0

def recover(db,camera_id,embedding,box,c):
    if not c.biometric_enabled:return None
    probe=vector(embedding)
    if probe is None:return None
    candidates=[];cutoff=(now()-timedelta(seconds=3)).timestamp()
    for event,snapshot in db.execute(select(Event,Snapshot).join(Snapshot,Snapshot.id==Event.snapshot_id).where(Event.camera_id==camera_id,Event.video_id.is_(None),Event.state.in_(('PENDING_VERIFICATION','NEEDS_REVIEW','ENTRY_RECORDED')),Snapshot.deleted.is_(False)).order_by(Event.created_at.desc()).limit(100)):
        evidence=event.evidence or {}
        if evidence.get('last_seen_epoch',0)<cutoff or overlap(box,evidence.get('box'))<.5:continue
        try:reference=vector(json.loads(reveal(snapshot.embedding_encrypted,c)))
        except Exception:continue
        if reference is not None:candidates.append((float(probe@reference),event))
    candidates.sort(key=lambda x:x[0],reverse=True)
    if candidates and candidates[0][0]>=.90 and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.15):return candidates[0][1]
    return None
