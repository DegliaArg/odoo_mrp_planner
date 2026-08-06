"""
Módulo: mrp_reschedule_config_inventory.py
Modelo: extensión de mrp.reschedule.config

Configuración del Panel de Inventario (pestaña Inventario de los Ajustes):
registro de disponibilidad (snapshot diario que alimenta la "Tasa de entrega
s/ disponible"), hora y retención de los snapshots, corte de antigüedad de
pendientes y redondeo de presentación. El circuito de despacho es una
extensión aparte en odoo_mrp_planner_dispatch.

Relacionado con:
- mrp.dispatch.stock.log / mrp.planner.kpi.monthly: snapshots y consolidado
  mensual que estos campos habilitan y parametrizan.
- ir_cron_dispatch_stock_snapshot: cron cuyo horario sincroniza
  _dispatch_sync_snapshot_cron (llamado desde write/create del singleton).
"""
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import models, fields


class MrpRescheduleConfigInventory(models.Model):
    _inherit = 'mrp.reschedule.config'

    dispatch_stock_log_enabled = fields.Boolean(
        string='Registrar disponibilidad de stock para entregas',
        default=False,
        help='Activa el snapshot diario de las salidas pendientes (cantidad pendiente '
             'vs. reservada). Alimenta la "Tasa de entrega s/ disponible" del Panel de '
             'Inventario: sin registro no hay tasa.')
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
        help='Las líneas pendientes cuya fecha programada (fecha del movimiento) es '
             'más vieja que esta cantidad de meses no cuentan en el Panel de '
             'Inventario ni en los snapshots de disponibilidad (0 = sin corte).')
    inventory_force_integer = fields.Boolean(
        string='Forzar cantidades enteras',
        default=False,
        help='Redondea a enteros las cantidades en piezas del Panel de Inventario '
             'y de Movimientos (las tasas y porcentajes conservan su decimal). '
             'Es independiente del "Forzar cantidades enteras" de la comparativa '
             'del forecast (Ajustes → Producción).')

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

    def _dispatch_sync_snapshot_cron(self):
        """Reprograma el próximo disparo del cron de snapshots a la hora configurada.

        El cron es global: se toma la hora del registro que se está guardando,
        interpretada en la zona horaria del usuario que guarda.
        """
        cron = self.env.ref('odoo_mrp_planner.ir_cron_dispatch_stock_snapshot',
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
