from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_reschedule.models.mrp_schedule_mixin import no_subcontract_domain


class MrpPlannerDashboard(models.TransientModel):
    _name = 'mrp.planner.dashboard'
    _description = 'Panel del planificador de producción'

    name = fields.Char(default='Panel del Planificador')

    # ── Alertas ──────────────────────────────────────────────────────────────

    alert_total           = fields.Integer(compute='_compute_alert_stats', string='Total alertas')
    alert_critical        = fields.Integer(compute='_compute_alert_stats', string='Críticas')
    alert_warning         = fields.Integer(compute='_compute_alert_stats', string='Avisos')
    alert_mo_delayed      = fields.Integer(compute='_compute_alert_stats', string='OFs atrasadas')
    alert_po_delayed      = fields.Integer(compute='_compute_alert_stats', string='OCs vencidas')
    alert_po_cancelled    = fields.Integer(compute='_compute_alert_stats', string='OCs canceladas')
    alert_receipt_delayed = fields.Integer(compute='_compute_alert_stats', string='Recepciones demoradas')
    alert_qty_mismatch    = fields.Integer(compute='_compute_alert_stats', string='Cant. diferentes')
    alert_mo_cancelled    = fields.Integer(compute='_compute_alert_stats', string='OFs canceladas')

    # ── Órdenes de fabricación ───────────────────────────────────────────────

    mo_confirmed          = fields.Integer(compute='_compute_mo_stats', string='Confirmadas')
    mo_in_progress        = fields.Integer(compute='_compute_mo_stats', string='En progreso')
    mo_delayed            = fields.Integer(compute='_compute_mo_stats', string='Atrasadas')
    mo_reschedule_needed  = fields.Integer(compute='_compute_mo_stats', string='Para reprogramar')

    # ── Órdenes de compra ────────────────────────────────────────────────────

    po_pending = fields.Integer(compute='_compute_po_stats', string='OCs activas')
    po_overdue = fields.Integer(compute='_compute_po_stats', string='OCs vencidas')

    # ── Programaciones ───────────────────────────────────────────────────────

    request_active            = fields.Integer(compute='_compute_request_stats', string='En curso')
    request_reschedule_needed = fields.Integer(compute='_compute_request_stats', string='Con reprogramación')

    # ── Cómputos ─────────────────────────────────────────────────────────────

    @api.depends()
    def _compute_alert_stats(self):
        Alert = self.env['mrp.reschedule.alert']
        base = [('resolved', '=', False)]
        for rec in self:
            rec.alert_total           = Alert.search_count(base)
            rec.alert_critical        = Alert.search_count(base + [('severity', '=', 'critical')])
            rec.alert_warning         = Alert.search_count(base + [('severity', '=', 'warning')])
            rec.alert_mo_delayed      = Alert.search_count(base + [('alert_type', '=', 'mo_delayed')])
            rec.alert_po_delayed      = Alert.search_count(base + [('alert_type', '=', 'po_delayed')])
            rec.alert_po_cancelled    = Alert.search_count(base + [('alert_type', '=', 'po_cancelled')])
            rec.alert_receipt_delayed = Alert.search_count(base + [('alert_type', '=', 'receipt_delayed')])
            rec.alert_qty_mismatch    = Alert.search_count(base + [('alert_type', '=', 'qty_mismatch')])
            rec.alert_mo_cancelled    = Alert.search_count(base + [('alert_type', '=', 'mo_cancelled')])

    @api.depends()
    def _compute_mo_stats(self):
        MO = self.env['mrp.production']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        for rec in self:
            rec.mo_confirmed        = MO.search_count([('state', '=', 'confirmed')] + no_sc)
            rec.mo_in_progress      = MO.search_count([('state', 'in', ('progress', 'to_close'))] + no_sc)
            rec.mo_delayed          = MO.search_count([
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc)
            rec.mo_reschedule_needed = MO.search_count([
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc)

    @api.depends()
    def _compute_po_stats(self):
        PO = self.env['purchase.order']
        now = fields.Datetime.now()
        for rec in self:
            rec.po_pending = PO.search_count([('state', '=', 'purchase'), ('date_planned', '>=', now)])
            rec.po_overdue = PO.search_count([('state', '=', 'purchase'), ('date_planned', '<', now)])

    @api.depends()
    def _compute_request_stats(self):
        Req = self.env['mrp.production.request']
        for rec in self:
            active = Req.search([('state', '=', 'confirmed')])
            rec.request_active = len(active)
            rec.request_reschedule_needed = len(active.filtered(
                lambda r: any(
                    it.production_id and it.production_id.x_reschedule_needed
                    for it in r.item_ids
                )
            ))

    # ── Apertura ─────────────────────────────────────────────────────────────

    @api.model
    def action_open(self):
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel del planificador'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh(self):
        self.env['mrp.reschedule.alert']._cron_check_delays()
        return self.env['mrp.planner.dashboard'].action_open()

    # ── Navegación — alertas ─────────────────────────────────────────────────

    def _open_alerts(self, extra_domain=None):
        domain = [('resolved', '=', False)] + (extra_domain or [])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_alerts(self):
        return self._open_alerts()

    def action_view_critical(self):
        return self._open_alerts([('severity', '=', 'critical')])

    def action_view_warning(self):
        return self._open_alerts([('severity', '=', 'warning')])

    def action_view_mo_delayed_alerts(self):
        return self._open_alerts([('alert_type', '=', 'mo_delayed')])

    def action_view_po_delayed_alerts(self):
        return self._open_alerts([('alert_type', '=', 'po_delayed')])

    def action_view_po_cancelled_alerts(self):
        return self._open_alerts([('alert_type', '=', 'po_cancelled')])

    def action_view_receipt_alerts(self):
        return self._open_alerts([('alert_type', '=', 'receipt_delayed')])

    def action_view_qty_mismatch_alerts(self):
        return self._open_alerts([('alert_type', '=', 'qty_mismatch')])

    def action_view_mo_cancelled_alerts(self):
        return self._open_alerts([('alert_type', '=', 'mo_cancelled')])

    # ── Navegación — OFs ─────────────────────────────────────────────────────

    def action_view_confirmed_mos(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs confirmadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')] + no_subcontract_domain(self.env),
            'target': 'current',
        }

    def action_view_in_progress_mos(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs en progreso'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('state', 'in', ('progress', 'to_close'))] + no_subcontract_domain(self.env),
            'target': 'current',
        }

    def action_view_delayed_mos(self):
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs atrasadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_subcontract_domain(self.env),
            'target': 'current',
        }

    def action_view_reschedule_needed(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs para reprogramar'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_subcontract_domain(self.env),
            'target': 'current',
        }

    # ── Navegación — OCs ─────────────────────────────────────────────────────

    def action_view_pending_pos(self):
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs activas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'purchase'), ('date_planned', '>=', now)],
            'target': 'current',
        }

    def action_view_overdue_pos(self):
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs vencidas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'purchase'), ('date_planned', '<', now)],
            'target': 'current',
        }

    # ── Navegación — Programaciones ──────────────────────────────────────────

    def action_view_active_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones en curso'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_requests_reschedule(self):
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

    # ── Apertura de paneles secundarios ──────────────────────────────────────

    def action_open_mos_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('mos')

    def action_open_pos_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('pos')

    def action_open_requests_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('requests')
