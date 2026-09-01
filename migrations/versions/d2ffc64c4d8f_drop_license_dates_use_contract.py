"""Drop License start/expiration/renewal dates - use Contract's instead

Revision ID: d2ffc64c4d8f
Revises: d28f530a8ef1
Create Date: 2026-09-01 18:00:00.000000

License.start_date/expiration_date/renewal_date and Contract.start_date/
end_date/renewal_date had drifted apart on several real rows (edited
independently over time), which is exactly the confusion this migration
resolves: going forward there is only one set of dates, on Contract.
License now exposes start_date/expiration_date/renewal_date as computed
passthroughs to its contract (see app/models.py) rather than columns, so
no application code needs to change - only the redundant, now-authoritative
duplicate columns on License are dropped here. Per explicit confirmation,
the contract's values win wherever the two had diverged; the license-side
values being dropped are not migrated anywhere.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd2ffc64c4d8f'
down_revision = 'd28f530a8ef1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('licenses', schema=None) as batch_op:
        batch_op.drop_index('ix_licenses_expiration_date')
        batch_op.drop_column('start_date')
        batch_op.drop_column('expiration_date')
        batch_op.drop_column('renewal_date')


def downgrade():
    # Best-effort: recreates the columns and backfills from the contract's
    # dates. The original (pre-upgrade) license-side values are gone for
    # good - this cannot restore the divergence that existed before
    # upgrading, only re-seed from whatever the contract currently holds.
    with op.batch_alter_table('licenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('start_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('expiration_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('renewal_date', sa.Date(), nullable=True))
        batch_op.create_index('ix_licenses_expiration_date', ['expiration_date'])

    bind = op.get_bind()
    licenses_t = sa.table(
        'licenses', sa.column('id', sa.Integer), sa.column('contract_id', sa.Integer),
        sa.column('start_date', sa.Date), sa.column('expiration_date', sa.Date),
        sa.column('renewal_date', sa.Date),
    )
    contracts_t = sa.table(
        'contracts', sa.column('id', sa.Integer), sa.column('start_date', sa.Date),
        sa.column('end_date', sa.Date), sa.column('renewal_date', sa.Date),
    )
    rows = bind.execute(
        sa.select(licenses_t.c.id, licenses_t.c.contract_id)
    ).fetchall()
    contracts_by_id = {
        c.id: c for c in bind.execute(
            sa.select(contracts_t.c.id, contracts_t.c.start_date, contracts_t.c.end_date, contracts_t.c.renewal_date)
        ).fetchall()
    }
    for row in rows:
        c = contracts_by_id.get(row.contract_id)
        if not c:
            continue
        bind.execute(
            licenses_t.update().where(licenses_t.c.id == row.id).values(
                start_date=c.start_date, expiration_date=c.end_date, renewal_date=c.renewal_date,
            )
        )
