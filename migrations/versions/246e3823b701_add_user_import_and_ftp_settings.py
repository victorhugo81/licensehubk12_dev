"""Add user CSV/FTP bulk import support

Revision ID: 246e3823b701
Revises: 54a75434e501
Create Date: 2026-09-05 00:00:00.000000

Adds bulk user provisioning (manual CSV upload or a scheduled FTP pull),
mirroring the existing license CSV import feature. `import_history.kind`
discriminates which feature wrote a given row ("license", the existing
default, vs "user") instead of adding a near-duplicate history table.
`ftp_import_settings` is a single-row table holding the optional scheduled
FTP connection config; its password is stored Fernet-encrypted
(app/utils/crypto.py), never in plaintext.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '246e3823b701'
down_revision = '54a75434e501'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('import_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), nullable=False, server_default='license'))

    op.create_table(
        'ftp_import_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False, server_default='21'),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password_encrypted', sa.Text(), nullable=True),
        sa.Column('remote_path', sa.String(length=500), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=20), nullable=True),
        sa.Column('last_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ftp_import_settings')
    with op.batch_alter_table('import_history', schema=None) as batch_op:
        batch_op.drop_column('kind')
