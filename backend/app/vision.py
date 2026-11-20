"""Real models; owned and called only by the single inference thread."""
from collections import defaultdict,deque
from types import SimpleNamespace
from pathlib import Path
from .delivery import DeliveryWorker, EvidenceWindow
import time,math,json

def crossing(previous,current,line):
    if previous is None or line is None:return False
    x1,y1,x2,y2=line
    def side(p):return (x2-x1)*(p[1]-y1)-(y2-y1)*(p[0]-x1)
    a,b=side(previous),side(current)
    if not(a<-.005 and b>=.005):return False
    t=-a/(b-a);p=(previous[0]+t*(current[0]-previous[0]),previous[1]+t*(current[1]-previous[1]))
    d=((p[0]-x1)*(x2-x1)+(p[1]-y1)*(y2-y1))/((x2-x1)**2+(y2-y1)**2)
    return 0<=d<=1

def passport_crop(frame,face):
    """Return only source pixels, with head room and upper-body context.

    Target 7:9 portrait framing. At image boundaries the available crop may
    have a different ratio; never stretch pixels or invent missing shoulders.
    Recognition and quality scoring must continue to use the tight face.
    """
    x,y,w,h=(float(v) for v in face[:4])
    if not all(math.isfinite(v) for v in (x,y,w,h)) or w<=0 or h<=0:
        raise ValueError('Invalid face bounds')
    image_h,image_w=frame.shape[:2]
    target_h=max(2.4*h,2.0*w*9/7)
    crop_w=min(image_w,max(1,math.ceil(target_h*7/9)))
    crop_h=min(image_h,max(1,math.ceil(target_h)))
    left=max(0,min(image_w-crop_w,math.floor(x+w/2-crop_w/2)))
    top=max(0,min(image_h-crop_h,math.floor(y-.35*h)))
    return frame[top:top+crop_h,left:left+crop_w].copy()

class FaceService:
    def __init__(self,c):
        import cv2
        self.c=c
        self.detector=cv2.FaceDetectorYN.create(str(c.model_dir/'face_detection_yunet_2023mar.onnx'),'',(320,320),.8)
        self.recognizer=cv2.FaceRecognizerSF.create(str(c.model_dir/'face_recognition_sface_2021dec.onnx'),'')
    def single_snapshot_embedding(self,frame):
        """Called by the inference thread only; ambiguous manual photos stay manual."""
        import cv2,numpy as np
        if not self.c.biometric_enabled:return None
        self.detector.setInputSize((frame.shape[1],frame.shape[0]));_,faces=self.detector.detect(frame)
        if faces is None or len(faces)!=1:return None
        face=faces[0];x,y,w,h=(float(v) for v in face[:4])
        if not all(math.isfinite(v) for v in (x,y,w,h)) or min(w,h)<self.c.face_min_size:return None
        crop=frame[max(0,int(y)):min(frame.shape[0],int(y+h)),max(0,int(x)):min(frame.shape[1],int(x+w))]
        if not crop.size:return None
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        if float(cv2.Laplacian(gray,cv2.CV_64F).var())<25 or not 25<float(gray.mean())<235 or float(np.mean((gray<10)|(gray>245)))>.5:return None
        result=self.recognizer.feature(self.recognizer.alignCrop(frame,face)).flatten()
        if result.shape!=(128,) or not np.isfinite(result).all() or float(np.linalg.norm(result))<1e-9:return None
        return result.tolist()

    def candidates(self,frame,boxes):
        import cv2,numpy as np
        self.reasons={tid:'FACE_NOT_DETECTED' for tid in boxes}
        if not boxes:return {}
        self.detector.setInputSize((frame.shape[1],frame.shape[0]));_,faces=self.detector.detect(frame);out={}
        if faces is None:return out
        for face in faces:
            x,y,w,h=face[:4];cx,cy=x+w/2,y+h/2
            owners=[tid for tid,b in boxes.items() if b[0]<=cx<=b[2] and b[1]<=cy<=b[1]+.65*(b[3]-b[1])]
            if len(owners)!=1:
                for tid in owners:self.reasons[tid]='AMBIGUOUS_FACE_OWNER'
                continue
            crop=frame[max(0,int(y)):min(frame.shape[0],int(y+h)),max(0,int(x)):min(frame.shape[1],int(x+w))]
            if not crop.size or min(crop.shape[:2])<self.c.face_min_size:
                self.reasons[owners[0]]='FACE_TOO_SMALL';continue
            gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY);sharp=float(cv2.Laplacian(gray,cv2.CV_64F).var());light=float(gray.mean())
            clipped=float(np.mean((gray<10)|(gray>245)));eyes=face[4:8].reshape(2,2);nose=face[8:10]
            distance=max(float(np.linalg.norm(eyes[1]-eyes[0])),1)
            tilt=abs(float(eyes[1,1]-eyes[0,1]))/distance
            symmetry=abs(float(np.linalg.norm(nose-eyes[0])-np.linalg.norm(nose-eyes[1])))/distance
            if sharp<25 or not 25<light<235 or clipped>.5 or tilt>.6:
                self.reasons[owners[0]]=('FACE_BLURRED' if sharp<25 else 'FACE_POOR_LIGHTING' if not 25<light<235 or clipped>.5 else 'FACE_TILTED');continue
            quality=math.log1p(sharp)*min(1,min(crop.shape[:2])/120)*(1-clipped)/(1+tilt+symmetry)
            tid=owners[0]
            if tid in out and out[tid]['quality']>=quality:continue
            embedding=None
            if self.c.biometric_enabled:embedding=self.recognizer.feature(self.recognizer.alignCrop(frame,face)).flatten().tolist()
            portrait=passport_crop(frame,face)
            ok,jpeg=cv2.imencode('.jpg',portrait,[cv2.IMWRITE_JPEG_QUALITY,92])
            if ok:self.reasons[tid]='CAPTURED'
            if ok:out[tid]={'quality':quality,'metrics':{'framing':'passport_v2','image_width':int(portrait.shape[1]),'image_height':int(portrait.shape[0]),'sharpness':sharp,'brightness':light,'clipping':clipped,'pose_proxy':symmetry,'tilt_proxy':tilt,'confidence':float(face[-1])},'jpeg':jpeg.tobytes(),'embedding':embedding}
        return out

