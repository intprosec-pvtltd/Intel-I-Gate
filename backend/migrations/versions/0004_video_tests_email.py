"""Explicit video test roles, video exit observations and email authentication."""
import re
from alembic import op
import sqlalchemy as sa
revision='0004_video_tests_email'
down_revision='0003_apartment_map'
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    accounts=list(bind.execute(sa.text('SELECT id, username FROM users')))
    emails={};updates=[]
    for ident,username in accounts:
        value=username.strip().lower()
        if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',value):
            if value in emails:raise RuntimeError('Duplicate email accounts must be resolved before migration; nothing has been renamed.')
            emails[value]=ident;updates.append({'email':value,'ident':ident})
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('email',sa.String(100),nullable=True))
        batch.create_unique_constraint('uq_users_email',['email'])
    for values in updates:bind.execute(sa.text('UPDATE users SET email=:email WHERE id=:ident'),values)
    with op.batch_alter_table('video_uploads') as batch:
        batch.add_column(sa.Column('test_role',sa.String(10),nullable=True))
        batch.create_check_constraint('ck_video_test_role',"test_role IS NULL OR test_role IN ('entry','exit')")
    with op.batch_alter_table('exit_observations') as batch:
        batch.alter_column('camera_id',existing_type=sa.String(36),nullable=True)
        batch.add_column(sa.Column('video_id',sa.String(36),nullable=True))
        batch.create_foreign_key('fk_exit_video','video_uploads',['video_id'],['id'])

def downgrade():
    with op.batch_alter_table('exit_observations') as batch:
        batch.drop_constraint('fk_exit_video',type_='foreignkey')
        batch.drop_column('video_id')
    # Null-camera video observations cannot exist in the earlier schema.
    op.execute(sa.text('DELETE FROM exit_observations WHERE camera_id IS NULL'))
    with op.batch_alter_table('exit_observations') as batch:
        batch.alter_column('camera_id',existing_type=sa.String(36),nullable=False)
    with op.batch_alter_table('video_uploads') as batch:
        batch.drop_constraint('ck_video_test_role',type_='check')
        batch.drop_column('test_role')
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('uq_users_email',type_='unique')
        batch.drop_column('email')
