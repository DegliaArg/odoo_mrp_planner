"""
Módulo: mrp_planner_dashboard.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.dashboard

Enciende en el panel de ventas los KPIs de despachados ("Entregas físicas"
y "Tasa física" sobre remitos despachados) implementando los hooks que el
módulo base expone en el cálculo del forecast.
"""
from odoo import models, api


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    @api.model
    def _forecast_dispatch_enabled(self):
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        return bool(cfg and cfg.enable_dispatch_validation)

    @api.model
    def _forecast_dispatched_picking_ids(self, picking_ids):
        if not picking_ids or not self._forecast_dispatch_enabled():
            return set()
        # sudo(): mismo criterio que las demás lecturas de picking del dashboard.
        return set(self.env['stock.picking'].sudo().search([
            ('id', 'in', list(picking_ids)),
            ('x_dispatch_state', '=', 'dispatched'),
        ]).ids)
