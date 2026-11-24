"""carteras de efectivo: cada uno su cartera, entradas y recuentos

Añade `efectivo` a los gastos de casa y a los miembros (cómo pagan casi
siempre) y la tabla de entradas y recuentos. No toca nada del negocio.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-24 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('hogar_miembros') as batch_op:
        batch_op.add_column(sa.Column('efectivo', sa.Boolean(), server_default=sa.text('1'), nullable=False))
    with op.batch_alter_table('gastos_casa') as batch_op:
        batch_op.add_column(sa.Column('efectivo', sa.Boolean(), server_default=sa.text('0'), nullable=False))
    op.create_table(
        'cartera_movimientos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hogar_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('importe', sa.Integer(), nullable=False),
        sa.Column('gasto_id', sa.Integer(), nullable=True),
        sa.Column('hasta_gasto_id', sa.Integer(), nullable=True),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['hogar_id'], ['hogares.id'], name=op.f('fk_cartera_movimientos_hogar_id_hogares')),
        sa.ForeignKeyConstraint(['gasto_id'], ['gastos_casa.id'], name=op.f('fk_cartera_movimientos_gasto_id_gastos_casa')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cartera_movimientos')),
    )
    op.create_index(op.f('ix_cartera_movimientos_hogar_id'), 'cartera_movimientos', ['hogar_id'])
    op.create_index(op.f('ix_cartera_movimientos_user_id'), 'cartera_movimientos', ['user_id'])


def downgrade() -> None:
    op.drop_table('cartera_movimientos')
    with op.batch_alter_table('gastos_casa') as batch_op:
        batch_op.drop_column('efectivo')
    with op.batch_alter_table('hogar_miembros') as batch_op:
        batch_op.drop_column('efectivo')
