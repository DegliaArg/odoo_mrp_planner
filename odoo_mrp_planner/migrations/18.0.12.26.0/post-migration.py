"""
Migración a 18.0.12.26.0 — recálculo de unmet_qty / unmet_amount en sale.order.line.

El cálculo del "entregado" del análisis de demanda insatisfecha pasó a topearse
en 0 (una devolución con qty_delivered negativo ya no infla el pendiente ni resta
al cumplimiento). Los campos computados-almacenados unmet_qty y unmet_amount NO se
recalculan solos al actualizar el módulo, así que las líneas con qty_delivered < 0
conservarían el valor viejo (inflado). Solo esas líneas cambian, por eso el
recompute se limita a ellas.

En bases sin líneas con qty_delivered negativo, el search no encuentra filas y la
migración es un no-op.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['sale.order.line']
    lines = Line.search([('qty_delivered', '<', 0)])
    if not lines:
        return
    for fname in ('unmet_qty', 'unmet_amount'):
        env.add_to_compute(Line._fields[fname], lines)
    lines.flush_recordset(['unmet_qty', 'unmet_amount'])
