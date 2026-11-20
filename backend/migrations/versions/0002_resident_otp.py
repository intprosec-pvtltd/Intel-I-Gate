"""Encrypted resident contacts and event-bound delivery approval codes."""
from alembic import op
import sqlalchemy as sa
revision='0002_resident_otp'
down_revision='0001'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('residents',sa.Column('phone_encrypted',sa.Text(),nullable=True))
    op.add_column('residents',sa.Column('revision',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('delivery_otps',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('event_id',sa.String(36),sa.ForeignKey('pending_events.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('resident_id',sa.String(36),sa.ForeignKey('residents.id'),nullable=False),
        sa.Column('requested_by',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('destination_digest',sa.String(64),nullable=False),
        sa.Column('code_digest',sa.String(64),nullable=True),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('sent_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('verified_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('consumed_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('state',sa.String(20),nullable=False))
    op.create_index('ix_delivery_otps_created_at','delivery_otps',['created_at'])
    op.create_table('otp_send_limits',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('recipient_digest',sa.String(64),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False))
    op.create_index('ix_otp_send_limits_created_at','otp_send_limits',['created_at'])
    op.create_index('ix_otp_send_limits_recipient_digest','otp_send_limits',['recipient_digest'])
    op.create_index('ix_otp_send_limits_actor_id','otp_send_limits',['actor_id'])

def downgrade():
    op.drop_table('otp_send_limits')
    op.drop_table('delivery_otps')
    op.drop_column('residents','revision')
    op.drop_column('residents','phone_encrypted')
