"""Download official, revision-pinned models; validate against recorded SHA256."""
from pathlib import Path
import os,json,hashlib,urllib.request,argparse
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from huggingface_hub import HfApi,snapshot_download
ROOT=Path(__file__).resolve().parents[1];MODELS=ROOT/'backend/ai_models';LOCK=ROOT/'docs/model-lock.json'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def download(url,path):
    tmp=path.with_suffix('.part')
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'INTEL-I-Mini'})
        with urllib.request.urlopen(req,timeout=120) as response,tmp.open('wb') as out:
            while b:=response.read(1048576):out.write(b)
        if tmp.stat().st_size<10000:raise ValueError('Invalid checkpoint payload or LFS pointer')
        tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--faces-only',action='store_true');a=p.parse_args()
    MODELS.mkdir(parents=True,exist_ok=True);LOCK.parent.mkdir(exist_ok=True)
    lock=json.loads(LOCK.read_text()) if LOCK.exists() else {'revisions':{},'files':{}}
    revisions=lock['revisions']
    if 'opencv_zoo' not in revisions:
        req=urllib.request.Request('https://api.github.com/repos/opencv/opencv_zoo/commits/main',headers={'User-Agent':'INTEL-I-Mini'})
        with urllib.request.urlopen(req,timeout=30) as response:revisions['opencv_zoo']=json.load(response)['sha']
    sources={'face_detection_yunet_2023mar.onnx':f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{revisions["opencv_zoo"]}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx','face_recognition_sface_2021dec.onnx':f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{revisions["opencv_zoo"]}/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'}
    if not a.faces_only:sources['yolov8m.pt']='https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt';revisions['ultralytics_assets']='v8.3.0'
    def record(path,**extra):
        name=path.relative_to(MODELS).as_posix();digest=sha(path);old=lock['files'].get(name)
        if old and old['sha256']!=digest:raise ValueError('Checksum mismatch: '+name)
        lock['files'][name]={'sha256':digest,'bytes':path.stat().st_size,**extra};LOCK.write_text(json.dumps(lock,indent=2));print('Verified',name,flush=True)
    for name,url in sources.items():
        path=MODELS/name
        if not path.is_file():print('Downloading',name,flush=True);download(url,path)
        record(path,source=url)
    if not a.faces_only:
        repo='IDEA-Research/grounding-dino-tiny';revision=revisions.get('grounding_dino') or HfApi().model_info(repo).sha;revisions['grounding_dino']=revision;LOCK.write_text(json.dumps(lock,indent=2))
        snapshot_download(repo,revision=revision,local_dir=MODELS/'grounding_dino_tiny',allow_patterns=['*.json','*.safetensors','*.txt','*.model','LICENSE*','README*'])
        for path in (MODELS/'grounding_dino_tiny').rglob('*'):
            if path.is_file() and not any(s.startswith('.') for s in path.relative_to(MODELS).parts):record(path,revision=revision)
    print('All requested models downloaded and checksummed')
if __name__=='__main__':main()
