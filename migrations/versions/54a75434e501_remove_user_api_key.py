"""Remove User.api_key (JSON API bearer-token feature removed)

Revision ID: 54a75434e501
Revises: d2ffc64c4d8f
Create Date: 2026-09-05 00:00:00.000000

The JSON API no longer authenticates state-changing requests with a
per-user bearer token - it now relies solely on the normal session
cookie, and the API blueprint is no longer CSRF-exempt (see
app/utils/api_auth.py, app/__init__.py). This drops the now-unused
column entirely, rather than leaving a dead field around.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '54a75434e501'
down_revision = 'd2ffc64c4d8f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('api_key')
        batch_op.drop_column('api_key')


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_key', sa.String(length=64), nullable=True))
        batch_op.create_index('api_key', ['api_key'], unique=True)
