"""facturas

La foto de los tickets escaneados. Tabla nueva, no toca las que hay.

Revision ID: b7e1f3c2a9d4
Revises: a65c13d5dc18
Create Date: 2026-10-27 11:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e1f3c2a9d4'
down_revision: Union[str, Sequence[str], None] = 'a65c13d5dc18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'facturas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('apunte_id', sa.Integer(), nullable=True),
        sa.Column('ruta', sa.String(), nullable=False),
        sa.Column('mime', sa.String(), nullable=False),
        sa.Column('tamano', sa.Integer(), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['apunte_id'], ['apuntes.id'], name=op.f('fk_facturas_apunte_id_apuntes')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_facturas')),
        sa.UniqueConstraint('apunte_id', name=op.f('uq_facturas_apunte_id')),
    )
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_facturas_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_facturas_user_id'))
    op.drop_table('facturas')
