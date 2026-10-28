"""facturas: datos leidos y esquinas

Todo lo que pone el ticket (lineas, CIF, numero...) y las esquinas del
papel. Columnas nuevas y vacias: lo escaneado antes sigue valiendo.

Revision ID: c3d9a7e5f1b2
Revises: b7e1f3c2a9d4
Create Date: 2026-10-28 13:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d9a7e5f1b2'
down_revision: Union[str, Sequence[str], None] = 'b7e1f3c2a9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('datos', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('esquinas', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.drop_column('esquinas')
        batch_op.drop_column('datos')
