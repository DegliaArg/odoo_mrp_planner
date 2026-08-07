"""
Migración a 18.0.2.2.0 — toggle propio de redondeo para Inventario.

Los paneles de Inventario y Movimientos dejan de leer el "Forzar cantidades
enteras" de la comparativa del forecast (Ajustes → Producción, que puede
estar invisible) y pasan a un toggle propio en la pestaña Inventario. Se
inicializa con el valor del toggle de Producción para que los números de los
paneles no cambien con el upgrade.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE mrp_reschedule_config
           SET inventory_force_integer = COALESCE(comparison_force_integer, FALSE)
    """)
