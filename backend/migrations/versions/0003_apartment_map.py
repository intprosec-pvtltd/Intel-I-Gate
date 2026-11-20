"""Store administrator-configured apartment map locations."""
from alembic import op
import sqlalchemy as sa
revision='0003_apartment_map'
down_revision='0002_resident_otp'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('apartment_map_points',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('flat',sa.String(40),nullable=False,unique=True),
        sa.Column('x',sa.Float(),nullable=False),
        sa.Column('y',sa.Float(),nullable=False),
        sa.CheckConstraint('x >= 0 AND x <= 1',name='ck_map_point_x'),
        sa.CheckConstraint('y >= 0 AND y <= 1',name='ck_map_point_y'))
    op.create_index('ix_apartment_map_points_created_at','apartment_map_points',['created_at'])

def downgrade():
    op.drop_index('ix_apartment_map_points_created_at',table_name='apartment_map_points')
    op.drop_table('apartment_map_points')
