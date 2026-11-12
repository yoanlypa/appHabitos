"""recordatorio de citas el mismo día, y correo para los avisos

`citas.avisada_el`: el día para el que ya se mandó el recordatorio.
`ajustes.correo`: a dónde mandar también por correo los avisos. Todo vacío.

Revision ID: b8d5f3a1c2e6
Revises: a7c4e2d9b1f5
Create Date: 2026-11-12 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d5f3a1c2e6'
down_revision: Union[str, Sequence[str], None] = 'a7c4e2d9b1f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('citas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avisada_el', sa.Date(), nullable=True))
    with op.batch_alter_table('ajustes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('correo', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ajustes', schema=None) as batch_op:
        batch_op.drop_column('correo')
    with op.batch_alter_table('citas', schema=None) as batch_op:
        batch_op.drop_column('avisada_el')
