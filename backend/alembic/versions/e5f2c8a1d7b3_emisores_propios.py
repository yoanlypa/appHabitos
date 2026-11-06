"""emisores propios

Los emisores que Yoa ha dicho que son él (al corregir con /emitida o poner
"mía"), para reconocer sus facturas sin depender de NOMBRES_PROPIOS.

Revision ID: e5f2c8a1d7b3
Revises: d4e8b1a6c3f7
Create Date: 2026-11-06 10:45:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f2c8a1d7b3'
down_revision: Union[str, Sequence[str], None] = 'd4e8b1a6c3f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'emisores_propios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('nif', sa.String(), nullable=True),
        sa.Column('nombre', sa.String(), nullable=True),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_emisores_propios')),
    )
    with op.batch_alter_table('emisores_propios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_emisores_propios_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('emisores_propios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_emisores_propios_user_id'))
    op.drop_table('emisores_propios')
