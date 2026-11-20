import json,queue,threading,time
from collections import OrderedDict,deque
from uuid import uuid4
from sqlalchemy import select,update,or_,and_
from .models import Camera,Video,Job,Event,Snapshot,Detection,Visit,ExitObservation,now
from .security import protect,reveal,validate_camera_url
from .media import Decoder

class Source:
    def __init__(self,key,ident,live,zones):
        self.key,self.ident,self.live,self.zones=key,ident,live,zones
        self.epoch=uuid4().hex
        self.test_role=None
        self.stop=threading.Event();self.frames=queue.Queue(1);self.preview=None;self.last_frame=0;self.decoder=None;self.thread=None;self.eof=False;self.failed=False;self.duration=0;self.raw=None;self.raw_at=0;self.preview_at=0;self.analysis=None;self.processed=deque(maxlen=100);self.last_packet=None;self.packet_times={};self.last_rows=[];self.progress_at=0

class Manager:
    def __init__(self,c,sessions,storage):
        self.c,self.sessions,self.storage=c,sessions,storage
        self.video_previews=OrderedDict()
        self.embedding_attempts={};self.embedding_scan_at=0
        self.sources={};self.lock=threading.RLock();self.retired=queue.Queue();self.stop=threading.Event()
        self.pipeline=None;self.model_state='NOT_LOADED' if c.ai_enabled else 'DISABLED';self.error=None;self.measurements={}
        self.thread=threading.Thread(target=self.run,daemon=True,name='intel-inference')
    def start(self):
        with self.sessions() as db:
            db.execute(update(Camera).values(enabled=False,status='STOPPED',error=None))
            db.execute(update(Job).where(Job.status.in_(['RUNNING','QUEUED'])).values(status='INTERRUPTED',error='Server restarted; restart analysis'))
            db.execute(update(Video).where(Video.status.in_(['RUNNING','QUEUED'])).values(status='INTERRUPTED'));db.commit()
        self.thread.start()
    def camera_status(self,ident,status,error=None):
        with self.sessions() as db:
            row=db.get(Camera,ident)
            if row:row.status,row.error=status,error;db.commit()
    def job_status(self,ident,status,error=None,progress=None):
        with self.sessions() as db:
            row=db.get(Video,ident);job=db.scalar(select(Job).where(Job.video_id==ident))
            if row and job:
                row.status=job.status=status;job.error=error
                if progress is not None:job.progress=progress
                db.commit()
    def add(self,ident,live):
        key=('camera:' if live else 'video:')+ident
        with self.lock:
            if key in self.sources:return
            if len(self.sources)>=self.c.max_sources:raise ValueError('Source capacity reached')
            with self.sessions() as db:
                row=db.get(Camera if live else Video,ident)
                if not row:raise ValueError('Source not found')
                if not live and row.status in ('DELETED','EXPIRED'):raise ValueError('Video deleted or expired')
                if live:
                    url=validate_camera_url(reveal(row.rtsp_encrypted,self.c),self.c);row.enabled=True;row.status='CONNECTING'
                else:
                    url=str(self.storage.path(row.path));job=db.scalar(select(Job).where(Job.video_id==ident))
                    if not job:job=Job(video_id=ident);db.add(job)
                    job.status=row.status='RUNNING';job.progress=0;job.error=None
                source=Source(key,ident,live,row.zones if live else {})
                source.purpose=row.purpose if live else None
                if not live:source.duration=row.duration;source.test_role=row.test_role
                db.commit()
            if not live:self.video_previews.pop(ident,None)
            self.sources[key]=source;source.thread=threading.Thread(target=self.decode,args=(source,url),daemon=True);source.thread.start()
    def remove(self,ident,live=True):
        key=('camera:' if live else 'video:')+ident
        with self.lock:source=self.sources.pop(key,None)
        if source:
            source.stop.set();source.preview=None;self.retired.put(source.key+':'+source.epoch)
            if source.decoder:source.decoder.close()
            source.thread.join(timeout=5)
        if live:
            with self.sessions() as db:
                row=db.get(Camera,ident)
                if row:row.enabled=False;row.status='STOPPED';row.error=None;db.commit()
        else:self.job_status(ident,'CANCELLED')
    def decode(self,s,url):
        import cv2
        attempts=0;sequence=0;last_sample=-100;started=time.monotonic()
        while not s.stop.is_set():
            try:
                if attempts:
                    self.retired.put(s.key+':'+s.epoch);s.epoch=uuid4().hex;s.raw=None;s.analysis=None;s.last_packet=None;s.last_rows=[];s.packet_times={}
                    while not s.frames.empty():s.frames.get_nowait()
                s.decoder=Decoder(url,self.c,s.live)
                while not s.stop.is_set():
                    frame=s.decoder.read()
                    if frame is None:
                        if s.live:raise RuntimeError('Camera disconnected')
                        if s.decoder.process.wait(timeout=3)!=0:raise RuntimeError('Decode failed')
                        s.eof=True;return
                    s.last_frame=time.monotonic()
                    if s.live:
                        if s.preview is None:self.camera_status(s.ident,'CONNECTED')
                        s.raw=frame;s.raw_at=time.monotonic()
                        if s.raw_at-s.preview_at>=.2:
                            ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75]);s.preview=jpeg.tobytes() if ok else None;s.preview_at=s.raw_at
                        seconds=time.monotonic()-started
                        if seconds-last_sample<1/self.c.inference_fps:continue
                    else:seconds=sequence/self.c.inference_fps;sequence+=1
                    last_sample=seconds;s.packet_times[seconds]=time.monotonic()
                    if len(s.packet_times)>4:s.packet_times.pop(next(iter(s.packet_times)))
                    packet=(frame,seconds,now() if s.live else None,s.epoch)
                    if s.live:
                        try:s.frames.get_nowait()
                        except queue.Empty:pass
                        s.frames.put_nowait(packet)
                    else:
                        while not s.stop.is_set():
                            s.decoder.touch()
                            try:s.frames.put(packet,timeout=.5);break
                            except queue.Full:pass
                    attempts=0
            except Exception:
                s.preview=None
                if s.stop.is_set():return
                if not s.live:s.failed=s.eof=True;self.job_status(s.ident,'FAILED','Video decoding failed');return
                self.camera_status(s.ident,'RECONNECTING','Camera unavailable; retrying');attempts+=1;s.stop.wait(min(30,2**min(attempts,5)))
            finally:
                if s.decoder:s.decoder.close()
    def persist(self,s,rows,seconds,captured,epoch):
        from .vision import authorized_match
        with self.sessions() as db:
            for row in rows:
                ref=f'{s.key}:{epoch}:{row["track_id"]}'
                e=db.scalar(select(Event).where(Event.track_ref==ref).with_for_update())
                # Recognize residents before creating any new event or writing a JPEG.
                # Upload tests remain isolated from permanent resident enrollment.
                from .resident_faces import match_resident
                embedding=row.get('exit_embedding')
                if embedding is None and row.get('face'):embedding=row['face'].get('embedding')
                resident_id=match_resident(db,embedding,self.c) if s.live else None
                if resident_id and (e is None or e.state in ('PENDING_VERIFICATION','NEEDS_REVIEW','EXIT_REVIEW','RESIDENT')):
                    if e is not None:
                        e.state='RESIDENT';e.verification={'resident_id':resident_id}
                        observation=db.scalar(select(ExitObservation).where(ExitObservation.track_ref==ref,ExitObservation.visit_id.is_(None)))
                        if observation:observation.state='RESIDENT'
                    continue
                if e is not None and e.state=='RESIDENT':
                    from .models import ResidentFace,Resident
                    enrolled=db.scalar(select(ResidentFace.id).join(Resident,Resident.id==ResidentFace.resident_id).where(ResidentFace.resident_id==(e.verification or {}).get('resident_id'),ResidentFace.active.is_(True),Resident.active.is_(True)))
                    if self.c.biometric_enabled and self.c.resident_recognition_enabled and enrolled:continue
                    e.state='PENDING_VERIFICATION';e.verification={}

                if e is None and s.live and getattr(s,'purpose',None)=='Entry Gate':
                    from .dedup import recover
                    e=recover(db,s.ident,embedding,row.get('box'),self.c)
                    if e is not None:ref=e.track_ref
                if e is not None:
                    e.evidence={**(e.evidence or {}),'last_seen_epoch':now().timestamp()}
                if e is None:
                    exit_camera=db.get(Camera,s.ident) if s.live and self.c.auto_exit_enabled else None
                    exit_only=bool(exit_camera and exit_camera.purpose=='Exit Gate')
                    e=Event(track_ref=ref,camera_id=s.ident if s.live else None,video_id=None if s.live else s.ident,frame_seconds=seconds,captured_at=captured,state='EXIT_REVIEW' if exit_only or (not s.live and s.test_role=='exit') else 'PENDING_VERIFICATION');db.add(e);db.flush()
                if s.live and self.c.auto_exit_enabled and e.state in ('PENDING_VERIFICATION','NEEDS_REVIEW'):
                    camera=db.get(Camera,s.ident)
                    if camera and camera.purpose=='Exit Gate':e.state='EXIT_REVIEW'
                if e.state in ('PENDING_VERIFICATION','NEEDS_REVIEW','CONFIRMED','EXIT_REVIEW'):
                    if e.state!='CONFIRMED':e.candidate_status='POSSIBLE_DELIVERY' if row['possible'] else 'NEEDS_REVIEW'
                    evidence={**e.evidence,'last_seen_epoch':now().timestamp(),'objects':row['objects'],'box':row['box'],'face_reason':row.get('face_reason','FACE_NOT_DETECTED'),'analysis_run':epoch,'entry_crossing':row['entry'] or e.evidence.get('entry_crossing',False)}
                    if row['face'] and e.evidence.get('auto_photo_count',0)<3 and not e.evidence.get('manual_snapshot') and (not e.snapshot_id or not (existing_snapshot:=db.get(Snapshot,e.snapshot_id)) or existing_snapshot.deleted or row['face']['quality'] > existing_snapshot.quality * 1.10):
                        f=row['face'];evidence['auto_photo_count']=e.evidence.get('auto_photo_count',0)+1;evidence['face_reason']='CAPTURED';key=self.storage.put(f['jpeg']);match=authorized_match(db,f['embedding'],self.c)
                        snap=Snapshot(path=key,quality=f['quality'],metrics=f['metrics'],embedding_encrypted=protect(json.dumps(f['embedding']),self.c) if f['embedding'] else None)
                        db.add(snap);db.flush();e.snapshot_id=snap.id
                        if match:evidence['identity_suggestion']=match
                    if e.snapshot_id:evidence['face_reason']='CAPTURED'
                    e.evidence=evidence
                # A saved visit with no face can receive its first suitable face;
                # never overwrite an approved/saved snapshot or a rejected event.
                if e.state=='ENTRY_RECORDED' and not e.snapshot_id and row.get('face'):
                    f=row['face'];snap=Snapshot(path=self.storage.put(f['jpeg']),quality=f['quality'],metrics=f['metrics'],approved=True,embedding_encrypted=protect(json.dumps(f['embedding']),self.c) if f['embedding'] else None)
                    db.add(snap);db.flush();e.snapshot_id=snap.id
                if row['possible'] or row['entry'] or row['exit']:
                    if not db.scalar(select(Detection.id).where(Detection.track_ref==ref,Detection.frame_seconds>seconds-5).limit(1)):
                        db.add(Detection(source_key=s.key,track_ref=ref,frame_seconds=seconds,captured_at=captured,evidence={'objects':row['objects'],'entry':row['entry'],'exit':row['exit'],'analysis_run':epoch}))
                if not s.live and s.test_role=='exit' and e.state=='EXIT_REVIEW' and not db.scalar(select(ExitObservation.id).where(ExitObservation.track_ref==ref)):
                    db.add(ExitObservation(video_id=s.ident,camera_id=None,track_ref=ref,evidence={'test_mode':True,'video_seconds':seconds,'rule':'GUARD_REVIEW_REQUIRED'}))
                if s.live and row['exit'] and not db.scalar(select(ExitObservation.id).where(ExitObservation.track_ref==ref)):
                    visit=db.scalar(select(Visit).where(Visit.event_id==e.id,Visit.status=='ENTRY_RECORDED'))
                    match=e.evidence.get('identity_suggestion')
                    db.add(ExitObservation(camera_id=s.ident,track_ref=ref,visit_id=visit.id if visit else (match.get('active_visit_id') if match else None),evidence={'same_track':bool(visit),'identity_suggestion':match,'rule':'GUARD_REVIEW_REQUIRED'}))
                if s.live:
                    from .auto_exit import observe
                    observe(db,e,row.get('exit_embedding'),seconds,captured,self.c,crossed=row['exit'])
                elif s.test_role=='exit':
                    from .auto_exit import observe_test
                    db.flush()
                    observe_test(db,e,row.get('exit_embedding'),seconds,self.c)
            db.commit()
    def hydrate_active_embeddings(self):
        """Prepare saved/retaken reference photos without sharing model objects with API threads."""
        moment=time.monotonic()
        if moment-self.embedding_scan_at<5:return
        self.embedding_scan_at=moment
        if not self.c.biometric_enabled or not self.pipeline:return
        import cv2,numpy as np
        if len(self.embedding_attempts)>2000:self.embedding_attempts={key:value for key,value in self.embedding_attempts.items() if moment-value<60}
        with self.sessions() as db:
            rows=list(db.scalars(select(Snapshot).join(Event,Event.snapshot_id==Snapshot.id).join(Visit,Visit.event_id==Event.id).outerjoin(Video,Video.id==Event.video_id).where(Visit.status=='ENTRY_RECORDED',or_(and_(Visit.historical.is_(False),self.c.auto_exit_enabled),and_(Visit.historical.is_(True),Video.test_role=='entry',Event.camera_id.is_(None),self.c.auto_test_exit_enabled)),Snapshot.approved.is_(True),Snapshot.deleted.is_(False),Snapshot.embedding_encrypted.is_(None)).order_by(Snapshot.created_at.desc())))
            attempted=0
            for snapshot in rows:
                if attempted>=2:break
                if moment-self.embedding_attempts.get(snapshot.id,float('-inf'))<30:continue
                self.embedding_attempts[snapshot.id]=moment;attempted+=1
                try:
                    path=self.storage.path(snapshot.path)
                    if not path.is_file() or path.stat().st_size>8*1024*1024:continue
                    frame=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                    if frame is None:continue
                    embedding=self.pipeline.face.single_snapshot_embedding(frame)
                    if embedding is None:continue
                    snapshot.embedding_encrypted=protect(json.dumps(embedding),self.c)
                except Exception:
                    # Bad/expired files must not stop monitoring or overwrite the photo.
                    continue
            db.commit()

    def run(self):
        while not self.stop.wait(.03):
            while not self.retired.empty():
                key=self.retired.get_nowait()
                if self.pipeline:self.pipeline.forget(key)
            with self.lock:sources=list(self.sources.values())
            if not sources or not self.c.ai_enabled:continue
            if self.pipeline is None and self.model_state!='FAILED':
                self.model_state='LOADING'
                try:
                    from .vision import Pipeline
                    self.pipeline=Pipeline(self.c);self.model_state='READY'
                except Exception as exc:self.model_state='FAILED';self.error='Model loading failed ('+type(exc).__name__+'); run scripts/test_models.py'
            if self.pipeline and (self.c.auto_exit_enabled or self.c.auto_test_exit_enabled):
                try:self.hydrate_active_embeddings()
                except Exception:self.error='Reference photo processing unavailable; retry scheduled'
            sources.sort(key=lambda s:0 if getattr(s,'purpose',None)=='Exit Gate' else 1)
            for s in sources:
                if s.stop.is_set():continue
                if self.model_state=='FAILED':
                    if not s.live:self.fail_video(s,self.error)
                    continue
                key=s.key+':'+s.epoch
                updates=self.pipeline.poll_delivery(key,s.live)
                delivery_error=getattr(self.pipeline,'delivery_errors',{}).get(key)
                if not s.live and (delivery_error or self.pipeline.delivery_worker.state=='FAILED'):
                    self.fail_video(s,delivery_error or 'Delivery model failed to load; check assets and device settings, then restart backend');continue
                if updates and s.last_packet and not s.stop.is_set():
                    _,seconds,captured,epoch=s.last_packet
                    try:
                        self.persist(s,updates,seconds,captured,epoch)
                        changed={row['track_id']:row for row in updates}
                        s.last_rows=[changed.get(row['track_id'],row) for row in s.last_rows]
                        if not s.live:self.publish_video_preview(s.ident,s.last_packet[0],s.last_rows,seconds)
                        elif s.analysis:
                            s.analysis={**s.analysis,'rows':self.overlay_rows(s.last_rows)}
                    except Exception as exc:self.error='Evidence update failed ('+type(exc).__name__+')'
                # Offline videos wait for delivery evidence without blocking live sources.
                if not s.live and self.pipeline.pending_delivery(key):continue
                try:frame,seconds,captured,epoch=s.frames.get_nowait()
                except queue.Empty:
                    if s.eof and not s.live:
                        if not s.failed:self.job_status(s.ident,'COMPLETED',progress=100)
                        with self.lock:self.sources.pop(s.key,None)
                        self.pipeline.forget(s.key+':'+s.epoch)
                    continue
                if epoch!=s.epoch:continue
                try:
                    began=time.monotonic()
                    rows=self.pipeline.process(s.key+':'+epoch,frame,seconds,{**s.zones,'_face_only':getattr(s,'purpose',None)=='Exit Gate'})
                    s.last_packet=(frame,seconds,captured,epoch);s.last_rows=rows
                    if not s.stop.is_set():
                        if s.live:
                            s.processed.append(time.monotonic())
                            s.analysis={'camera_id':s.ident,'epoch':epoch,'captured_at':captured.isoformat() if captured else None,'updated_at':time.time(),'frame_at':s.packet_times.get(seconds,began),'processing_ms':round((time.monotonic()-began)*1000,2),'rows':self.overlay_rows(rows)}
                        self.persist(s,rows,seconds,captured,epoch)
                        if not s.live:self.publish_video_preview(s.ident,frame,rows,seconds)
                        if not s.live and time.monotonic()-s.progress_at>=1:
                            self.job_status(s.ident,'RUNNING',progress=min(99,100*seconds/max(s.duration,.1)));s.progress_at=time.monotonic()
                    self.measurements=self.pipeline.metrics()
                except Exception as exc:
                    self.error='Processing failed ('+type(exc).__name__+')'
                    if s.live:self.camera_status(s.ident,'AI_ERROR',self.error)
                    else:self.fail_video(s,self.error)
    def fail_video(self,s,message):
        self.job_status(s.ident,'FAILED',message);s.stop.set()
        if s.decoder:s.decoder.close()
        with self.lock:self.sources.pop(s.key,None)
        if self.pipeline:self.pipeline.forget(s.key+':'+s.epoch)
    def publish_video_preview(self,ident,frame,rows,seconds):
        """Publish only an actual analyzed frame. Keep bounded, temporary JPEGs in RAM."""
        import cv2
        height,width=frame.shape[:2];scale=min(1,960/width)
        image=cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale)))) if scale<1 else frame.copy()
        def rectangle(box,label,color):
            x1,y1,x2,y2=[round(float(x)*scale) for x in box]
            x1,x2=[max(0,min(image.shape[1]-1,x)) for x in (x1,x2)]
            y1,y2=[max(0,min(image.shape[0]-1,y)) for y in (y1,y2)]
            cv2.rectangle(image,(x1,y1),(x2,y2),color,2)
            cv2.putText(image,label,(x1,max(16,y1-7)),cv2.FONT_HERSHEY_SIMPLEX,.48,color,1,cv2.LINE_AA)
        for row in rows:
            color=(80,210,120) if row['possible'] else (230,190,80)
            rectangle(row['box'],f"Person #{row['track_id']} | "+('Possible delivery' if row['possible'] else 'Guard review'),color)
        cv2.putText(image,f"ANALYZED FRAME +{seconds:.1f}s | {len(rows)} tracked people",(12,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),2,cv2.LINE_AA)
        ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
        if not ok:return
        with self.lock:
            self.video_previews[ident]=(jpeg.tobytes(),seconds,uuid4().hex,time.monotonic())
            self.video_previews.move_to_end(ident)
            while len(self.video_previews)>16:self.video_previews.popitem(last=False)
            for key,value in list(self.video_previews.items()):
                if time.monotonic()-value[3]>900:self.video_previews.pop(key,None)
    def video_preview(self,ident):
        with self.lock:
            packet=self.video_previews.get(ident)
            if packet and time.monotonic()-packet[3]<=900:return packet[:3]
            self.video_previews.pop(ident,None)
            return None
    @staticmethod
    def overlay_rows(rows):
        from .media import WIDTH,HEIGHT
        return [{'track_id':r['track_id'],'box':[r['box'][0]/WIDTH,r['box'][1]/HEIGHT,r['box'][2]/WIDTH,r['box'][3]/HEIGHT],'possible':r['possible']} for r in rows]
    def raw_frame(self,ident):
        with self.lock:s=self.sources.get('camera:'+ident)
        if not s or s.stop.is_set() or s.raw is None or time.monotonic()-s.raw_at>3:return None
        return s.raw,s.raw_at,s.epoch
    def analysis_state(self):
        with self.lock:sources=list(self.sources.values())
        result=[];t=time.monotonic()
        for s in sources:
            if not s.live:continue
            item=dict(s.analysis or {'camera_id':s.ident,'epoch':s.epoch,'rows':[]})
            age=max(0,t-item.pop('frame_at',t)) if s.analysis else None
            item['result_age_ms']=round(age*1000,1) if age is not None else None
            if age is None or age>self.c.overlay_ttl:item['rows']=[]
            samples=[v for v in list(s.processed) if t-v<=10]
            item['actual_ai_fps']=round((len(samples)-1)/(samples[-1]-samples[0]),2) if len(samples)>1 else 0
            item['stale']=age is None or age>self.c.overlay_ttl
            result.append(item)
        return result
    def preview(self,ident):
        with self.lock:s=self.sources.get('camera:'+ident)
        return s.preview if s and time.monotonic()-s.last_frame<5 else None
    def status(self):return {'models':self.model_state,'error':self.error,'sources':len(self.sources),'worker_alive':self.thread.is_alive(),'metrics':self.measurements,'cameras':self.analysis_state(),'delivery_state':self.pipeline.delivery_worker.state if self.pipeline else 'NOT_LOADED'}
    def close(self):
        self.stop.set()
        with self.lock:sources=list(self.sources.values())
        for s in sources:self.remove(s.ident,s.live)
        if self.thread.is_alive():self.thread.join(timeout=15)
        if self.pipeline:self.pipeline.close()

