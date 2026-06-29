import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

_logger = logging.getLogger(__name__)

QTY_TOLERANCE = 0.05  # fallback; sobreescrito por mrp.reschedule.config


class MrpRescheduleAlert(models.Model):
    _name = 'mrp.reschedule.alert'
    _description = 'Alerta de planificación de producción'
    _order = 'resolved asc, severity desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)

    alert_type = fields.Selection([
        ('mo_delayed',      'OF atrasada'),
        ('mo_upcoming',     'OF por vencer'),
        ('po_delayed',      'OC vencida'),
        ('po_upcoming',     'OC por vencer'),
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

    days_late = fields.Integer(string='Días de atraso', compute='_compute_days_late', store=False)
    message   = fields.Char(string='Detalle')

    resolved     = fields.Boolean(string='Resuelta', default=False)
    resolve_date = fields.Datetime(string='Resuelta el', readonly=True)
    plan_id      = fields.Many2one('mrp.reschedule.plan', string='Plan generado', readonly=True)

    active = fields.Boolean(default=True)

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('alert_type', 'production_id', 'purchase_id', 'picking_id')
    def _compute_name(self):
        type_labels = dict(self._fields['alert_type'].selection)
        for alert in self:
            ref = (
                (alert.production_id.name if alert.production_id else None)
                or (alert.purchase_id.name if alert.purchase_id else None)
                or (alert.picking_id.name  if alert.picking_id  else None)
                or ''
            )
            label = type_labels.get(alert.alert_type, alert.alert_type)
            alert.name = f'{label} — {ref}' if ref else label

    @api.depends()
    def _compute_days_late(self):
        """Calcula días de atraso en tiempo real desde la fecha del registro fuente."""
        now = datetime.utcnow()
        for alert in self:
            ref_date = None
            atype = alert.alert_type
            if atype in ('mo_delayed', 'mo_upcoming', 'qty_mismatch', 'mo_cancelled'):
                if alert.production_id and alert.production_id.date_finished:
                    ref_date = alert.production_id.date_finished
            elif atype in ('po_delayed', 'po_upcoming', 'po_cancelled'):
                if alert.purchase_id and alert.purchase_id.date_planned:
                    ref_date = alert.purchase_id.date_planned
            elif atype == 'receipt_delayed':
                if alert.picking_id and alert.picking_id.scheduled_date:
                    ref_date = alert.picking_id.scheduled_date
            if ref_date:
                alert.days_late = max(0, (now - ref_date).days)
            else:
                alert.days_late = 0

    def _compute_impact_mo_count(self):
        # Usar .ids evita cargar los campos de los registros relacionados
        for alert in self:
            alert.impact_mo_count = len(alert.impact_mo_ids.ids)

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
            MO = self.env['mrp.production']
            mo_fields = MO._fields
            try:
                domain = [('state', 'in', ('confirmed', 'progress'))]
                or_clauses = []
                if 'purchase_order_id' in mo_fields:
                    or_clauses.append(('purchase_order_id', '=', self.purchase_id.id))
                if 'purchase_line_id' in mo_fields:
                    or_clauses.append(('purchase_line_id.order_id', '=', self.purchase_id.id))
                if or_clauses:
                    if len(or_clauses) == 2:
                        domain = domain + ['|'] + or_clauses
                    else:
                        domain = domain + or_clauses
                    mo = MO.search(domain, limit=1)
                if not mo:
                    mo = MO.search([
                        ('state', 'in', ('confirmed', 'progress')),
                        ('origin', 'ilike', self.purchase_id.name),
                    ], limit=1)
            except Exception as e:
                _logger.warning('MRP Reschedule: no se pudo buscar OF para alerta %s: %s', self.id, e)

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
        """Botón manual: ejecuta el chequeo de alertas ahora (solo para responsables)."""
        # FIX [FASE-2]: sin este guard cualquier usuario puede disparar búsquedas masivas
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            from odoo.exceptions import UserError
            raise UserError(_(
                'Solo los responsables de fabricación pueden ejecutar el chequeo de alertas manualmente.'
            ))
        self._cron_check_delays()
        return self.env.ref('odoo_mrp_planner.action_mrp_reschedule_alert').read()[0]

    # ── Helpers — impacto ────────────────────────────────────────────────────

    @api.model
    def _find_impact_mos(self, product_id, available_qty, cache=None):
        """Retorna MOs confirmadas/en progreso que consumen product_id y
        cuya demanda acumulada supera el stock disponible (orden cronológico)."""
        if cache is not None and product_id in cache:
            return cache[product_id]

        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', '=', product_id),
        ] + no_subcontract_domain(self.env)).sorted(lambda m: m.date_start or datetime(9999, 12, 31))

        # Prefetch all raw moves in one query
        mos.mapped('move_raw_ids')

        impacted   = self.env['mrp.production']
        cumulative = 0.0
        for mo in mos:
            required = sum(
                (m.product_uom_qty - (getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)))
                for m in mo.move_raw_ids
                if m.product_id.id == product_id
                and m.state not in ('done', 'cancel')
            )
            if required <= 0:
                continue
            cumulative += required
            if cumulative > available_qty:
                impacted |= mo

        if cache is not None:
            cache[product_id] = impacted
        return impacted

    # ── Cron ─────────────────────────────────────────────────────────────────

    @api.model
    def _cron_check_delays(self):
        """Ejecutado periódicamente. Detecta desvíos y crea/actualiza alertas."""
        now = datetime.utcnow()
        impact_cache = {}
        steps = [
            (self._check_delayed_mos,     (now,)),
            (self._check_upcoming_mos,    (now,)),
            (self._check_delayed_pos,     (now, impact_cache)),
            (self._check_upcoming_pos,    (now,)),
            (self._check_delayed_receipts,(now, impact_cache)),
            (self._check_qty_mismatches,  (now, impact_cache)),
            (self._auto_resolve_stale,    ()),
        ]
        for fn, args in steps:
            try:
                fn(*args)
            except Exception as e:
                _logger.warning('MRP Reschedule cron: error en %s: %s', fn.__name__, e)

    def _get_config(self):
        return self.env['mrp.reschedule.config'].search([], limit=1)

    @api.model
    def _check_delayed_mos(self, now):
        cfg = self._get_config()
        crit_days = cfg.alert_mo_critical_days if cfg else 3
        mos = self.env['mrp.production'].search([
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
            ('date_finished', '<', now),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        # Preload all open mo_delayed alerts indexed by production_id
        by_mo = {
            a.production_id.id: a
            for a in self.search([('alert_type', '=', 'mo_delayed'), ('resolved', '=', False)])
        }

        to_create = []
        for mo in mos:
            days = max(0, (now - mo.date_finished).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Fin planificado: %s') % mo.date_finished.strftime('%d/%m/%Y %H:%M')
            write_vals = {'severity': severity, 'message': msg}
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'mo_delayed',
                    'production_id': mo.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_upcoming_mos(self, now):
        cfg = self._get_config()
        warn_days = cfg.alert_mo_warning_days if cfg else 7
        future_limit = now + timedelta(days=warn_days)

        mos = self.env['mrp.production'].search([
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
            ('date_finished', '>=', now),
            ('date_finished', '<=', future_limit),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        by_mo = {
            a.production_id.id: a
            for a in self.search([('alert_type', '=', 'mo_upcoming'), ('resolved', '=', False)])
        }

        to_create = []
        for mo in mos:
            days_until = max(0, (mo.date_finished - now).days)
            msg = _('Vence el: %s (en %d días)') % (mo.date_finished.strftime('%d/%m/%Y'), days_until)
            write_vals = {'severity': 'warning', 'message': msg}
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'mo_upcoming',
                    'production_id': mo.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_delayed_pos(self, now, impact_cache=None):
        cfg = self._get_config()
        crit_days = cfg.alert_po_critical_days if cfg else 5
        pos = self.env['purchase.order'].search([
            ('state', '=', 'purchase'),
            ('date_planned', '<', now),
        ])

        # Preload all open po_delayed alerts indexed by purchase_id
        by_po = {
            a.purchase_id.id: a
            for a in self.search([('alert_type', '=', 'po_delayed'), ('resolved', '=', False)])
        }

        # Batch-read qty_available for ALL products across ALL POs in one shot
        all_product_ids = set()
        for po in pos:
            all_product_ids.update(po.order_line.mapped('product_id').ids)
        if all_product_ids:
            products = self.env['product.product'].browse(list(all_product_ids))
            qty_by_product = {p.id: p.qty_available for p in products}
        else:
            qty_by_product = {}

        to_create = []
        for po in pos:
            days = max(0, (now - po.date_planned).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Entrega planificada: %s') % po.date_planned.strftime('%d/%m/%Y')

            product_ids = po.order_line.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                impacted |= self._find_impact_mos(pid, qty_by_product.get(pid, 0), cache=impact_cache)

            write_vals = {
                'severity':  severity,
                'message':   msg,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if po.id in by_po:
                by_po[po.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type': 'po_delayed',
                    'purchase_id': po.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_upcoming_pos(self, now):
        cfg = self._get_config()
        warn_days = cfg.alert_po_warning_days if cfg else 10
        future_limit = now + timedelta(days=warn_days)

        pos = self.env['purchase.order'].search([
            ('state', '=', 'purchase'),
            ('receipt_status', '!=', 'full'),
            ('date_planned', '>=', now),
            ('date_planned', '<=', future_limit),
        ])

        by_po = {
            a.purchase_id.id: a
            for a in self.search([('alert_type', '=', 'po_upcoming'), ('resolved', '=', False)])
        }

        to_create = []
        for po in pos:
            days_until = max(0, (po.date_planned - now).days)
            msg = _('Entrega prevista: %s (en %d días)') % (po.date_planned.strftime('%d/%m/%Y'), days_until)
            write_vals = {'severity': 'warning', 'message': msg}
            if po.id in by_po:
                by_po[po.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':  'po_upcoming',
                    'purchase_id': po.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_delayed_receipts(self, now, impact_cache=None):
        cfg = self._get_config()
        crit_days = cfg.alert_receipt_critical_days if cfg else 3
        pickings = self.env['stock.picking'].search([
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_code', '=', 'incoming'),
            ('purchase_id', '!=', False),
            ('scheduled_date', '<', now),
        ])

        # Preload all open receipt_delayed alerts indexed by picking_id
        by_picking = {
            a.picking_id.id: a
            for a in self.search([('alert_type', '=', 'receipt_delayed'), ('resolved', '=', False)])
        }

        # Batch-read qty_available for ALL products across ALL pickings in one shot
        all_product_ids = set()
        for picking in pickings:
            all_product_ids.update(picking.move_ids.mapped('product_id').ids)
        if all_product_ids:
            products = self.env['product.product'].browse(list(all_product_ids))
            qty_by_product = {p.id: p.qty_available for p in products}
        else:
            qty_by_product = {}

        to_create = []
        for picking in pickings:
            days = max(0, (now - picking.scheduled_date).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Fecha prevista: %s') % picking.scheduled_date.strftime('%d/%m/%Y')

            product_ids = picking.move_ids.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                impacted |= self._find_impact_mos(pid, qty_by_product.get(pid, 0), cache=impact_cache)

            write_vals = {
                'severity':  severity,
                'message':   msg,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if picking.id in by_picking:
                by_picking[picking.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type': 'receipt_delayed',
                    'picking_id': picking.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_qty_mismatches(self, now, impact_cache=None):
        """Detecta MOs recién cerradas con cantidad diferente a la planificada."""
        cfg = self._get_config()
        qty_tol = (cfg.qty_tolerance_pct / 100.0) if cfg else QTY_TOLERANCE
        # Dynamic window from config, matching cron interval + 10% margin
        if cfg:
            interval_number = cfg.cron_interval_number or 1
            interval_type = cfg.cron_interval_type or 'hours'
            type_to_hours = {'minutes': 1/60, 'hours': 1, 'days': 24}
            hours = interval_number * type_to_hours.get(interval_type, 1) * 1.1
        else:
            hours = 2.0
        since = now - timedelta(hours=max(hours, 0.5))
        done_mos = self.env['mrp.production'].search([
            ('state', '=', 'done'),
            ('date_finished', '>=', since),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        # Preload all open qty_mismatch alerts indexed by production_id
        by_mo = {
            a.production_id.id: a
            for a in self.search([('alert_type', '=', 'qty_mismatch'), ('resolved', '=', False)])
        }

        # Prefetch all finished moves in one query
        done_mos.mapped('move_finished_ids')

        to_create = []
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
            if delta <= qty_tol:
                continue
            # Calcular OFs afectadas por el delta de producción
            avail = mo.product_id.qty_available
            impacted = self._find_impact_mos(mo.product_id.id, avail, cache=impact_cache)
            severity = 'critical' if actual_qty < planned_qty else 'warning'
            msg = _('Planificado: %g | Real: %g (%.0f%%)') % (
                planned_qty, actual_qty, (actual_qty / planned_qty) * 100
            )
            write_vals = {
                'severity':     severity,
                'message':      msg,
                'expected_qty': planned_qty,
                'actual_qty':   actual_qty,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'qty_mismatch',
                    'production_id': mo.id,
                    'product_id':    mo.product_id.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _resolve_for(self, alert_types, **record_fields):
        """Resuelve inmediatamente alertas abiertas del tipo dado para un registro.
        Usado por los write() de OF/OC/Recepción para resolución reactiva.
        """
        domain = [('alert_type', 'in', list(alert_types)), ('resolved', '=', False)]
        for fname, fval in record_fields.items():
            if fval:
                domain.append((fname, '=', fval))
        alerts = self.search(domain)
        if alerts:
            alerts.write({'resolved': True, 'resolve_date': fields.Datetime.now()})

    @api.model
    def _auto_resolve_stale(self):
        """Resuelve alertas cuyos registros ya volvieron a estado normal.
        Actúa como red de seguridad: la resolución principal es reactiva (write()).
        Nota: mo_cancelled NO se resuelve aquí — debe resolverla el usuario a mano.
        """
        now = fields.Datetime.now()

        # Limpiar alertas de OFs subcontratadas — no deben generar alertas de producción
        # Usamos is_subcontracting_location porque las OFs SBC suelen tener bom_id=False
        stale_sc = self.search([
            ('alert_type', 'in', ('mo_delayed', 'mo_upcoming', 'mo_cancelled', 'qty_mismatch')),
            ('resolved', '=', False),
            ('production_id.location_src_id.is_subcontracting_location', '=', True),
        ])
        if stale_sc:
            stale_sc.write({'resolved': True, 'resolve_date': now})

        # mo_delayed y qty_mismatch: se resuelven cuando la OF termina o se cancela
        stale_mo = self.search([
            ('alert_type', 'in', ('mo_delayed', 'qty_mismatch')),
            ('resolved', '=', False),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_mo:
            stale_mo.write({'resolved': True, 'resolve_date': now})

        # mo_delayed: también se resuelve si la OF ya no está atrasada
        stale_mo_on_time = self.search([
            ('alert_type', '=', 'mo_delayed'),
            ('resolved', '=', False),
            ('production_id.date_finished', '>', now),
        ])
        if stale_mo_on_time:
            stale_mo_on_time.write({'resolved': True, 'resolve_date': now})

        # mo_upcoming: se resuelve cuando la OF ya venció (pasa a mo_delayed) o termina/cancela
        stale_upcoming_mo = self.search([
            ('alert_type', '=', 'mo_upcoming'),
            ('resolved', '=', False),
            '|',
            ('production_id.date_finished', '<', now),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_upcoming_mo:
            stale_upcoming_mo.write({'resolved': True, 'resolve_date': now})

        # po_upcoming: se resuelve cuando la OC ya venció (pasa a po_delayed) o se cancela/completa
        stale_upcoming_po = self.search([
            ('alert_type', '=', 'po_upcoming'),
            ('resolved', '=', False),
            '|',
            ('purchase_id.date_planned', '<', now),
            ('purchase_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_upcoming_po:
            stale_upcoming_po.write({'resolved': True, 'resolve_date': now})

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
