"""
Mixin: mrp_planner_dashboard_actions_mixin.py
Modelo: mrp.planner.dashboard.actions.mixin  (AbstractModel)

Acciones de drill-down del panel del planificador: los 20 métodos
action_view_* que abren vistas de lista filtradas (alertas, OFs, OCs,
programaciones) al clicar los contadores del dashboard.

Se extrae de mrp_planner_dashboard.py para separar la librería de
navegación/drill-down de los _compute_* que son la responsabilidad
propia del coordinador.

Los helpers _wh_domain_* y _get_allowed_wh_ids permanecen en el modelo
principal porque los usan tanto los _compute_* como estas actions.
"""
from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain


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

    def action_view_all_alerts(self):
        """Navega a la lista de todas las alertas activas (sin filtro de tipo/severidad)."""
        return self._open_alerts()

    def action_view_critical(self):
        """Navega a la lista de alertas activas con severidad crítica."""
        return self._open_alerts([('severity', '=', 'critical')])

    def action_view_mo_delayed_alerts(self):
        """Navega a las alertas de tipo 'OF atrasada' (mo_delayed)."""
        return self._open_alerts([('alert_type', '=', 'mo_delayed')])

    def action_view_po_delayed_alerts(self):
        """Navega a las alertas de tipo 'OC atrasada' (po_delayed)."""
        return self._open_alerts([('alert_type', '=', 'po_delayed')])

    def action_view_po_cancelled_alerts(self):
        """Navega a las alertas de tipo 'OC cancelada' (po_cancelled)."""
        return self._open_alerts([('alert_type', '=', 'po_cancelled')])

    def action_view_receipt_alerts(self):
        """Navega a las alertas de recepción atrasada vinculadas a OCs (excluye devoluciones)."""
        return self._open_alerts([
            ('alert_type', '=', 'receipt_delayed'),
            ('picking_id.purchase_id', '!=', False),
            ('picking_id.return_id', '=', False),
        ])

    def action_view_qty_mismatch_alerts(self):
        """Navega a las alertas de discrepancia de cantidad (qty_mismatch)."""
        return self._open_alerts([('alert_type', '=', 'qty_mismatch')])

    def action_view_mo_cancelled_alerts(self):
        """Navega a las alertas de tipo 'OF cancelada' (mo_cancelled)."""
        return self._open_alerts([('alert_type', '=', 'mo_cancelled')])

    def action_view_mo_upcoming_alerts(self):
        """Navega a las alertas de tipo 'OF próxima a vencer' (mo_upcoming)."""
        return self._open_alerts([('alert_type', '=', 'mo_upcoming')])

    def action_view_po_upcoming_alerts(self):
        """Navega a las alertas de tipo 'OC próxima a vencer' (po_upcoming)."""
        return self._open_alerts([('alert_type', '=', 'po_upcoming')])

    # ── Navegación — OFs ─────────────────────────────────────────────────────

    def _open_mos(self, domain, name):
        """Construye y retorna la acción de ventana de OFs con el dominio y nombre dados."""
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_mos(self):
        """Navega a todas las OFs activas (excluye done, cancel y subcontratación)."""
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', 'not in', ('done', 'cancel'))] + no_sc,
            _('OFs activas'),
        )

    def action_view_delayed_mos(self):
        """Navega a las OFs activas cuya fecha de finalización planificada ya pasó."""
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc,
            _('OFs atrasadas'),
        )

    # ── Navegación — OCs ─────────────────────────────────────────────────────

    def action_view_rfqs(self):
        """Navega a la lista de solicitudes de cotización (OCs en estado draft o sent)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Solicitudes de cotización'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', 'in', ('draft', 'sent'))] + self._get_wh_domains().po,
            'target': 'current',
        }

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

    def action_view_pending_pos(self):
        """Navega a las OCs aprobadas cuya fecha de entrega planificada aún no venció (o sin fecha), no totalmente recibidas."""
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs a tiempo'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('purchase', 'done')),
                ('receipt_status', '!=', 'full'),
                '|', ('date_planned', '>=', now), ('date_planned', '=', False),
            ] + self._get_wh_domains().po,
            'target': 'current',
        }

    def action_view_overdue_pos(self):
        """Navega a las OCs aprobadas con fecha de entrega vencida y recepción incompleta."""
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs vencidas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('purchase', 'done')),
                ('date_planned', '<', now),
                ('receipt_status', 'not in', ['full']),
            ] + self._get_wh_domains().po,
            'target': 'current',
        }

    def action_view_all_pos(self):
        """Navega a todas las OCs aprobadas (estado purchase o done) no totalmente recibidas."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de compra aprobadas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('purchase', 'done')),
                ('receipt_status', '!=', 'full'),
            ] + self._get_wh_domains().po,
            'target': 'current',
        }

    # ── Navegación — Programaciones ──────────────────────────────────────────

    def action_view_active_requests(self):
        """Navega a las programaciones confirmadas (con OFs ya generadas)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con OFs creadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_calculated_requests(self):
        """Navega a las programaciones en estado calculado (pendientes de confirmación)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones calculadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'calculated')],
            'target': 'current',
        }

    def action_view_requests_reschedule(self):
        """Navega a las programaciones confirmadas que tienen al menos una OF con reprogramación pendiente."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con reprogramación pendiente'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'confirmed'),
                ('item_ids.production_id.x_reschedule_needed', '=', True),
            ],
            'target': 'current',
        }
