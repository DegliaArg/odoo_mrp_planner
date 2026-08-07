"""
Módulo: mrp_planner_dashboard.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.dashboard

Enciende las funciones de despacho de los paneles del módulo base:
- Panel de ventas: KPIs de despachados ("Entregas físicas" y "Tasa física"
  sobre remitos despachados) implementando los hooks del forecast.
- Panel de Inventario: la capa operativa de la tabla — cola "Validado
  s/ despachar", chip y despacho masivo — implementando los hooks
  _inventory_dispatch_enabled / _inventory_dispatch_queue_ids /
  _inventory_can_dispatch.
"""
from odoo import models, api


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Panel de ventas: entregas físicas ─────────────────────────────────────

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

    # ── Panel de Inventario: capa operativa del circuito ─────────────────────

    @api.model
    def _inventory_dispatch_enabled(self):
        return self._forecast_dispatch_enabled()

    @api.model
    def _inventory_dispatch_queue_ids(self, picking_ids):
        if not picking_ids or not self._inventory_dispatch_enabled():
            return set()
        return set(self.env['stock.picking'].sudo().search([
            ('id', 'in', list(picking_ids)),
            ('x_dispatch_state', '=', 'to_dispatch'),
        ]).ids)

    @api.model
    def _inventory_can_dispatch(self):
        if not self._inventory_dispatch_enabled():
            return False
        u = self.env.user
        return (u.has_group('odoo_mrp_planner_dispatch.group_dispatch_validation')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system'))
