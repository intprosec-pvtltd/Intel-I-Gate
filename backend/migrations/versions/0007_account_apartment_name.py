"""Optional apartment name for existing and new accounts."""
from alembic import op
import sqlalchemy as sa
revision='0007_account_apartment_name'
down_revision='0006_resident_faces'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('apartment_name',sa.String(120),nullable=True))

def downgrade():
    op.drop_column('users','apartment_name')
