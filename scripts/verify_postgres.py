from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import text,inspect
from app.config import Settings
from app.database import database
from app.models import Base
engine,_=database(Settings().database_url)
with engine.connect() as c:
    version=c.scalar(text('SHOW server_version'))
    if not version.startswith('16.'):raise SystemExit('Expected PostgreSQL 16; found '+version)
    revision=c.scalar(text('SELECT version_num FROM alembic_version'))
    missing=set(Base.metadata.tables)-set(inspect(c).get_table_names())
    if revision!='0001' or missing:raise SystemExit('Schema mismatch: '+str((revision,missing)))
    print('PASS PostgreSQL',version,'schema revision',revision,'tables',len(Base.metadata.tables))
