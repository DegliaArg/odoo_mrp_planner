"""
Módulo: stock_picking.py
Modelo: extensión de stock.picking

Intercepta escrituras en transferencias para mantener el sistema de alertas
de reprogramación MRP actualizado cuando cambia el estado o la fecha de una recepción.

Responsabilidades:
- Detectar cancelaciones, confirmaciones y cambios de fecha en recepciones entrantes.
- Resolver alertas de tipo 'receipt_delayed' cuando la situación se normaliza.
- Marcar las órdenes de fabricación (MOs) que consumen los productos afectados
  como necesitadas de reprogramación (x_reschedule_needed).

Relacionado con:
- mrp.reschedule.alert: gestiona las alertas de retraso que este módulo resuelve.
- mrp.production: las órdenes de fabricación que se marcan para reprogramar.
"""

import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def write(self, vals):
        """
        Extiende write para disparar la lógica de alertas MRP en recepciones.

        Al persistir cambios en transferencias, evalúa tres condiciones sobre los
        registros de tipo 'incoming' (recepciones de proveedor):

        1. Cancelación (state → 'cancel'): resuelve alertas 'receipt_delayed' activas
           y marca las MOs dependientes para reprogramación, porque el material ya
           no llegará por esta vía.
        2. Confirmación/recepción (state → 'done'): resuelve alertas 'receipt_delayed'
           porque el material ya ingresó al almacén.
        3. Cambio de fecha programada: si la nueva fecha es posterior a la anterior,
           la recepción se atrasó y las MOs dependientes deben reevaluarse; si la
           nueva fecha es futura respecto al momento actual, la alerta previa se resuelve.

        Los errores por recepción se loguean como warning sin interrumpir el write,
        para no bloquear operaciones de almacén por fallos en la lógica de planificación.

        :param vals: dict con los valores a escribir en los registros.
        :returns: resultado de super().write(vals) (bool True en Odoo ORM).
        """
        track_cancel = vals.get('state') == 'cancel'
        track_done   = vals.get('state') == 'done'
        track_date   = 'scheduled_date' in vals

        if track_date:
            old_dates = {p.id: p.scheduled_date for p in self}

        result = super().write(vals)

        alert_env = self.env['mrp.reschedule.alert']
        now = fields.Datetime.now()
        incoming = self.filtered(lambda p: p.picking_type_code == 'incoming')

        if incoming:
            for picking in incoming:
                try:
                    if track_cancel or track_done:
                        alert_env._resolve_for(('receipt_delayed',), picking_id=picking.id)
                        if track_cancel:
                            self._flag_mos_for_picking(picking)
                    elif track_date:
                        if picking.scheduled_date and picking.scheduled_date > now:
                            alert_env._resolve_for(('receipt_delayed',), picking_id=picking.id)
                        old_dt = old_dates.get(picking.id)
                        if old_dt and picking.scheduled_date and picking.scheduled_date > old_dt:
                            self._flag_mos_for_picking(picking)
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al procesar recepción %s: %s', picking.name, e
                    )

        return result

    def _flag_mos_for_picking(self, picking):
        """Marca x_reschedule_needed en MOs que consumen los productos de esta recepción."""
        product_ids = picking.move_ids.mapped('product_id').ids
        if not product_ids:
            return
        # FIX [FASE-3]: limit=50 dejaba OFs sin marcar; aumentado a 200 para reducir pérdidas
        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', 'in', product_ids),
        ], limit=200)
        if mos:
            mos.write({'x_reschedule_needed': True})
