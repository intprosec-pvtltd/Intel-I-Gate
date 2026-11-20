from pathlib import Path
from uuid import uuid4
import os,shutil
class Storage:
    def __init__(self,root):
        self.root=Path(root).resolve()
        for name in ('uploads','snapshots','temporary'):(self.root/name).mkdir(parents=True,exist_ok=True)
    def path(self,key):
        p=(self.root/key).resolve()
        if not p.is_relative_to(self.root) or p==self.root:raise ValueError('Unsafe storage path')
        return p
    def space(self):
        if shutil.disk_usage(self.root).free<256*1048576:raise OSError('Insufficient disk space')
    def put(self,data,folder='temporary',suffix='.jpg'):
        self.space();key=f'{folder}/{uuid4().hex}{suffix}';p=self.path(key);tmp=p.with_suffix('.part')
        try:
            with tmp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(tmp,p)
        finally:tmp.unlink(missing_ok=True)
        return key
    def remove(self,key):self.path(key).unlink(missing_ok=True)
