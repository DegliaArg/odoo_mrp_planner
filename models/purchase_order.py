import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        if 'date_planned' in vals:
            old_dates = {po.id: po.date_planned for po in self}

        result = super().write(vals)

        if 'date_planned' in vals:
            for po in self:
                old_dt = old_dates.get(po.id)
                if old_dt and po.date_planned and po.date_planned > old_dt:
                    try:
                        self._flag_mos_for_po(po)
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al marcar MOs de OC %s: %s', po.name, e
                        )
        return result

    def _flag_mos_for_po(self, po):
        """Marca x_reschedule_needed en MOs relacionadas a esta OC."""
        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            '|',
            ('purchase_order_id', '=', po.id),
            ('purchase_line_id.order_id', '=', po.id),
        ])
        if mos:
            mos.write({'x_reschedule_needed': True})
