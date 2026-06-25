from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

import logging
_logger = logging.getLogger(__name__)

QTY_TOLERANCE = 0.05


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _where_calc(self, domain, active_test=True):
        # Workaround Odoo 18 bug: mrp.stock_rule._run_manufacture construye el
        # domain como tupla en vez de lista, causando TypeError en _where_calc.
        if isinstance(domain, tuple):
            domain = list(domain)
        return super()._where_calc(domain, active_test=active_test)

    # ── Fase 2: vínculo tipado a la OF madre ────────────────────────────────

    x_parent_mo_id = fields.Many2one(
        'mrp.production',
        string='OF madre',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
        help='Vínculo tipado a la orden de fabricación que generó esta. '
             'Más confiable que el campo Origen (texto).',
    )

    # ── Fase 4: flag de reprogramación sugerida ──────────────────────────────

    x_reschedule_needed = fields.Boolean(
        string='Reprogramación sugerida',
        copy=False,
        help='Indica que un cambio reciente en esta orden puede afectar '
             'la programación de las órdenes subsecuentes. '
             'Se limpia automáticamente al abrir el wizard.',
    )

    # ── Fase 4: override de write() para detección semi-automática ───────────

    def write(self, vals):
        trigger_state = 'state' in vals and vals['state'] in ('done', 'cancel')
        going_done = trigger_state and vals['state'] == 'done'
        track_date = 'date_finished' in vals

        if trigger_state:
            old_states = {mo.id: mo.state for mo in self}
        if going_done:
            planned_qtys = {mo.id: mo.product_qty for mo in self}

        result = super().write(vals)

        if trigger_state:
            for mo in self:
                old_state = old_states.get(mo.id, mo.state)
                if old_state in ('done', 'cancel'):
                    continue

                try:
                    self._flag_subsequent_mos(mo)
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al marcar MOs subsecuentes de %s: %s',
                        mo.name, e,
                    )

                if mo.state == 'cancel':
                    # Resolver alertas de atraso inmediatamente al cancelar
                    try:
                        self.env['mrp.reschedule.alert']._resolve_for(
                            ('mo_delayed', 'qty_mismatch'),
                            production_id=mo.id,
                        )
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al resolver alertas de %s: %s',
                            mo.name, e,
                        )
                    # Crear alerta de cancelación (requiere resolución manual)
                    try:
                        self.env['mrp.reschedule.alert']._upsert_alert(
                            'mo_cancelled', 'critical', 0,
                            _('OF cancelada: %s') % mo.name,
                            production_id=mo.id,
                        )
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al crear alerta de cancelación de %s: %s',
                            mo.name, e,
                        )

                if mo.state == 'done':
                    # Resolver alerta de atraso al completar
                    try:
                        self.env['mrp.reschedule.alert']._resolve_for(
                            ('mo_delayed',),
                            production_id=mo.id,
                        )
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al resolver alertas de %s: %s',
                            mo.name, e,
                        )

                if mo.state == 'done' and going_done:
                    planned_qty = planned_qtys.get(mo.id, 0)
                    if planned_qty:
                        try:
                            done_moves = mo.move_finished_ids.filtered(
                                lambda m: m.state == 'done' and m.product_id == mo.product_id
                            )
                            actual_qty = sum(
                                getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                                for m in done_moves
                            ) if done_moves else planned_qty
                            if actual_qty == 0:
                                actual_qty = planned_qty
                            delta = abs(actual_qty - planned_qty) / planned_qty
                            if delta > QTY_TOLERANCE:
                                alert_env = self.env['mrp.reschedule.alert']
                                avail = mo.product_id.qty_available
                                impacted = alert_env._find_impact_mos(mo.product_id.id, avail)
                                severity = 'critical' if actual_qty < planned_qty else 'warning'
                                msg = _('Planificado: %g | Real: %g (%.0f%%)') % (
                                    planned_qty, actual_qty, (actual_qty / planned_qty) * 100
                                )
                                alert_env._upsert_alert(
                                    'qty_mismatch', severity, 0, msg,
                                    production_id=mo.id,
                                    product_id=mo.product_id.id,
                                    expected_qty=planned_qty,
                                    actual_qty=actual_qty,
                                    impact_mo_ids=impacted.ids,
                                )
                        except Exception as e:
                            _logger.warning(
                                'MRP Reschedule: error al crear alerta de cantidad de %s: %s',
                                mo.name, e,
                            )
        # Resolución reactiva: OF reprogramada a fecha futura → ya no está atrasada
        if track_date:
            now = fields.Datetime.now()
            for mo in self:
                if mo.date_finished and mo.date_finished > now:
                    try:
                        self.env['mrp.reschedule.alert']._resolve_for(
                            ('mo_delayed',),
                            production_id=mo.id,
                        )
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al resolver alerta de atraso de %s: %s',
                            mo.name, e,
                        )

        return result

    def _flag_subsequent_mos(self, mo):
        """
        Busca MOs subsecuentes en los mismos WC y activa x_reschedule_needed.
        Solo busca las más próximas (limit=20) para no afectar el rendimiento.
        """
        if not mo.date_start:
            return
        wc_ids = mo.workorder_ids.mapped('workcenter_id').ids
        if not wc_ids:
            return
        # limit=50 por performance; OFs adicionales se detectarán en el próximo write o al cron
        subsequent = self.env['mrp.production'].search([
            ('id', '!=', mo.id),
            ('state', 'not in', ['done', 'cancel']),
            ('date_start', '>=', mo.date_start),
            ('workorder_ids.workcenter_id', 'in', wc_ids),
        ] + no_subcontract_domain(self.env), limit=50)
        if subsequent:
            subsequent.write({'x_reschedule_needed': True})

    # ── Contador de planes ───────────────────────────────────────────────────

    reschedule_plan_count = fields.Integer(
        compute='_compute_reschedule_plan_count',
        string='Planes',
    )

    def _compute_reschedule_plan_count(self):
        # PERF: optimización vs versión anterior que hacía N búsquedas por OF
        mo_ids = self.ids
        if not mo_ids:
            for mo in self:
                mo.reschedule_plan_count = 0
            return

        # Plans donde la OF es el pivot
        pivot_map = {}
        pivot_data = self.env['mrp.reschedule.plan'].search_read(
            [('production_id', 'in', mo_ids)],
            ['production_id', 'id'],
        )
        for d in pivot_data:
            mo_id = d['production_id'][0]
            pivot_map.setdefault(mo_id, set()).add(d['id'])

        # Plans donde la OF aparece como línea
        line_data = self.env['mrp.reschedule.plan.line'].search_read(
            [('production_id', 'in', mo_ids)],
            ['production_id', 'plan_id'],
        )
        line_map = {}
        for d in line_data:
            mo_id = d['production_id'][0]
            line_map.setdefault(mo_id, set()).add(d['plan_id'][0])

        for mo in self:
            all_ids = pivot_map.get(mo.id, set()) | line_map.get(mo.id, set())
            mo.reschedule_plan_count = len(all_ids)

    def action_view_reschedule_plans(self):
        self.ensure_one()
        pivot_ids = self.env['mrp.reschedule.plan'].search([
            ('production_id', '=', self.id),
        ]).ids
        line_ids = self.env['mrp.reschedule.plan.line'].search([
            ('production_id', '=', self.id),
        ]).mapped('plan_id').ids
        all_ids = list(set(pivot_ids + line_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Planes de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_ids)],
            'target': 'current',
        }

    # ── Alertas ──────────────────────────────────────────────────────────────

    alert_count = fields.Integer(
        compute='_compute_alert_count',
        string='Alertas',
    )

    def _compute_alert_count(self):
        # FIX [FASE-4]: read_group en lugar de N search_count individuales
        data = self.env['mrp.reschedule.alert'].read_group(
            [('production_id', 'in', self.ids), ('resolved', '=', False)],
            ['production_id'],
            ['production_id'],
        )
        counts = {d['production_id'][0]: d['production_id_count'] for d in data}
        for mo in self:
            mo.alert_count = counts.get(mo.id, 0)

    def action_view_alerts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'target': 'current',
        }

    # ── Acción del botón Reprogramar ─────────────────────────────────────────

    def action_open_reschedule_plan(self):
        """
        Crea un plan de reprogramación y lo abre. Funciona desde:
          - La vista lista (Acción → botón servidor).
          - El botón inteligente en el form (cuando x_reschedule_needed=True).
        """
        production_ids = self.env.context.get('active_ids', self.ids)
        if not production_ids:
            return
        pivot = self.browse(production_ids[0])

        pivot.write({'x_reschedule_needed': False})

        plan = self.env['mrp.reschedule.plan'].create({
            'production_id': pivot.id,
            'new_finish_date': pivot.date_finished or fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Plan de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }
