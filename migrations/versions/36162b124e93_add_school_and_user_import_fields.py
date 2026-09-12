"""Add extra school contact/identifier fields and User.middle_name

Revision ID: 36162b124e93
Revises: e1f206fb8528
Create Date: 2026-09-11 00:00:00.000000

Adds the fields needed to support a richer schools CSV import (city, state,
zip_code, email, phone, acronym, cds_code) and users CSV import
(middle_name), all nullable so existing rows are unaffected.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '36162b124e93'
down_revision = 'e1f206fb8528'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('city', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('state', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('zip_code', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('phone', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('acronym', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('cds_code', sa.String(length=30), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('middle_name', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('middle_name')

    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('cds_code')
        batch_op.drop_column('acronym')
        batch_op.drop_column('phone')
        batch_op.drop_column('email')
        batch_op.drop_column('zip_code')
        batch_op.drop_column('state')
        batch_op.drop_column('city')
