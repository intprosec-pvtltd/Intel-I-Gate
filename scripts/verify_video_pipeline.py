"""Actual video -> managed AI worker -> candidate -> idempotent save in isolated test DB.

Does not touch PostgreSQL or the application's production storage. Requires model assets.
"""
from pathlib import Path
import sys,argparse,tempfile,time,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from app.config import Settings
from app.models import Base,Video,Job,Event,Visit,User
from app.storage import Storage
from app.worker import Manager
from app.media import probe
from app.security import hasher
from app.schemas import Destination
from app import events
def main():
    p=argparse.ArgumentParser();p.add_argument('--video',required=True);p.add_argument('--timeout',type=int,default=180);a=p.parse_args()
    source=Path(a.video).resolve();base=Settings();report={'scope':'Isolated actual-model video integration test; not CCTV accuracy or PostgreSQL validation'}
    with tempfile.TemporaryDirectory(prefix='intel-video-test-') as temp:
        root=Path(temp);c=base.model_copy(update={'storage_dir':root/'storage','ai_enabled':True});storage=Storage(c.storage_dir)
        engine=create_engine('sqlite:///'+str(root/'test.db'),connect_args={'check_same_thread':False});Base.metadata.create_all(engine);sessions=sessionmaker(engine,expire_on_commit=False)
        meta=probe(source,c);key=storage.put(source.read_bytes(),'uploads','.video')
        with sessions() as db:
            user=User(username='isolated-test-guard',password_hash=hasher.hash('test-only-local-password'),role='guard');v=Video(filename='authorized-test-footage',path=key,size=source.stat().st_size,duration=meta['duration']);db.add_all([user,v]);db.commit();video_id=v.id;user_id=user.id
        worker=Manager(c,sessions,storage);worker.start();worker.add(video_id,False);start=time.monotonic()
        try:
            while time.monotonic()-start<a.timeout:
                with sessions() as db:
                    job=db.scalar(select(Job).where(Job.video_id==video_id));status=job.status;error=job.error
                if status in ('COMPLETED','FAILED'):break
                time.sleep(.25)
            if status!='COMPLETED':raise RuntimeError(f'Video did not complete: {status}; {error}')
            with sessions() as db:
                rows=list(db.scalars(select(Event).where(Event.video_id==video_id)));report['pending_events']=len(rows);report['snapshots']=sum(bool(e.snapshot_id) for e in rows)
                if rows:
                    data=Destination(delivery_confirmed=True,flat='TEST-ONLY',resident_name='Isolated test fixture')
                    first=events.save(db,rows[0].id,data,db.get(User,user_id));db.commit()
                    second=events.save(db,rows[0].id,data,db.get(User,user_id));db.commit()
                    if first.id!=second.id:raise RuntimeError('Idempotency failed')
                    report['guard_save']='PASS';report['historical_timestamp_preserved']=first.entry_at is None
                else:report['guard_save']='NOT_EXERCISED: no observed person in supplied footage'
            report['job']='COMPLETED';report['elapsed_seconds']=round(time.monotonic()-start,2);report['metrics']=worker.status()['metrics']
        finally:worker.close();engine.dispose()
    output=Path(__file__).resolve().parents[1]/'docs/integrated-model-test.json';output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
