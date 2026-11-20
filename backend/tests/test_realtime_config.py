import subprocess
from pathlib import Path
import shutil
import sys
from cryptography.fernet import Fernet


def test_configurator_preserves_secrets_allowlists_and_backup(tmp_path):
    root=Path(__file__).resolve().parents[2]
    (tmp_path/'scripts').mkdir();(tmp_path/'backend').mkdir()
    shutil.copy2(root/'scripts/configure_realtime.py',tmp_path/'scripts/configure_realtime.py')
    shutil.copytree(root/'backend/app',tmp_path/'backend/app',ignore=shutil.ignore_patterns('__pycache__'))
    secret='private-fixture-key-'*3
    original='SECRET_KEY='+secret+'\nENCRYPTION_KEY='+Fernet.generate_key().decode()+'\nCAMERA_ALLOW_CIDRS=192.168.1.50/32,192.168.1.51/32\n# local note\n'
    path=tmp_path/'backend/.env';path.write_text(original)
    result=subprocess.run([sys.executable,str(tmp_path/'scripts/configure_realtime.py'),'--device','cuda:0','--dino-device','cpu'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'SECRET_KEY='+secret in path.read_text()
    assert 'CAMERA_ALLOW_CIDRS=192.168.1.50/32,192.168.1.51/32' in path.read_text()
    assert 'PREVIEW_FPS=25' in path.read_text() and 'DINO_DEVICE=cpu' in path.read_text()
    assert secret not in result.stdout+result.stderr
    assert next(path.parent.glob('.env.realtime-backup-*')).read_text()==original
