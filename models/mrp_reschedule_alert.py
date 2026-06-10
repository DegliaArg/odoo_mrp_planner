import logging
from datetime import datetime

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class MrpRescheduleAlert(models.Model):
    _name = 'mrp.reschedule.alert'
    _description = 'Alerta de planificación de producción'
    _order = 'resolved asc, severity desc, days_late desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)

    alert_type = fields.Selection([
        ('mo_delayed',      'OF atrasada'),
        ('po_delayed',      'OC vencida'),
        ('receipt_delayed', 'Recepción atrasada'),
        ('mo_cancelled',    'OF cancelada'),
    ], string='Tipo', required=True)

    severity = fields.Selection([
        ('warning',  'Aviso'),
        ('critical', 'Crítico'),
    ], string='Severidad', required=True, default='warning')

    production_id = fields.Many2one('mrp.production', string='Orden de fabricación',
                                    ondelete='cascade', index=True)
    purchase_id   = fields.Many2one('purchase.order',  string='Orden de compra',
                                    ondelete='cascade', index=True)
    picking_id    = fields.Many2one('stock.picking',   string='Recepción',
                                    ondelete='cascade', index=True)

    days_late = fields.Integer(string='Días de atraso')
    message   = fields.Char(string='Detalle')

    resolved     = fields.Boolean(string='Resuelta', default=False)
    resolve_date = fields.Datetime(string='Resuelta el', readonly=True)
    plan_id      = fields.Many2one('mrp.reschedule.plan', string='Plan generado', readonly=True)

    active = fields.Boolean(default=True)

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('alert_type', 'production_id', 'purchase_id', 'picking_id', 'days_late')
    def _compute_name(self):
        type_labels = dict(self._fields['alert_type'].selection)
        for alert in self:
            ref = (
                (alert.production_id.name if alert.production_id else None)
                or (alert.purchase_id.name if alert.purchase_id else None)
                or (alert.picking_id.name if alert.picking_id else None)
                or ''
            )
            label = type_labels.get(alert.alert_type, alert.alert_type)
            suffix = f' ({alert.days_late}d)' if alert.days_late else ''
            alert.name = f'{label} — {ref}{suffix}' if ref else f'{label}{suffix}'

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_resolve(self):
        self.write({'resolved': True, 'resolve_date': fields.Datetime.now()})

    def action_create_reschedule_plan(self):
        """Crea (o abre) el plan de reprogramación asociado a esta alerta."""
        self.ensure_one()
        if self.plan_id and self.plan_id.state not in ('applied', 'cancelled'):
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.reschedule.plan',
                'res_id': self.plan_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

        mo = self.production_id
        if not mo and self.purchase_id:
            mo = self.env['mrp.production'].search([
                ('state', 'in', ('confirmed', 'progress')),
                '|',
                ('purchase_order_id', '=', self.purchase_id.id),
                ('purchase_line_id.order_id', '=', self.purchase_id.id),
            ], limit=1)

        plan_vals = {'replan_from': fields.Datetime.now()}
        if mo:
            plan_vals['production_id'] = mo.id
            if mo.date_finished:
                plan_vals['new_finish_date'] = mo.date_finished

        plan = self.env['mrp.reschedule.plan'].create(plan_vals)
        self.plan_id = plan.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.reschedule.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Cron ─────────────────────────────────────────────────────────────────

    @api.model
    def _cron_check_delays(self):
        """Ejecutado diariamente. Detecta desvíos y crea/actualiza alertas."""
        now = datetime.utcnow()
        self._check_delayed_mos(now)
        self._check_delayed_pos(now)
        self._check_delayed_receipts(now)
        self._auto_resolve_stale()

    @api.model
    def _check_delayed_mos(self, now):
        mos = self.env['mrp.production'].search([
            ('state', '=', 'progress'),
            ('date_finished', '<', now),
            ('date_finished', '!=', False),
        ])
        for mo in mos:
            days = max(0, (now - mo.date_finished).days)
            severity = 'critical' if days >= 3 else 'warning'
            msg = _('Fin planificado: %s') % mo.date_finished.strftime('%d/%m/%Y %H:%M')
            self._upsert_alert('mo_delayed', severity, days, msg, production_id=mo.id)

    @api.model
    def _check_delayed_pos(self, now):
        pos = self.env['purchase.order'].search([
            ('state', '=', 'purchase'),
            ('date_planned', '<', now),
        ])
        for po in pos:
            days = max(0, (now - po.date_planned).days)
            severity = 'critical' if days >= 5 else 'warning'
            msg = _('Entrega planificada: %s') % po.date_planned.strftime('%d/%m/%Y')
            self._upsert_alert('po_delayed', severity, days, msg, purchase_id=po.id)

    @api.model
    def _check_delayed_receipts(self, now):
        pickings = self.env['stock.picking'].search([
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_code', '=', 'incoming'),
            ('scheduled_date', '<', now),
        ])
        for picking in pickings:
            days = max(0, (now - picking.scheduled_date).days)
            severity = 'critical' if days >= 3 else 'warning'
            msg = _('Fecha prevista: %s') % picking.scheduled_date.strftime('%d/%m/%Y')
            self._upsert_alert('receipt_delayed', severity, days, msg, picking_id=picking.id)

    @api.model
    def _upsert_alert(self, alert_type, severity, days_late, message, **record_fields):
        """Crea la alerta si no existe; actualiza si ya existe."""
        domain = [('alert_type', '=', alert_type), ('resolved', '=', False)]
        for fname, fval in record_fields.items():
            if fval:
                domain.append((fname, '=', fval))
        existing = self.search(domain, limit=1)
        if existing:
            existing.write({'days_late': days_late, 'severity': severity, 'message': message})
        else:
            vals = {'alert_type': alert_type, 'severity': severity,
                    'days_late': days_late, 'message': message}
            vals.update(record_fields)
            self.create(vals)

    @api.model
    def _auto_resolve_stale(self):
        """Resuelve automáticamente alertas cuyos registros ya se normalizaron."""
        now = fields.Datetime.now()

        stale_mo = self.search([
            ('alert_type', 'in', ('mo_delayed', 'mo_cancelled')),
            ('resolved', '=', False),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_mo:
            stale_mo.write({'resolved': True, 'resolve_date': now})

        stale_po = self.search([
            ('alert_type', '=', 'po_delayed'),
            ('resolved', '=', False),
            ('purchase_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_po:
            stale_po.write({'resolved': True, 'resolve_date': now})

        stale_pick = self.search([
            ('alert_type', '=', 'receipt_delayed'),
            ('resolved', '=', False),
            ('picking_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_pick:
            stale_pick.write({'resolved': True, 'resolve_date': now})
