"""Add contract_file_name/contract_file_path to contracts

Revision ID: e1f206fb8528
Revises: 075977192af8
Create Date: 2026-09-07 00:00:00.000000

Lets a contract carry one uploaded document (the signed PO/agreement,
PDF or Word). contract_file_path is a server-generated random filename
under UPLOAD_FOLDER/contracts/ - contract_file_name is only the original
filename, kept for display and as the download's attachment name.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e1f206fb8528'
down_revision = '075977192af8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('contracts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contract_file_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('contract_file_path', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('contracts', schema=None) as batch_op:
        batch_op.drop_column('contract_file_path')
        batch_op.drop_column('contract_file_name')
