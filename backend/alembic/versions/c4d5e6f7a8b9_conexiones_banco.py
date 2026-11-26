"""conexión con el banco: el permiso PSD2 para leer la cuenta

Una tabla nueva; no toca nada de lo que hay.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conexiones_banco',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('banco', sa.String(), nullable=False),
        sa.Column('estado', sa.String(), nullable=False),
        sa.Column('clave_vuelta', sa.String(), nullable=True),
        sa.Column('sesion', sa.String(), nullable=True),
        sa.Column('valido_hasta', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cuentas', sa.Text(), nullable=True),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conexiones_banco')),
        sa.UniqueConstraint('clave_vuelta', name=op.f('uq_conexiones_banco_clave_vuelta')),
    )
    op.create_index(op.f('ix_conexiones_banco_user_id'), 'conexiones_banco', ['user_id'])


def downgrade() -> None:
    op.drop_table('conexiones_banco')
