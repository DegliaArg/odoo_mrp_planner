"""
Módulo: mrp_reschedule_config.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.reschedule.config

Agrega el interruptor de la validación de despacho (por empresa) y el
marcado retroactivo: al activar la función, las salidas ya validadas que
nunca entraron al circuito se consideran despachadas, para que la cola de
"Sin despachar" arranque vacía en lugar de arrastrar todo el histórico.

También los ajustes del registro de disponibilidad (snapshots diarios que
alimentan la "Tasa física s/ disponible" del Panel de Inventario): toggle,
hora del snapshot y retención de los registros crudos.
"""
import logging
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpRescheduleConfig(models.Model):
    _inherit = 'mrp.reschedule.config'

    dispatch_stock_log_enabled = fields.Boolean(
        string='Registrar disponibilidad de stock para despacho',
        default=False,
        help='Activa el snapshot diario de las salidas pendientes (cantidad pendiente '
             'vs. reservada). Alimenta la "Tasa física s/ disponible" del Panel de '
             'Inventario: sin registro no hay tasa. Requiere la validación de despacho activa.')
    dispatch_snapshot_hour = fields.Float(
        string='Hora del snapshot', default=20.0,
        help='Hora local (0-23.99) en que corre el snapshot diario de disponibilidad. '
             'El cron es único para toda la base: si hay varias empresas con el registro '
             'activo, rige la hora guardada más recientemente.')
    dispatch_log_retention_months = fields.Integer(
        string='Retención de snapshots (meses)', default=12,
        help='Los snapshots crudos más viejos que esta cantidad de meses se purgan, '
             'solo después de que su mes quede consolidado en el histórico mensual '
             '(que no se purga nunca).')
    dispatch_pending_cutoff_months = fields.Integer(
        string='Ignorar pendientes anteriores a (meses)', default=0,
        help='Las salidas pendientes con fecha programada más vieja que esta cantidad '
             'de meses no cuentan en el Panel de Inventario ni en los snapshots de '
             'disponibilidad (0 = sin corte).')

    enable_dispatch_validation = fields.Boolean(
        string='Habilitar validación de despacho',
        default=False,
        help='Activa el circuito de despacho en las órdenes de entrega de esta empresa: '
             'estado Sin despachar/Despachado, botón "Marcar despachado" (solo con el '
             'remito validado y para el grupo Inventario: validación de despacho) y '
             'filtros en la lista de salidas. Al activar, las salidas ya validadas que '
             'nunca entraron al circuito se marcan como despachadas.')

    def _dispatch_pending_cutoff_domain(self, field='scheduled_date'):
        """Dominio del corte de antigüedad de pendientes.

        Con "Ignorar pendientes anteriores a (meses)" > 0, las salidas cuya
        fecha programada es más vieja que N meses quedan fuera del Panel de
        Inventario (KPIs, tabla y drills) y de los snapshots de disponibilidad.
        Con 0 no hay corte y el dominio es vacío.

        :param field: campo de fecha sobre el que filtrar ('scheduled_date' en
                      stock.picking, 'picking_id.scheduled_date' en stock.move).
        :returns: list — dominio a sumar a la búsqueda ([] = sin filtro).
        """
        months = int(self and self[0].dispatch_pending_cutoff_months or 0)
        if months <= 0:
            return []
        cutoff = fields.Date.context_today(self) - relativedelta(months=months)
        # String (no datetime): el dominio también viaja al cliente en los
        # drills del panel y tiene que ser serializable a JSON.
        return [(field, '>=', fields.Datetime.to_string(
            datetime.combine(cutoff, datetime.min.time())))]

    def _dispatch_mark_legacy(self):
        """Marca como despachadas las salidas validadas que nunca entraron al circuito.

        Solo toca remitos con estado de despacho VACÍO (anteriores al módulo):
        lo que ya está "Sin despachar" conserva su estado real, así una
        desactivación temporal no borra la cola pendiente.
        """
        for rec in self:
            legacy = self.env['stock.picking'].sudo().search([
                ('company_id', '=', rec.company_id.id),
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
                ('x_dispatch_state', '=', False),
            ])
            if legacy:
                legacy.write({'x_dispatch_state': 'dispatched'})
                _logger.info('Despacho: %s salidas históricas de %s marcadas como despachadas.',
                             len(legacy), rec.company_id.name)

    def _dispatch_sync_snapshot_cron(self):
        """Reprograma el próximo disparo del cron de snapshots a la hora configurada.

        El cron es global: se toma la hora del registro que se está guardando,
        interpretada en la zona horaria del usuario que guarda.
        """
        cron = self.env.ref('odoo_mrp_planner_dispatch.ir_cron_dispatch_stock_snapshot',
                            raise_if_not_found=False)
        if not cron or not self:
            return
        hour = self[0].dispatch_snapshot_hour or 20.0
        hour = min(max(hour, 0.0), 23.99)
        try:
            tz = pytz.timezone(self.env.user.tz or 'UTC')
        except Exception:
            tz = pytz.utc
        now_local = datetime.now(pytz.utc).astimezone(tz)
        target = now_local.replace(hour=int(hour), minute=int(round(hour % 1 * 60)) % 60,
                                   second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
        cron.sudo().write({
            'nextcall': target.astimezone(pytz.utc).replace(tzinfo=None),
        })

    def write(self, vals):
        res = super().write(vals)
        if vals.get('enable_dispatch_validation'):
            self._dispatch_mark_legacy()
        if 'dispatch_snapshot_hour' in vals or vals.get('dispatch_stock_log_enabled'):
            self._dispatch_sync_snapshot_cron()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('enable_dispatch_validation')._dispatch_mark_legacy()
        if any(v.get('dispatch_stock_log_enabled') or v.get('dispatch_snapshot_hour')
               for v in vals_list):
            records._dispatch_sync_snapshot_cron()
        return records
