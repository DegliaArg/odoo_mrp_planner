from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain
from .const import DEFAULT_PO_CRITICAL_DAYS


class MrpPlannerDetailDashboard(models.TransientModel):
    _name = 'mrp.planner.detail.dashboard'
    _description = 'Panel de detalle del planificador'

    category = fields.Selection([
        ('mos',      'Órdenes de fabricación'),
        ('pos',      'Órdenes de compra'),
        ('requests', 'Programaciones'),
    ], required=True, default='mos')

    name = fields.Char(compute='_compute_name')

    # ── OFs (category='mos') ─────────────────────────────────────────────────
    mo_total             = fields.Integer(compute='_compute_all')
    mo_confirmed         = fields.Integer(compute='_compute_all')
    mo_in_progress       = fields.Integer(compute='_compute_all')
    mo_done              = fields.Integer(compute='_compute_all')
    mo_delayed           = fields.Integer(compute='_compute_all')
    mo_reschedule_needed = fields.Integer(compute='_compute_all')
    mo_wc_count          = fields.Integer(compute='_compute_all')

    # ── OCs (category='pos') ─────────────────────────────────────────────────
    po_total            = fields.Integer(compute='_compute_all')
    po_pending          = fields.Integer(compute='_compute_all')
    po_overdue          = fields.Integer(compute='_compute_all')
    po_overdue_critical = fields.Integer(compute='_compute_all')

    # ── Programaciones (category='requests') ─────────────────────────────────
    req_total       = fields.Integer(compute='_compute_all')
    req_reschedule  = fields.Integer(compute='_compute_all')
    req_mos_total   = fields.Integer(compute='_compute_all')
    req_mos_delayed = fields.Integer(compute='_compute_all')
    req_mos_done    = fields.Integer(compute='_compute_all')

    @api.depends('category')
    def _compute_name(self):
        labels = dict(self._fields['category'].selection)
        for rec in self:
            rec.name = labels.get(rec.category, 'Panel')

    @api.depends('category')
    def _compute_all(self):
        MO  = self.env['mrp.production']
        PO  = self.env['purchase.order']
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)

        for rec in self:
            cat = rec.category

            # ── OFs ──────────────────────────────────────────────────────────
            if cat == 'mos':
                active = MO.search([('state', 'not in', ('done', 'cancel'))] + no_sc)
                delayed = active.filtered(lambda m: m.date_finished and m.date_finished < now)
                rec.mo_total             = len(active)
                rec.mo_confirmed         = len(active.filtered(lambda m: m.state == 'confirmed'))
                rec.mo_in_progress       = len(active.filtered(lambda m: m.state in ('progress', 'to_close')))
                rec.mo_done              = MO.search_count([('state', '=', 'done')] + no_sc)
                rec.mo_delayed           = len(delayed)
                rec.mo_reschedule_needed = len(active.filtered(lambda m: m.x_reschedule_needed))
                rec.mo_wc_count          = len(active.mapped('workorder_ids.workcenter_id'))
            else:
                rec.mo_total = rec.mo_confirmed = rec.mo_in_progress = 0
                rec.mo_done = rec.mo_delayed = rec.mo_reschedule_needed = rec.mo_wc_count = 0

            # ── OCs ──────────────────────────────────────────────────────────
            if cat == 'pos':
                # FIX [FASE-3]: umbral crítico de días leído de config (antes hardcodeado en 5)
                cfg = self.env['mrp.reschedule.config'].get_config()
                po_crit_days = cfg.alert_po_critical_days if cfg else DEFAULT_PO_CRITICAL_DAYS
                active_pos = PO.search([('state', '=', 'purchase')])
                overdue = active_pos.filtered(lambda p: p.date_planned and p.date_planned < now)
                rec.po_total            = len(active_pos)
                rec.po_pending          = len(active_pos.filtered(
                    lambda p: not p.date_planned or p.date_planned >= now
                ))
                rec.po_overdue          = len(overdue)
                rec.po_overdue_critical = len(overdue.filtered(
                    lambda p: (now - p.date_planned).days >= po_crit_days
                ))
            else:
                rec.po_total = rec.po_pending = rec.po_overdue = rec.po_overdue_critical = 0

            # ── Programaciones ────────────────────────────────────────────────
            if cat == 'requests':
                reqs = Req.search([('state', '=', 'confirmed')])
                all_mos = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id)
                delayed_req = all_mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )
                rec.req_total       = len(reqs)
                rec.req_reschedule  = len(reqs.filtered(
                    lambda r: any(
                        it.production_id and it.production_id.x_reschedule_needed
                        for it in r.item_ids
                    )
                ))
                rec.req_mos_total   = len(all_mos)
                rec.req_mos_delayed = len(delayed_req)
                rec.req_mos_done    = len(all_mos.filtered(lambda m: m.state == 'done'))
            else:
                rec.req_total = rec.req_reschedule = 0
                rec.req_mos_total = rec.req_mos_delayed = rec.req_mos_done = 0

    # ── Apertura ─────────────────────────────────────────────────────────────

    @api.model
    def action_open_for_category(self, category):
        labels = dict(self._fields['category'].selection)
        rec = self.create({'category': category})
        return {
            'type': 'ir.actions.act_window',
            'name': labels.get(category, _('Panel')),
            'res_model': 'mrp.planner.detail.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
            'flags': {'withControlPanel': False},
        }

    # ── Navegación — volver ───────────────────────────────────────────────────

    def action_back(self):
        return self.env['mrp.planner.dashboard'].action_open()

    # ── Navegación — OFs ──────────────────────────────────────────────────────

    def action_view_all_mos(self):
        no_sc = no_subcontract_domain(self.env)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de fabricación activas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('state', 'not in', ('done', 'cancel'))] + no_sc,
            'target': 'current',
        }

    def action_view_delayed_mos(self):
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs atrasadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'not in', ('done', 'cancel')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc,
            'target': 'current',
        }

    def action_view_reschedule_mos(self):
        no_sc = no_subcontract_domain(self.env)
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs para reprogramar'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc,
            'target': 'current',
        }

    # ── Navegación — OCs ──────────────────────────────────────────────────────

    def action_view_all_pos(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de compra activas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'purchase')],
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

    def action_view_critical_pos(self):
        now = fields.Datetime.now()
        cfg = self.env['mrp.reschedule.config'].get_config()
        po_crit_days = cfg.alert_po_critical_days if cfg else DEFAULT_PO_CRITICAL_DAYS
        from datetime import timedelta
        crit_threshold = now - timedelta(days=po_crit_days)
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs críticas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'purchase'),
                ('date_planned', '<', crit_threshold),
                ('receipt_status', '!=', 'full'),
            ],
            'target': 'current',
        }

    # ── Navegación — Programaciones ───────────────────────────────────────────

    def action_view_all_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones en curso'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_reschedule_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con reprogramación'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'confirmed'),
                ('item_ids.production_id.x_reschedule_needed', '=', True),
            ],
            'target': 'current',
        }

    def action_view_req_mos(self):
        reqs = self.env['mrp.production.request'].search([('state', '=', 'confirmed')])
        mo_ids = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs en programaciones activas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mo_ids)],
            'target': 'current',
        }

    def action_view_req_delayed_mos(self):
        now = fields.Datetime.now()
        reqs = self.env['mrp.production.request'].search([('state', '=', 'confirmed')])
        mo_ids = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs atrasadas en programaciones'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('id', 'in', mo_ids),
                ('state', 'not in', ('done', 'cancel')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ],
            'target': 'current',
        }
