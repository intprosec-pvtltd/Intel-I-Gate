"""Short-lived live-camera frames for guard-selected manual snapshots."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from uuid import uuid4
from fastapi import HTTPException

class CaptureCache:
    def __init__(self):
        self.items=OrderedDict()
        self.lock=Lock()
    def _expire(self):
        t=monotonic()
        for k,v in list(self.items.items()):
            if t-v[0]>120:self.items.pop(k,None)
    def create(self,event_id,user_id,jpeg):
        with self.lock:
            self._expire()
            for key,value in list(self.items.items()):
                if value[1:3]==(event_id,user_id):self.items.pop(key,None)
            token=uuid4().hex
            self.items[token]=(monotonic(),event_id,user_id,jpeg)
            while len(self.items)>16:self.items.popitem(last=False)
            return token
    def read(self,token,event_id,user_id):
        with self.lock:
            self._expire();item=self.items.get(token)
            if not item or item[1:3]!=(event_id,user_id):raise HTTPException(404,'Capture expired or unavailable. Capture a new frame.')
            return item[3]
    def discard(self,token):
        with self.lock:self.items.pop(token,None)

captures=CaptureCache()
