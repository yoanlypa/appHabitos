"""casa compartida: hogar, miembros, invitaciones, gastos y lista de la compra

Solo tablas nuevas: no toca nada de lo que ya había.

Revision ID: a1b2c3d4e5f6
Revises: c9e6a4b2d7f1
Create Date: 2026-11-24 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c9e6a4b2d7f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hogares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hogares')),
    )
    op.create_table(
        'hogar_miembros',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hogar_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('nombre', sa.String(), nullable=False),
        sa.Column('titular', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['hogar_id'], ['hogares.id'], name=op.f('fk_hogar_miembros_hogar_id_hogares')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hogar_miembros')),
        sa.UniqueConstraint('user_id', name=op.f('uq_hogar_miembros_user_id')),
    )
    op.create_index(op.f('ix_hogar_miembros_hogar_id'), 'hogar_miembros', ['hogar_id'])
    op.create_table(
        'hogar_invitaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hogar_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('usada_por', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['hogar_id'], ['hogares.id'], name=op.f('fk_hogar_invitaciones_hogar_id_hogares')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hogar_invitaciones')),
        sa.UniqueConstraint('codigo', name=op.f('uq_hogar_invitaciones_codigo')),
    )
    op.create_index(op.f('ix_hogar_invitaciones_hogar_id'), 'hogar_invitaciones', ['hogar_id'])
    op.create_table(
        'gastos_casa',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hogar_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('concepto', sa.String(), nullable=False),
        sa.Column('importe', sa.Integer(), nullable=False),
        sa.Column('categoria', sa.String(), nullable=False),
        sa.Column('origen', sa.String(), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['hogar_id'], ['hogares.id'], name=op.f('fk_gastos_casa_hogar_id_hogares')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_gastos_casa')),
    )
    op.create_index(op.f('ix_gastos_casa_hogar_id'), 'gastos_casa', ['hogar_id'])
    op.create_index(op.f('ix_gastos_casa_fecha'), 'gastos_casa', ['fecha'])
    op.create_table(
        'compra_articulos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hogar_id', sa.Integer(), nullable=False),
        sa.Column('texto', sa.String(), nullable=False),
        sa.Column('hay', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('anadido_por', sa.BigInteger(), nullable=True),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('cambiado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['hogar_id'], ['hogares.id'], name=op.f('fk_compra_articulos_hogar_id_hogares')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_compra_articulos')),
    )
    op.create_index(op.f('ix_compra_articulos_hogar_id'), 'compra_articulos', ['hogar_id'])


def downgrade() -> None:
    for tabla in ['compra_articulos', 'gastos_casa', 'hogar_invitaciones', 'hogar_miembros', 'hogares']:
        op.drop_table(tabla)
