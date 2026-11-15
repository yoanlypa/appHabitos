"""el trabajo pasa a ser una ficha propia (tabla `trabajos`)

Antes un trabajo era una línea de cobro y los gastos colgaban de ella. Yoa
lo quiere como una página de Notion: un trabajo con cliente, fechas,
facturado y reseña, que junta sus cobros, gastos, notas y citas.

Lo que había se convierte sin perder nada:
- Cada cobro del que colgaba algún gasto pasa a ser un trabajo nuevo (con su
  concepto, cliente, fecha y si estaba facturado), y ese cobro y sus gastos
  quedan dentro.
- Un cobro facturado sin gastos se queda suelto pero marcado para la
  gestoría (si no tiene ya la factura colgada, que manda sola).
- `apuntes.facturado` desaparece: ahora es del trabajo.

Revision ID: c9e6a4b2d7f1
Revises: b8d5f3a1c2e6
Create Date: 2026-11-15 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e6a4b2d7f1'
down_revision: Union[str, Sequence[str], None] = 'b8d5f3a1c2e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trabajos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('titulo', sa.String(), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('cliente_id', sa.Integer(), nullable=True),
        sa.Column('fecha_inicio', sa.Date(), nullable=True),
        sa.Column('fecha_fin', sa.Date(), nullable=True),
        sa.Column('facturado', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('resena', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('creado', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_trabajos_cliente_id_clientes')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_trabajos')),
    )
    with op.batch_alter_table('trabajos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_trabajos_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_trabajos_cliente_id'), ['cliente_id'], unique=False)

    conexion = op.get_bind()
    apuntes = sa.table(
        'apuntes',
        sa.column('id', sa.Integer), sa.column('user_id', sa.BigInteger),
        sa.column('fecha', sa.Date), sa.column('tipo', sa.String),
        sa.column('concepto', sa.String), sa.column('cliente_id', sa.Integer),
        sa.column('trabajo_id', sa.Integer), sa.column('facturado', sa.Boolean),
        sa.column('para_gestoria', sa.Boolean),
    )
    facturas = sa.table('facturas', sa.column('apunte_id', sa.Integer), sa.column('emitida', sa.Boolean))
    trabajos = sa.table(
        'trabajos',
        sa.column('id', sa.Integer), sa.column('user_id', sa.BigInteger),
        sa.column('titulo', sa.String), sa.column('cliente_id', sa.Integer),
        sa.column('fecha_inicio', sa.Date), sa.column('facturado', sa.Boolean),
    )

    # Los cobros de los que colgaba algún gasto: cada uno, un trabajo.
    padres = {
        fila.trabajo_id
        for fila in conexion.execute(
            sa.select(apuntes.c.trabajo_id).where(apuntes.c.trabajo_id.isnot(None))
        )
    }
    nuevo_de = {}
    for cobro in conexion.execute(sa.select(apuntes).where(apuntes.c.id.in_(padres))).mappings():
        # RETURNING vale en SQLite y en Postgres; `inserted_primary_key` no,
        # porque esta tabla de trabajo no sabe cuál es su clave.
        nuevo_de[cobro['id']] = conexion.execute(
            trabajos.insert()
            .values(
                user_id=cobro['user_id'], titulo=cobro['concepto'], cliente_id=cobro['cliente_id'],
                fecha_inicio=cobro['fecha'], facturado=bool(cobro['facturado']),
            )
            .returning(trabajos.c.id)
        ).scalar_one()

    # Un cobro facturado y suelto conserva lo que valía para la gestoría.
    con_factura = {
        fila.apunte_id
        for fila in conexion.execute(
            sa.select(facturas.c.apunte_id).where(
                facturas.c.emitida.is_(True), facturas.c.apunte_id.isnot(None)
            )
        )
    }
    for fila in conexion.execute(
        sa.select(apuntes.c.id).where(apuntes.c.tipo == 'trabajo', apuntes.c.facturado.is_(True))
    ):
        if fila.id not in nuevo_de and fila.id not in con_factura:
            conexion.execute(apuntes.update().where(apuntes.c.id == fila.id).values(para_gestoria=True))

    # Se cambia la clave ajena: de apuntes a trabajos.
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_apuntes_trabajo_id_apuntes', type_='foreignkey')
        batch_op.drop_column('facturado')
        batch_op.add_column(sa.Column('trabajo_nuevo', sa.Integer(), nullable=True))
    con_nueva = sa.table(
        'apuntes', sa.column('id', sa.Integer), sa.column('trabajo_id', sa.Integer),
        sa.column('trabajo_nuevo', sa.Integer),
    )
    for viejo, nuevo in nuevo_de.items():
        # El cobro padre entra en su propio trabajo, y sus gastos con él.
        conexion.execute(
            con_nueva.update()
            .where(sa.or_(con_nueva.c.id == viejo, con_nueva.c.trabajo_id == viejo))
            .values(trabajo_nuevo=nuevo)
        )
    # En dos pasos: SQLite recrea la tabla, y quitar una columna y dar su
    # nombre a otra en la misma pasada se lía.
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.drop_index('ix_apuntes_trabajo_id')
        batch_op.drop_column('trabajo_id')
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.alter_column('trabajo_nuevo', new_column_name='trabajo_id')
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_apuntes_trabajo_id'), ['trabajo_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_apuntes_trabajo_id_trabajos'), 'trabajos', ['trabajo_id'], ['id'])

    with op.batch_alter_table('citas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trabajo_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_citas_trabajo_id'), ['trabajo_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_citas_trabajo_id_trabajos'), 'trabajos', ['trabajo_id'], ['id'])


def downgrade() -> None:
    # Vuelta atrás con pérdida: los trabajos-ficha no caben en el modelo de
    # antes. Los apuntes se quedan sueltos.
    with op.batch_alter_table('citas', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_citas_trabajo_id_trabajos'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_citas_trabajo_id'))
        batch_op.drop_column('trabajo_id')
    with op.batch_alter_table('apuntes', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_apuntes_trabajo_id_trabajos'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_apuntes_trabajo_id'))
        batch_op.drop_column('trabajo_id')
        batch_op.add_column(sa.Column('trabajo_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('facturado', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.create_index(batch_op.f('ix_apuntes_trabajo_id'), ['trabajo_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_apuntes_trabajo_id_apuntes'), 'apuntes', ['trabajo_id'], ['id'])
    op.drop_table('trabajos')
