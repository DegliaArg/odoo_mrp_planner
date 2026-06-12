import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def write(self, vals):
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
        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', 'in', product_ids),
        ], limit=50)
        if mos:
            mos.write({'x_reschedule_needed': True})
