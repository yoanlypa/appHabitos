"""trabajos con gastos, y qué va a la gestoría

Un gasto puede colgar de un trabajo (`trabajo_id`, que apunta a otro
apunte), un trabajo puede estar facturado o no, y un gasto suelto puede
marcarse para la gestoría.

Los trabajos que ya tienen colgada una factura emitida por Yoa nacen como
facturados: lo son, y dejarlos en "no" los sacaría de lo que va a la
gestoría sin que nadie lo hubiera decidido. Todo lo demás empieza en "no",
que es no decidir por él.

Revision ID: a7c4e2d9b1f5
Revises: f6a3d9b2e8c4
Create Date: 2026-11-11 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c4e2d9b1f5'
down_revision: Union[str, Sequence[str], None] = 'f6a3d9b2e8c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trabajo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('facturado', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('para_gestoria', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.create_index(batch_op.f('ix_apuntes_trabajo_id'), ['trabajo_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_apuntes_trabajo_id_apuntes'), 'apuntes', ['trabajo_id'], ['id'])

    # Con tablas sueltas y no con SQL a mano: `emitida = 1` vale en SQLite
    # pero no en Postgres, y el motor puede cambiar.
    apuntes = sa.table('apuntes', sa.column('id', sa.Integer), sa.column('facturado', sa.Boolean))
    facturas = sa.table(
        'facturas', sa.column('apunte_id', sa.Integer), sa.column('emitida', sa.Boolean)
    )
    con_factura = sa.select(facturas.c.apunte_id).where(
        facturas.c.emitida.is_(True), facturas.c.apunte_id.isnot(None)
    )
    op.execute(apuntes.update().where(apuntes.c.id.in_(con_factura)).values(facturado=True))


def downgrade() -> None:
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_apuntes_trabajo_id_apuntes'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_apuntes_trabajo_id'))
        batch_op.drop_column('para_gestoria')
        batch_op.drop_column('facturado')
        batch_op.drop_column('trabajo_id')
