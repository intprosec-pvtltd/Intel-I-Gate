"""Update only realtime knobs; preserve database, authentication and camera allowlists."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--device',choices=['cpu','cuda:0'],required=True)
    parser.add_argument('--dino-device',choices=['cpu','cuda:0'],required=True)
    parser.add_argument('--inference-fps',type=float,default=5)
    parser.add_argument('--preview-fps',type=int,default=25)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    path=root/'backend/.env'
    if not path.is_file():raise SystemExit('backend/.env is missing. Keep your existing configured .env before applying this update.')
    if not .2<=args.inference_fps<=10 or not 1<=args.preview_fps<=30:raise SystemExit('Use AI FPS 0.2–10 and preview FPS 1–30.')
    settings={'DEVICE':args.device,'DINO_DEVICE':args.dino_device,'INFERENCE_FPS':str(args.inference_fps),'PREVIEW_FPS':str(args.preview_fps),'DINO_INTERVAL':'3','DELIVERY_THRESHOLD':'0.5','DELIVERY_HITS':'3','DELIVERY_MIN_SPAN':'2','DELIVERY_WINDOW':'15','DELIVERY_RESULT_TTL':'15','OVERLAY_TTL':'1','MAX_PREVIEW_PEERS':'4'}
    lines=[];seen=set()
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key=line.partition('=')[0].strip()
        if key in settings:
            if key not in seen:lines.append(key+'='+settings[key]);seen.add(key)
        else:lines.append(line)
    lines.extend(key+'='+value for key,value in settings.items() if key not in seen)
    candidate='\n'.join(lines)+'\n'
    sys.path.insert(0,str(root/'backend'))
    from dotenv import dotenv_values
    from io import StringIO
    from app.config import Settings
    try:Settings(_env_file=None,**{k.lower():v for k,v in dotenv_values(stream=StringIO(candidate)).items() if v is not None})
    except Exception:raise SystemExit('Configuration validation failed. No changes made; check your existing .env locally.') from None
    backup=path.with_name('.env.realtime-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path,backup)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.realtime-',delete=False) as out:
            temp=Path(out.name);out.write(candidate);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp and temp.exists():temp.unlink()
    print('Realtime settings updated. Existing database credentials, keys and camera allowlists preserved.')
    print('A private .env backup was created beside .env. Do not share that backup.')
    print('Restart the backend; start both cameras and check measured FPS and result age.')


if __name__=='__main__':main()
