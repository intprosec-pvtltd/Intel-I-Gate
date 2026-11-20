"""Resident face enrollment independent of visitor retention."""
from alembic import op
import sqlalchemy as sa
revision='0006_resident_faces'
down_revision='0005_sessions_retention'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('resident_faces',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,index=True),
        sa.Column('resident_id',sa.String(36),sa.ForeignKey('residents.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('snapshot_id',sa.String(36),sa.ForeignKey('snapshots.id',ondelete='SET NULL')),
        sa.Column('embedding_encrypted',sa.Text()),
        sa.Column('enrolled_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('active',sa.Boolean(),nullable=False),
        sa.Column('consent_at',sa.DateTime(timezone=True),nullable=False))

def downgrade():op.drop_table('resident_faces')
