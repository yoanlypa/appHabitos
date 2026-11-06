"""IBAN en los emisores propios, y se olvida lo aprendido hasta ahora

La primera versión aprendió de una factura que la IA leyó cruzada y guardó
al CLIENTE (IG España XXI) como si fuera Yoa. Lo aprendido tenía un día: se
borra entero y se vuelve a aprender, ya bien, en la siguiente corrección.

Revision ID: f6a3d9b2e8c4
Revises: e5f2c8a1d7b3
Create Date: 2026-11-06 11:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a3d9b2e8c4'
down_revision: Union[str, Sequence[str], None] = 'e5f2c8a1d7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM emisores_propios")
    with op.batch_alter_table('emisores_propios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('iban', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('emisores_propios', schema=None) as batch_op:
        batch_op.drop_column('iban')
