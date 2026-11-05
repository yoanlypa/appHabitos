"""facturas emitidas

Distingue las facturas que emite Yoa (cuelgan de un trabajo) de los tickets
de compra. Todo lo que ya había es de compra: por defecto False.

Revision ID: d4e8b1a6c3f7
Revises: c3d9a7e5f1b2
Create Date: 2026-11-05 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e8b1a6c3f7'
down_revision: Union[str, Sequence[str], None] = 'c3d9a7e5f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emitida', sa.Boolean(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('facturas', schema=None) as batch_op:
        batch_op.drop_column('emitida')
