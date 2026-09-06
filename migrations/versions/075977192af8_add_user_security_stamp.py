"""Add users.security_stamp for session invalidation on password change

Revision ID: 075977192af8
Revises: 246e3823b701
Create Date: 2026-09-06 00:00:00.000000

Flask-Login sessions here are stateless signed cookies with no server-side
revocation, so resetting/changing a password previously did nothing to an
already-issued session cookie (e.g. from a stolen device) - defeating the
whole point of "reset your password if you think someone else has access."
User.get_id() now returns "<id>.<security_stamp>"; set_password() rotates
the stamp, so any cookie signed before the change fails the login_manager
user_loader's comparison and is treated as logged out.

Every existing user gets a distinct random stamp here (not one shared
constant) - this also means every currently active session cookie in the
wild is invalidated by this migration alone, once (a one-time, deliberate
consequence of closing the gap, not a bug).
"""
import secrets

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '075977192af8'
down_revision = '246e3823b701'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('security_stamp', sa.String(length=32), nullable=True))

    bind = op.get_bind()
    users = sa.table('users', sa.column('id', sa.Integer), sa.column('security_stamp', sa.String))
    for (user_id,) in bind.execute(sa.select(users.c.id)).fetchall():
        bind.execute(
            users.update().where(users.c.id == user_id).values(security_stamp=secrets.token_hex(16))
        )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('security_stamp', existing_type=sa.String(length=32), nullable=False)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('security_stamp')
