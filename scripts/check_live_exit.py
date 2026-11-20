"""Read-only live-exit readiness check. Does not print credentials or camera URLs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select,func
from app.config import Settings
from app.database import database
from app.models import Camera,Visit,Event,Snapshot

c=Settings()
for key in ('ai_enabled','biometric_enabled','auto_exit_enabled','auto_test_exit_enabled','auto_exit_confirmations','auto_exit_min_span','auto_exit_min_entry_seconds','auto_exit_max_frame_age'):
    print(key, '=',getattr(c,key))
engine,sessions=database(c.database_url)
try:
    with sessions() as db:
        print('\nCameras:')
        for camera in db.scalars(select(Camera)):
            print(camera.name,'| purpose:',camera.purpose,'| enabled:',camera.enabled,'| status:',camera.status,'| exit line:',bool((camera.zones or {}).get('exit')))
        live=select(func.count()).select_from(Visit).where(Visit.status=='ENTRY_RECORDED',Visit.historical.is_(False))
        print('\nActive LIVE visits:',db.scalar(live))
        ready=select(func.count()).select_from(Visit).join(Event,Event.id==Visit.event_id).join(Snapshot,Snapshot.id==Event.snapshot_id).where(Visit.status=='ENTRY_RECORDED',Visit.historical.is_(False),Event.state=='ENTRY_RECORDED',Snapshot.approved.is_(True),Snapshot.deleted.is_(False),Snapshot.embedding_encrypted.is_not(None))
        print('Active LIVE visits with approved face references:',db.scalar(ready))
        print('A reference being present does not guarantee an acceptable or unique face match.')
finally:engine.dispose()
