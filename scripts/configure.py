from pathlib import Path
import secrets
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'backend/.env'
if target.exists():raise SystemExit('backend/.env exists; retained unchanged.')
text=(ROOT/'backend/.env.example').read_text().replace('SECRET_KEY=GENERATE_ME','SECRET_KEY='+secrets.token_urlsafe(48)).replace('ENCRYPTION_KEY=GENERATE_ME','ENCRYPTION_KEY='+Fernet.generate_key().decode())
target.write_text(text)
print('Created backend/.env. Set DATABASE_URL and CAMERA_ALLOW_CIDRS before startup.')
