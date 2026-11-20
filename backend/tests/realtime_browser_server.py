"""Synthetic two-camera transport fixture ONLY. No model/accuracy benchmark."""
import asyncio
import os
import time
from pathlib import Path
from contextlib import asynccontextmanager
import numpy as np
import cv2
from fastapi import Depends
from app.security import current,protect
from app.models import Camera
from app.worker import Source
from .browser_server import app,sessions,c

with sessions() as db:
    for index in range(2):
        row=Camera(name=f'Test Gate {index+1}',location='Synthetic transport fixture',purpose='Entry Gate',enabled=True,status='CONNECTED',rtsp_encrypted=protect(f'rtsp://192.168.1.{50+index}/fixture',c),fingerprint=str(index)*64)
        db.add(row);db.flush()
        source=Source('camera:'+row.id,row.id,True,{})
        app.state.worker.sources[source.key]=source
    db.commit()
paused=False

async def produce():
    index=0
    while True:
        t=time.monotonic();index+=1
        for source in list(app.state.worker.sources.values()):
            image=np.zeros((540,960,3),np.uint8)
            x=(index*5)%700
            image[100:440,x:x+100]=[60,170,70]
            image[0:15,:]=index%255
            source.raw=image;source.raw_at=source.last_frame=t
            if index%5==0:
                ok,jpeg=cv2.imencode('.jpg',image);source.preview=jpeg.tobytes() if ok else None
            if not paused and index%5==0:
                source.processed.append(t)
                source.analysis={'camera_id':source.ident,'epoch':source.epoch,'updated_at':time.time(),'frame_at':t,'rows':[{'track_id':1,'box':[x/960,100/540,(x+100)/960,440/540],'possible':False}]}
        await asyncio.sleep(.04)

old=app.router.lifespan_context
@asynccontextmanager
async def lifespan(instance):
    async with old(instance):
        task=asyncio.create_task(produce())
        try:yield
        finally:task.cancel()
app.router.lifespan_context=lifespan

@app.post('/test/pause-ai')
def pause(user=Depends(current)):
    global paused
    paused=True
    return {'ok':True}
