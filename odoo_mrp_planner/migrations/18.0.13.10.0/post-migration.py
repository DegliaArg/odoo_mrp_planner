"""
Migración a 18.0.13.10.0 — Tasa de entrega del Panel de Inventario.

La tasa se redefinió (por eslabón, con numerador = validado del período y
denominador configurable) y ahora se calcula EN VIVO desde los snapshots. El
consolidado mensual mrp.planner.kpi.monthly quedó con la fórmula vieja y sin
dimensión de eslabón: sus números ya no aplican y confunden. Se borran todas
sus filas del KPI 'dispatch_available' (el único que ese modelo almacenaba).

El modelo queda vacío (legacy): no se vuelve a escribir ni a leer. La tabla se
conserva para no arrastrar una baja de modelo con sus ACLs/reglas; si en el
futuro se decide re-consolidar con la definición nueva, está lista.
"""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM mrp_planner_kpi_monthly
         WHERE kpi = 'dispatch_available'
    """)
