import importlib.util
from pathlib import Path
from sqlalchemy import create_engine,text,inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_preserves_passwords_and_backfills_email(tmp_path):
    root=Path(__file__).resolve().parents[1]/'migrations/versions'
    engine=create_engine('sqlite:///'+str(tmp_path/'upgrade.db'))
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            for name in ['0001_initial','0002_resident_otp','0003_apartment_map']:
                spec=importlib.util.spec_from_file_location(name,root/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.upgrade()
            conn.execute(text("INSERT INTO users(id,created_at,username,password_hash,role,active,token_version) VALUES ('old','2026-01-01','Admin@Example.test','same-hash','admin',1,0)"))
            conn.execute(text("INSERT INTO users(id,created_at,username,password_hash,role,active,token_version) VALUES ('legacy','2026-01-01','legacy-admin','legacy-hash','admin',1,0)"))
            spec=importlib.util.spec_from_file_location('new',root/'0004_video_tests_email.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.upgrade()
            assert conn.execute(text("SELECT email,password_hash,username FROM users WHERE id='old'")).one()==('admin@example.test','same-hash','Admin@Example.test')
            assert conn.execute(text("SELECT email,password_hash FROM users WHERE id='legacy'")).one()==(None,'legacy-hash')
            assert 'test_role' in {c['name'] for c in inspect(conn).get_columns('video_uploads')}
            assert next(c for c in inspect(conn).get_columns('exit_observations') if c['name']=='camera_id')['nullable']
    engine.dispose()