class Pipeline:
    def __init__(self,c):
        import torch
        from ultralytics import YOLO
        self.c=c;torch.set_num_threads(4)
        if (c.device.startswith('cuda') or c.dino_device.startswith('cuda')) and not torch.cuda.is_available():raise RuntimeError('CUDA requested but unavailable')
        self.yolo=YOLO(str(c.model_dir/'yolov8m.pt'));self.face=FaceService(c)
        self.delivery_worker=DeliveryWorker(c)
        self.sources={};self.delivery_errors={};self.timings=defaultdict(lambda:deque(maxlen=100));self.delivery_error=None
    def timed(self,name,fn):
        start=time.perf_counter();value=fn();self.timings[name].append((time.perf_counter()-start)*1000);return value
    def forget(self,key):
        self.sources.pop(key,None)
        self.delivery_errors.pop(key,None)
        self.delivery_worker.forget(key)
    def close(self):self.delivery_worker.close()
    def pending_delivery(self,key):return self.delivery_worker.pending(key)
    def poll_delivery(self,key,live=True):
        result=self.delivery_worker.take(key)
        state=self.sources.get(key)
        if result is None or state is None:return []
        seconds,submitted,objects,error=result
        if error:
            self.delivery_errors[key]=error;return []
        self.delivery_errors.pop(key,None)
        if live and time.monotonic()-submitted>self.c.delivery_result_ttl:return []
        out=[]
        for tid,clues in objects.items():
            r=state['tracks'].get(tid)
            if r is None or r['seen']-seconds>self.c.delivery_window:continue
            r['evidence'].observe(seconds,clues)
            r['clues']=clues
            row=dict(r['row']);row['face']=None;row['entry']=row['exit']=False
            row['objects']=clues;row['possible']=r['evidence'].possible(r['seen'])
            r['row']=row;out.append(row)
        return out
    def new_tracker(self):
        import yaml
        from ultralytics.trackers.byte_tracker import BYTETracker
        opts=yaml.safe_load((self.c.model_dir/'bytetrack.yaml').read_text())
        return BYTETracker(SimpleNamespace(**opts),frame_rate=max(1,int(self.c.inference_fps)))
    def process(self,key,frame,seconds,zones):
        from ultralytics.trackers.basetrack import BaseTrack
        if key not in self.sources:self.sources[key]={'tracker':self.new_tracker(),'counter':0,'tracks':{},'dino_at':-100}
        state=self.sources[key]
        result=self.timed('yolo_ms',lambda:self.yolo.predict(frame,classes=[0],conf=.1,device=self.c.device,imgsz=640,verbose=False)[0])
        # Ultralytics allocates IDs globally. Swap counters only in this serialized thread.
        BaseTrack._count=state['counter'];tracked=state['tracker'].update(result.boxes.cpu().numpy(),frame);state['counter']=BaseTrack._count
        boxes={int(t[4]):[float(x) for x in t[:4]] for t in tracked if float(t[5])>=.25}
        faces=self.timed('yunet_sface_ms',lambda:self.face.candidates(frame,boxes))
        if boxes and not zones.get('_face_only') and seconds-state['dino_at']>=self.c.dino_interval:
            if self.delivery_worker.submit(key,frame,boxes,seconds):state['dino_at']=seconds
        out=[]
        for tid,box in boxes.items():
            r=state['tracks'].setdefault(tid,{'seen':seconds,'evidence':EvidenceWindow(self.c.delivery_hits,self.c.delivery_min_span,self.c.delivery_window),'clues':[],'point':None,'best':0})
            r['seen']=seconds
            point=((box[0]+box[2])/2/frame.shape[1],box[3]/frame.shape[0])
            entry=crossing(r['point'],point,zones.get('entry'));exit_seen=crossing(r['point'],point,zones.get('exit'));r['point']=point
            face=faces.get(tid)
            exit_embedding=face.get('embedding') if face else None
            if face and face['quality']<=r['best']:face=None
            if face:r['best']=face['quality']
            row={'exit_embedding':exit_embedding,'track_id':tid,'box':box,'face':face,'face_reason':self.face.reasons.get(tid,'FACE_NOT_DETECTED'),'objects':r['clues'],'possible':r['evidence'].possible(seconds),'entry':entry,'exit':exit_seen}
            r['row']={**row,'face':None,'exit_embedding':None};out.append(row)
        for tid in list(state['tracks']):
            if seconds-state['tracks'][tid]['seen']>60:del state['tracks'][tid]
        return out
    def metrics(self):
        import torch,psutil,sys
        try:
            if sys.platform.startswith('linux'):
                line=next(x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('VmRSS:'));rss=round(int(line.split()[1])/1024,1)
            else:rss=round(psutil.Process().memory_info().rss/1048576,1)
        except (OSError,psutil.Error,StopIteration):rss=None
        return {'latencies_ms':{k:{'mean':round(sum(v)/len(v),2),'samples':len(v)} for k,v in self.timings.items() if v},'rss_mb':rss,'cuda_allocated_mb':round(torch.cuda.memory_allocated()/1048576,1) if torch.cuda.is_available() else None,'delivery_error':self.delivery_worker.error,'delivery_state':self.delivery_worker.state,'delivery_ms':self.delivery_worker.last_ms}

def authorized_match(db,embedding,c):
    if not c.biometric_enabled or embedding is None:return None
    import numpy as np
    from sqlalchemy import select
    from .models import FaceProfile,Visit,now
    from .security import reveal
    q=np.asarray(embedding);scores=[]
    for profile in db.scalars(select(FaceProfile).where(FaceProfile.expires_at>now())):
        p=np.asarray(json.loads(reveal(profile.embedding_encrypted,c)));score=float(q@p/max(float(np.linalg.norm(q)*np.linalg.norm(p)),1e-9))
        scores.append((score,profile))
    scores.sort(key=lambda s:s[0],reverse=True)
    if not scores or scores[0][0]<c.face_match_threshold or len(scores)>1 and scores[0][0]-scores[1][0]<.08:return None
    score,p=scores[0];v=db.get(Visit,p.visit_id)
    return {'profile_id':p.id,'previous_visit_id':p.visit_id,'active_visit_id':v.id if v and v.status=='ENTRY_RECORDED' and not v.historical else None,'similarity':score,'requires_guard_review':True}
