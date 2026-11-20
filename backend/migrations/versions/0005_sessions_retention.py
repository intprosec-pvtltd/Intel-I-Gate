"""Visit deadlines, overdue responses and calendar cleanup."""
from alembic import op
import sqlalchemy as sa
revision='0005_sessions_retention'
down_revision='0004_video_tests_email'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('visits') as b:
        b.add_column(sa.Column('expected_exit_at',sa.DateTime(timezone=True)))
        b.add_column(sa.Column('completed_at',sa.DateTime(timezone=True)))
        b.create_index('ix_visits_expected_exit_at',['expected_exit_at'])
    # Backfill only real stored completion evidence; no fabricated exit time.
    op.execute(sa.text("UPDATE visits SET completed_at=COALESCE(exit_at,created_at) WHERE status='COMPLETED'"))
    from app.models import VisitAlert,FileDeletion,CleanupRun
    for table in (VisitAlert.__table__,FileDeletion.__table__,CleanupRun.__table__):table.create(op.get_bind())

def downgrade():
    for name in ('cleanup_runs','pending_file_deletions','visit_alerts'):op.drop_table(name)
    with op.batch_alter_table('visits') as b:
        b.drop_index('ix_visits_expected_exit_at');b.drop_column('completed_at');b.drop_column('expected_exit_at')
