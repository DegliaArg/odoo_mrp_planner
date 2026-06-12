from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_reschedule.models.mrp_schedule_mixin import no_subcontract_domain


class MrpPlannerDetailDashboard(models.TransientModel):
    _name = 'mrp.planner.detail.dashboard'
    _description = 'Panel de detalle del planificador'

    # ── Contexto ─────────────────────────────────────────────────────────────

    request_id    = fields.Many2one('mrp.production.request', string='Programación', readonly=True)
    production_id = fields.Many2one('mrp.production',         string='OF',           readonly=True)
    purchase_id   = fields.Many2one('purchase.order',         string='OC',           readonly=True)

    context_type = fields.Selection([
        ('request',    'Programación'),
        ('production', 'OF'),
        ('purchase',   'OC'),
    ], compute='_compute_context', string='Tipo')

    dashboard_title = fields.Char(compute='_compute_context', string='Título')

    # ── Artículos del plan (solo request) ────────────────────────────────────

    req_item_total       = fields.Integer(compute='_compute_all')
    req_item_confirmed   = fields.Integer(compute='_compute_all')
    req_item_in_progress = fields.Integer(compute='_compute_all')
    req_item_done        = fields.Integer(compute='_compute_all')
    req_item_delayed     = fields.Integer(compute='_compute_all')
    req_item_reschedule  = fields.Integer(compute='_compute_all')

    # ── Alertas ──────────────────────────────────────────────────────────────

    alert_total    = fields.Integer(compute='_compute_all')
    alert_critical = fields.Integer(compute='_compute_all')
    alert_warning  = fields.Integer(compute='_compute_all')

    # ── Reprogramaciones (request + production) ──────────────────────────────

    plan_total   = fields.Integer(compute='_compute_all')
    plan_pending = fields.Integer(compute='_compute_all')
    plan_applied = fields.Integer(compute='_compute_all')

    # ── OFs (request + purchase) ─────────────────────────────────────────────

    mo_total       = fields.Integer(compute='_compute_all')
    mo_confirmed   = fields.Integer(compute='_compute_all')
    mo_in_progress = fields.Integer(compute='_compute_all')
    mo_done        = fields.Integer(compute='_compute_all')
    mo_delayed     = fields.Integer(compute='_compute_all')

    # ── OCs (request + production) ───────────────────────────────────────────

    po_total   = fields.Integer(compute='_compute_all')
    po_overdue = fields.Integer(compute='_compute_all')

    # ── Cómputos ─────────────────────────────────────────────────────────────

    @api.depends('request_id', 'production_id', 'purchase_id')
    def _compute_context(self):
        for rec in self:
            if rec.request_id:
                rec.context_type = 'request'
                rec.dashboard_title = _('Panel — %s') % rec.request_id.name
            elif rec.production_id:
                rec.context_type = 'production'
                rec.dashboard_title = _('Panel — %s') % rec.production_id.name
            elif rec.purchase_id:
                rec.context_type = 'purchase'
                rec.dashboard_title = _('Panel — %s') % rec.purchase_id.name
            else:
                rec.context_type = False
                rec.dashboard_title = _('Panel')

    def _get_context_mos(self):
        """Retorna el recordset de mrp.production relevante para este contexto."""
        if self.request_id:
            return self.request_id.item_ids.mapped('production_id').filtered(lambda m: m.id)
        if self.production_id:
            return self.production_id
        if self.purchase_id:
            return self.env['mrp.production'].search([
                '|',
                ('purchase_order_id', '=', self.purchase_id.id),
                ('purchase_line_id.order_id', '=', self.purchase_id.id),
            ] + no_subcontract_domain(self.env))
        return self.env['mrp.production'].browse()

    def _get_context_pos(self):
        """Retorna el recordset de purchase.order relevante para este contexto."""
        if self.purchase_id:
            return self.purchase_id
        mos = self._get_context_mos()
        if not mos:
            return self.env['purchase.order'].browse()
        return (
            mos.mapped('purchase_order_id') |
            mos.mapped('move_raw_ids').filtered(lambda m: m.purchase_line_id)
              .mapped('purchase_line_id.order_id')
        )

    @api.depends('request_id', 'production_id', 'purchase_id')
    def _compute_all(self):
        Alert = self.env['mrp.reschedule.alert']
        Plan  = self.env['mrp.reschedule.plan']
        now   = fields.Datetime.now()

        for rec in self:
            mos    = rec._get_context_mos()
            mo_ids = mos.ids

            # ── Artículos (solo request) ─────────────────────────────────────
            if rec.request_id:
                items = rec.request_id.item_ids.filtered(lambda i: i.production_id)
                rec.req_item_total       = len(rec.request_id.item_ids)
                rec.req_item_confirmed   = len(items.filtered(lambda i: i.production_id.state == 'confirmed'))
                rec.req_item_in_progress = len(items.filtered(lambda i: i.production_id.state in ('progress', 'to_close')))
                rec.req_item_done        = len(items.filtered(lambda i: i.production_id.state == 'done'))
                rec.req_item_delayed     = len(items.filtered(
                    lambda i: i.production_id.state not in ('done', 'cancel')
                    and i.production_id.date_finished
                    and i.production_id.date_finished < now
                ))
                rec.req_item_reschedule  = len(items.filtered(lambda i: i.production_id.x_reschedule_needed))
            else:
                rec.req_item_total = rec.req_item_confirmed = rec.req_item_in_progress = 0
                rec.req_item_done  = rec.req_item_delayed   = rec.req_item_reschedule  = 0

            # ── Alertas ──────────────────────────────────────────────────────
            if rec.purchase_id and not rec.request_id and not rec.production_id:
                alerts = Alert.search([('purchase_id', '=', rec.purchase_id.id), ('resolved', '=', False)])
            else:
                alerts = Alert.search([('production_id', 'in', mo_ids), ('resolved', '=', False)])
            rec.alert_total    = len(alerts)
            rec.alert_critical = len(alerts.filtered(lambda a: a.severity == 'critical'))
            rec.alert_warning  = len(alerts.filtered(lambda a: a.severity == 'warning'))

            # ── Planes (request + production) ────────────────────────────────
            if mo_ids and rec.context_type in ('request', 'production'):
                plans = Plan.search([('production_id', 'in', mo_ids), ('state', '!=', 'cancelled')])
                rec.plan_total   = len(plans)
                rec.plan_pending = len(plans.filtered(lambda p: p.state in ('draft', 'in_progress')))
                rec.plan_applied = len(plans.filtered(lambda p: p.state == 'applied'))
            else:
                rec.plan_total = rec.plan_pending = rec.plan_applied = 0

            # ── OFs ──────────────────────────────────────────────────────────
            rec.mo_total       = len(mos)
            rec.mo_confirmed   = len(mos.filtered(lambda m: m.state == 'confirmed'))
            rec.mo_in_progress = len(mos.filtered(lambda m: m.state in ('progress', 'to_close')))
            rec.mo_done        = len(mos.filtered(lambda m: m.state == 'done'))
            rec.mo_delayed     = len(mos.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.date_finished and m.date_finished < now
            ))

            # ── OCs (request + production) ────────────────────────────────────
            if rec.context_type in ('request', 'production'):
                pos = rec._get_context_pos()
                rec.po_total   = len(pos)
                rec.po_overdue = len(pos.filtered(
                    lambda p: p.state == 'purchase' and p.date_planned and p.date_planned < now
                ))
            else:
                rec.po_total = rec.po_overdue = 0

    # ── Apertura estática ─────────────────────────────────────────────────────

    @api.model
    def action_open_for_request(self, request_id):
        req = self.env['mrp.production.request'].browse(request_id)
        rec = self.create({'request_id': request_id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel — %s') % req.name,
            'res_model': 'mrp.planner.detail.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def action_open_for_production(self, production_id):
        mo = self.env['mrp.production'].browse(production_id)
        rec = self.create({'production_id': production_id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel — %s') % mo.name,
            'res_model': 'mrp.planner.detail.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def action_open_for_purchase(self, purchase_id):
        po = self.env['purchase.order'].browse(purchase_id)
        rec = self.create({'purchase_id': purchase_id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel — %s') % po.name,
            'res_model': 'mrp.planner.detail.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
            'flags': {'withControlPanel': False},
        }

    # ── Registro fuente ───────────────────────────────────────────────────────

    def action_open_source(self):
        self.ensure_one()
        if self.request_id:
            return {'type': 'ir.actions.act_window', 'res_model': 'mrp.production.request',
                    'res_id': self.request_id.id, 'view_mode': 'form', 'target': 'current'}
        if self.production_id:
            return {'type': 'ir.actions.act_window', 'res_model': 'mrp.production',
                    'res_id': self.production_id.id, 'view_mode': 'form', 'target': 'current'}
        if self.purchase_id:
            return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order',
                    'res_id': self.purchase_id.id, 'view_mode': 'form', 'target': 'current'}

    # ── Navegación — alertas ──────────────────────────────────────────────────

    def _alert_base_domain(self):
        if self.purchase_id and not self.request_id and not self.production_id:
            return [('purchase_id', '=', self.purchase_id.id), ('resolved', '=', False)]
        mo_ids = self._get_context_mos().ids
        return [('production_id', 'in', mo_ids), ('resolved', '=', False)]

    def action_view_all_alerts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Alertas'),
                'res_model': 'mrp.reschedule.alert', 'view_mode': 'list,form',
                'domain': self._alert_base_domain(), 'target': 'current'}

    def action_view_critical_alerts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Alertas críticas'),
                'res_model': 'mrp.reschedule.alert', 'view_mode': 'list,form',
                'domain': self._alert_base_domain() + [('severity', '=', 'critical')],
                'target': 'current'}

    def action_view_warning_alerts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Avisos'),
                'res_model': 'mrp.reschedule.alert', 'view_mode': 'list,form',
                'domain': self._alert_base_domain() + [('severity', '=', 'warning')],
                'target': 'current'}

    # ── Navegación — planes ───────────────────────────────────────────────────

    def _plan_base_domain(self):
        mo_ids = self._get_context_mos().ids
        return [('production_id', 'in', mo_ids), ('state', '!=', 'cancelled')]

    def action_view_all_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Planes de reprogramación'),
                'res_model': 'mrp.reschedule.plan', 'view_mode': 'list,form',
                'domain': self._plan_base_domain(), 'target': 'current'}

    def action_view_pending_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Planes pendientes'),
                'res_model': 'mrp.reschedule.plan', 'view_mode': 'list,form',
                'domain': self._plan_base_domain() + [('state', 'in', ('draft', 'in_progress'))],
                'target': 'current'}

    def action_view_applied_plans(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Planes aplicados'),
                'res_model': 'mrp.reschedule.plan', 'view_mode': 'list,form',
                'domain': self._plan_base_domain() + [('state', '=', 'applied')],
                'target': 'current'}

    # ── Navegación — OFs ──────────────────────────────────────────────────────

    def action_view_all_mos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Órdenes de fabricación'),
                'res_model': 'mrp.production', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._get_context_mos().ids)], 'target': 'current'}

    def action_view_delayed_mos(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return {'type': 'ir.actions.act_window', 'name': _('OFs atrasadas'),
                'res_model': 'mrp.production', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._get_context_mos().ids),
                           ('state', 'not in', ('done', 'cancel')),
                           ('date_finished', '<', now), ('date_finished', '!=', False)],
                'target': 'current'}

    def action_view_reschedule_mos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('OFs para reprogramar'),
                'res_model': 'mrp.production', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._get_context_mos().ids),
                           ('x_reschedule_needed', '=', True)],
                'target': 'current'}

    # ── Navegación — OCs ──────────────────────────────────────────────────────

    def action_view_all_pos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Órdenes de compra'),
                'res_model': 'purchase.order', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._get_context_pos().ids)], 'target': 'current'}

    def action_view_overdue_pos(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return {'type': 'ir.actions.act_window', 'name': _('OCs vencidas'),
                'res_model': 'purchase.order', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._get_context_pos().ids),
                           ('state', '=', 'purchase'), ('date_planned', '<', now)],
                'target': 'current'}
