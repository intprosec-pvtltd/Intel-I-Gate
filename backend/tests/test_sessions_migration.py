import importlib.util
from pathlib import Path
from sqlalchemy import create_engine,text,inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_sessions_preserves_login_and_backfills_completed_times(tmp_path):
 engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'));root=Path(__file__).resolve().parents[1]/'migrations/versions'
 with engine.begin() as conn:
  with Operations.context(MigrationContext.configure(conn)):
   for name in ['0001_initial','0002_resident_otp','0003_apartment_map','0004_video_tests_email','0005_sessions_retention']:
    spec=importlib.util.spec_from_file_location(name,root/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    if name=='0005_sessions_retention':
     conn.execute(text("INSERT INTO users(id,created_at,username,email,password_hash,role,active,token_version) VALUES ('admin','2026-01-01','admin','admin@example.test','unchanged-hash','admin',1,0)"))
     conn.execute(text("INSERT INTO pending_events(id,created_at,track_ref,state,candidate_status,evidence) VALUES ('entry','2026-01-01','fixture','COMPLETED','GUARD_CONFIRMED','{}')"))
     conn.execute(text("INSERT INTO visits(id,created_at,event_id,resident_name,flat,guard_id,company,notes,entry_at,exit_at,historical,status) VALUES ('visit','2026-01-01','entry','Resident','A-101','admin','','','2026-01-01','2026-01-02',0,'COMPLETED')"))
    m.upgrade()
   assert conn.execute(text('SELECT password_hash FROM users')).scalar()=='unchanged-hash'
   assert conn.execute(text('SELECT completed_at FROM visits')).scalar()=='2026-01-02'
   assert {'visit_alerts','pending_file_deletions','cleanup_runs'}<=set(inspect(conn).get_table_names())
 engine.dispose()
