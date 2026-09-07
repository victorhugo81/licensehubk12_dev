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
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_index('api_key')
            batch_op.drop_column('api_key')
    else:
        # api_key was created as an unnamed sa.UniqueConstraint (see
        # 9b65b743672a) - MySQL auto-names that after the column ('api_key'),
        # but SQLite leaves it anonymous, so a naming_convention is needed
        # for batch mode to address it.
        naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table(
            'users', schema=None, naming_convention=naming_convention
        ) as batch_op:
            batch_op.drop_constraint('uq_users_api_key', type_='unique')
            batch_op.drop_column('api_key')


def downgrade():
    bind = op.get_bind()
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_key', sa.String(length=64), nullable=True))
        if bind.dialect.name == "mysql":
            batch_op.create_index('api_key', ['api_key'], unique=True)
        else:
            batch_op.create_unique_constraint('uq_users_api_key', ['api_key'])
