"""
Módulo: mrp_planner_run_log.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.run.log

Agrega el proceso "Snapshot de despacho" al historial de ejecuciones: cada
corrida del cron de disponibilidad (snapshot + cierre mensual + retención)
deja su fila con resultado y métricas.
"""
from odoo import models, fields


class MrpPlannerRunLog(models.Model):
    _inherit = 'mrp.planner.run.log'

    process = fields.Selection(
        selection_add=[('dispatch_snapshot', 'Snapshot de despacho')],
        ondelete={'dispatch_snapshot': 'cascade'})
