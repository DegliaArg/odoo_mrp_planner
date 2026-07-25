"""
Mixin: mrp_planner_dashboard_actions_mixin.py
Modelo: mrp.planner.dashboard.actions.mixin  (AbstractModel)

Acciones de drill-down del panel del planificador: los métodos action_view_*
que abren vistas de lista filtradas de alertas al clicar los contadores del
dashboard principal (vista mrp_planner_dashboard_views.xml).

Nota: los drill-downs de OFs/OCs/programaciones viven en dos lugares según
quién los usa: los widgets OWL navegan por IDs exactos calculados en el
backend (p. ej. kpi_ids del widget de OC) y el sub-panel de detalle
(mrp.planner.detail.dashboard) define sus propias acciones. Este mixin solo
conserva las acciones referenciadas por botones de la vista principal.

Los helpers _wh_domain_* y _get_allowed_wh_ids permanecen en el modelo
principal porque los usan tanto los _compute_* como estas actions.
"""
from odoo import models, _


class MrpPlannerDashboardActionsMixin(models.AbstractModel):
    _name = 'mrp.planner.dashboard.actions.mixin'
    _description = 'Mixin de acciones de drill-down del panel del planificador'

    # ── Navegación — alertas ─────────────────────────────────────────────────

    def _open_alerts(self, extra_domain=None):
        """Construye y retorna la acción de ventana de alertas con dominio base + filtro adicional."""
        # Alertas sin OF (recepciones, OCs) siempre se incluyen; solo se excluyen
        # las alertas de OFs de subcontratación (production_id != False y ubicación SBC)
        no_sc = ['|', ('production_id', '=', False),
                 ('production_id.location_src_id.is_subcontracting_location', '!=', True)]
        domain = [('resolved', '=', False)] + no_sc + (extra_domain or [])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_po_delayed_alerts(self):
        """Navega a las alertas de tipo 'OC atrasada' (po_delayed)."""
        return self._open_alerts([('alert_type', '=', 'po_delayed')])

    def action_view_receipt_alerts(self):
        """Navega a las alertas de recepción atrasada vinculadas a OCs (excluye devoluciones)."""
        return self._open_alerts([
            ('alert_type', '=', 'receipt_delayed'),
            ('picking_id.purchase_id', '!=', False),
            ('picking_id.return_id', '=', False),
        ])

    def action_view_po_upcoming_alerts(self):
        """Navega a las alertas de tipo 'OC próxima a vencer' (po_upcoming)."""
        return self._open_alerts([('alert_type', '=', 'po_upcoming')])

    # ── Navegación — OCs ─────────────────────────────────────────────────────

    def action_view_to_approve(self):
        """Navega a la lista de OCs pendientes de aprobación (estado 'to approve')."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Por aprobar'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'to approve')] + self._get_wh_domains().po,
            'target': 'current',
        }
