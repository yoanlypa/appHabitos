"""movimientos del banco: lo ya visto, para preguntar una vez por cada pago

Tabla nueva y dos columnas en `conexiones_banco` (cuándo se leyó y el aviso
de caducidad). No toca nada del negocio ni de Casa.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-26 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('conexiones_banco') as batch_op:
        batch_op.add_column(sa.Column('leida', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('aviso_caducidad', sa.Date(), nullable=True))
    op.create_table(
        'movimientos_banco',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conexion_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('cuenta', sa.String(), nullable=False),
        sa.Column('referencia', sa.String(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=True),
        sa.Column('importe', sa.Integer(), nullable=False),
        sa.Column('es_gasto', sa.Boolean(), nullable=False),
        sa.Column('concepto', sa.String(), nullable=False),
        sa.Column('texto', sa.String(), nullable=True),
        sa.Column('estado', sa.String(), nullable=False),
        sa.Column('gasto_casa_id', sa.Integer(), nullable=True),
        sa.Column('apunte_id', sa.Integer(), nullable=True),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['conexion_id'], ['conexiones_banco.id'], name=op.f('fk_movimientos_banco_conexion_id_conexiones_banco')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_movimientos_banco')),
        sa.UniqueConstraint('cuenta', 'referencia', name=op.f('uq_movimientos_banco_cuenta')),
    )
    op.create_index(op.f('ix_movimientos_banco_conexion_id'), 'movimientos_banco', ['conexion_id'])
    op.create_index(op.f('ix_movimientos_banco_user_id'), 'movimientos_banco', ['user_id'])
    op.create_index(op.f('ix_movimientos_banco_estado'), 'movimientos_banco', ['estado'])


def downgrade() -> None:
    op.drop_table('movimientos_banco')
    with op.batch_alter_table('conexiones_banco') as batch_op:
        batch_op.drop_column('aviso_caducidad')
        batch_op.drop_column('leida')
