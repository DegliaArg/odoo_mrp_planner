"""Pre-migración 18.0.13.15.0.

Se eliminó el método 'average' (Promedio de disponible) de la Base de la tasa de
entrega (dispatch_available_denominator_method), dejando solo 'closing' y 'peak'.
Las empresas que lo tuvieran configurado se pasan al default 'closing' para que
el Selection no quede con un valor inválido.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE mrp_reschedule_config
           SET dispatch_available_denominator_method = 'closing'
         WHERE dispatch_available_denominator_method = 'average'
    """)
