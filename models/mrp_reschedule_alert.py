import logging
from datetime import datetime

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

QTY_TOLERANCE = 0.05  # 5% de diferencia para disparar alerta


class MrpRescheduleAlert(models.Model):
    _name = 'mrp.reschedule.alert'
    _description = 'Alerta de planificación de producción'
    _order = 'resolved asc, severity desc, days_late desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)

    alert_type = fields.Selection([
        ('mo_delayed',      'OF atrasada'),
        ('po_delayed',      'OC vencida'),
        ('po_cancelled',    'OC cancelada'),
        ('receipt_delayed', 'Recepción atrasada'),
        ('qty_mismatch',    'Cantidad diferente'),
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
    product_id    = fields.Many2one('product.product', string='Producto', index=True)

    expected_qty  = fields.Float(string='Cantidad planificada', digits=(16, 2))
    actual_qty    = fields.Float(string='Cantidad real',        digits=(16, 2))

    impact_mo_ids = fields.Many2many(
        'mrp.production',
        'mrp_reschedule_alert_production_rel',
        'alert_id', 'production_id',
        string='OFs afectadas',
    )
    impact_mo_count = fields.Integer(compute='_compute_impact_mo_count', string='OFs afectadas')

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
                or (alert.picking_id.name  if alert.picking_id  else None)
                or ''
            )
            label  = type_labels.get(alert.alert_type, alert.alert_type)
            suffix = f' ({alert.days_late}d)' if alert.days_late else ''
            alert.name = f'{label} — {ref}{suffix}' if ref else f'{label}{suffix}'

    def _compute_impact_mo_count(self):
        for alert in self:
            alert.impact_mo_count = len(alert.impact_mo_ids)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_resolve(self):
        self.write({'resolved': True, 'resolve_date': fields.Datetime.now()})

    def action_view_impact_mos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs afectadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.impact_mo_ids.ids)],
            'target': 'current',
        }

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

    @api.model
    def action_run_cron_manual(self):
        """Botón manual: ejecuta el chequeo de alertas ahora."""
        self._cron_check_delays()
        return self.env.ref('odoo_mrp_reschedule.action_mrp_reschedule_alert').read()[0]

    # ── Helpers — impacto ────────────────────────────────────────────────────

    @api.model
    def _find_impact_mos(self, product_id, available_qty):
        """Retorna MOs confirmadas/en progreso que consumen product_id y
        cuya demanda acumulada supera el stock disponible (orden cronológico)."""
        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', '=', product_id),
        ]).sorted(lambda m: m.date_start or datetime(9999, 12, 31))

        impacted   = self.env['mrp.production']
        cumulative = 0.0
        for mo in mos:
            required = sum(
                (m.product_uom_qty - (m.quantity_done or 0.0))
                for m in mo.move_raw_ids
                if m.product_id.id == product_id
                and m.state not in ('done', 'cancel')
            )
            if required <= 0:
                continue
            cumulative += required
            if cumulative > available_qty:
                impacted |= mo
        return impacted

    # ── Cron ─────────────────────────────────────────────────────────────────

    @api.model
    def _cron_check_delays(self):
        """Ejecutado cada 30 minutos. Detecta desvíos y crea/actualiza alertas."""
        now = datetime.utcnow()
        self._check_delayed_mos(now)
        self._check_delayed_pos(now)
        self._check_delayed_receipts(now)
        self._check_qty_mismatches(now)
        self._auto_resolve_stale()

    @api.model
    def _check_delayed_mos(self, now):
        mos = self.env['mrp.production'].search([
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
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
            # Calcular OFs afectadas
            product_ids = po.order_line.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                product = self.env['product.product'].browse(pid)
                impacted |= self._find_impact_mos(pid, product.qty_available)
            self._upsert_alert('po_delayed', severity, days, msg,
                               purchase_id=po.id, impact_mo_ids=impacted.ids)

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
            product_ids = picking.move_ids.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                product = self.env['product.product'].browse(pid)
                impacted |= self._find_impact_mos(pid, product.qty_available)
            self._upsert_alert('receipt_delayed', severity, days, msg,
                               picking_id=picking.id, impact_mo_ids=impacted.ids)

    @api.model
    def _check_qty_mismatches(self, now):
        """Detecta MOs recién cerradas con cantidad diferente a la planificada."""
        from datetime import timedelta
        since = now - timedelta(hours=1)  # Solo las del último ciclo de cron
        done_mos = self.env['mrp.production'].search([
            ('state', '=', 'done'),
            ('date_finished', '>=', since),
            ('date_finished', '!=', False),
        ])
        for mo in done_mos:
            planned_qty = mo.product_qty
            if not planned_qty:
                continue
            # Cantidad real producida: suma de movimientos de salida terminados
            done_moves = mo.move_finished_ids.filtered(
                lambda m: m.state == 'done' and m.product_id == mo.product_id
            )
            actual_qty = sum(
                getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                for m in done_moves
            ) if done_moves else planned_qty
            if actual_qty == 0:
                actual_qty = planned_qty  # sin datos, no alertar
            delta = abs(actual_qty - planned_qty) / planned_qty
            if delta <= QTY_TOLERANCE:
                continue
            # Calcular OFs afectadas por el delta de producción
            avail = mo.product_id.qty_available
            impacted = self._find_impact_mos(mo.product_id.id, avail)
            severity = 'critical' if actual_qty < planned_qty else 'warning'
            msg = _('Planificado: %g | Real: %g (%.0f%%)') % (
                planned_qty, actual_qty, (actual_qty / planned_qty) * 100
            )
            self._upsert_alert(
                'qty_mismatch', severity, 0, msg,
                production_id=mo.id,
                product_id=mo.product_id.id,
                expected_qty=planned_qty,
                actual_qty=actual_qty,
                impact_mo_ids=impacted.ids,
            )

    @api.model
    def _upsert_alert(self, alert_type, severity, days_late, message, **record_fields):
        """Crea la alerta si no existe; actualiza days_late y severity si ya existe."""
        impact_mo_ids = record_fields.pop('impact_mo_ids', [])

        domain = [('alert_type', '=', alert_type), ('resolved', '=', False)]
        for fname, fval in record_fields.items():
            if fval:
                domain.append((fname, '=', fval))

        existing = self.search(domain, limit=1)
        write_vals = {'days_late': days_late, 'severity': severity, 'message': message}
        if impact_mo_ids:
            write_vals['impact_mo_ids'] = [(4, mid) for mid in impact_mo_ids]

        if existing:
            existing.write(write_vals)
        else:
            create_vals = {
                'alert_type': alert_type,
                'days_late':  days_late,
                'severity':   severity,
                'message':    message,
            }
            create_vals.update(record_fields)
            if impact_mo_ids:
                create_vals['impact_mo_ids'] = [(4, mid) for mid in impact_mo_ids]
            self.create(create_vals)

    @api.model
    def _auto_resolve_stale(self):
        """Resuelve alertas cuyos registros ya volvieron a estado normal."""
        now = fields.Datetime.now()

        stale_mo = self.search([
            ('alert_type', 'in', ('mo_delayed', 'mo_cancelled', 'qty_mismatch')),
            ('resolved', '=', False),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        stale_mo_delayed = self.search([
            ('alert_type', '=', 'mo_delayed'),
            ('resolved', '=', False),
            ('production_id.state', '=', 'done'),
        ])
        (stale_mo | stale_mo_delayed).write({'resolved': True, 'resolve_date': now})

        stale_po = self.search([
            ('alert_type', 'in', ('po_delayed', 'po_cancelled')),
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
