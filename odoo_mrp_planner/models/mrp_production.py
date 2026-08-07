"""
Módulo: mrp_production.py
Modelo: extensión de mrp.production

Extiende la orden de fabricación estándar de Odoo con los indicadores del
módulo MRP Planner. Las capacidades de reprogramación (planes, botones,
acciones en cascada) viven en odoo_mrp_planner_scheduling.

Responsabilidades:
- Vincular OFs hijo con su OF madre mediante campo tipado (x_parent_mo_id).
- Detectar cambios de estado (done/cancel) y marcar OFs subsecuentes con la
  bandera x_reschedule_needed (consumida por los KPIs y por scheduling).
- Generar y resolver alertas de atraso, cancelación y desvío de cantidad.
- Proveer el contador (smart button) de alertas activas.

Relacionado con:
- mrp.reschedule.alert: alertas activas (atraso, cancelación, desvío de cantidad).
- mrp_planner_helpers: provee no_subcontract_domain para filtrar OFs subcontratadas.
"""
from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import no_subcontract_domain

import logging
_logger = logging.getLogger(__name__)

# QTY_TOLERANCE eliminada: la tolerancia se lee de mrp.reschedule.config.qty_tolerance_pct.


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _where_calc(self, domain, active_test=True):
        """Normaliza el dominio a lista antes de pasarlo a ORM para evitar TypeError."""
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
        """
        Extiende write() para detectar cambios de estado y fecha, y actuar en consecuencia.

        Acciones por transición de estado:
        - Cualquier estado → done/cancel: marca OFs subsecuentes con x_reschedule_needed.
        - → cancel: resuelve alertas mo_delayed/qty_mismatch y crea alerta mo_cancelled.
        - → done: resuelve alerta mo_delayed y compara cantidad producida vs planificada;
                  si el desvío supera la tolerancia configurada en mrp.reschedule.config crea alerta qty_mismatch.
        - Cambio de date_finished a fecha futura: resuelve alerta mo_delayed (ya no hay atraso).

        Todos los bloques de alerta están envueltos en try/except para no interrumpir
        la escritura principal ante errores en el subsistema de alertas.

        :param vals: dict de campos a escribir.
        :returns: bool — resultado de super().write().
        """
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
                            cfg = self.env['mrp.reschedule.config'].get_config()
                            qty_tolerance = (cfg.qty_tolerance_pct or 5.0) / 100.0
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
                            if delta > qty_tolerance:
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
        Solo busca las más próximas (limit=50) para no afectar el rendimiento.
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

    # ── Alertas ──────────────────────────────────────────────────────────────

    alert_count = fields.Integer(
        compute='_compute_alert_count',
        string='Alertas',
        help='Número de alertas activas (no resueltas) asociadas a esta OF: '
             'atrasos, cancelaciones o desvíos de cantidad producida.',
    )

    def _compute_alert_count(self):
        """
        Calcula alert_count para cada registro.

        Fórmula: conteo de alertas activas (resolved=False) agrupadas por production_id.
        Depende de: mrp.reschedule.alert.production_id, mrp.reschedule.alert.resolved.
        """
        # read_group en lugar de N search_count individuales
        data = self.env['mrp.reschedule.alert'].read_group(
            [('production_id', 'in', self.ids), ('resolved', '=', False)],
            ['production_id'],
            ['production_id'],
        )
        counts = {d['production_id'][0]: d['production_id_count'] for d in data}
        for mo in self:
            mo.alert_count = counts.get(mo.id, 0)

    def action_view_alerts(self):
        """
        Abre la lista de alertas asociadas a esta OF (resueltas e irresueltas).

        :returns: dict — acción de ventana ir.actions.act_window filtrada por production_id.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'target': 'current',
        }
