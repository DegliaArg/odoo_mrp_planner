import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        track_cancel = vals.get('state') == 'cancel'
        if track_cancel:
            pos_to_cancel = self.filtered(lambda p: p.state not in ('cancel', 'done'))

        if 'date_planned' in vals:
            old_dates = {po.id: po.date_planned for po in self}

        result = super().write(vals)

        if track_cancel:
            for po in pos_to_cancel:
                try:
                    alert_env = self.env['mrp.reschedule.alert']
                    product_ids = po.order_line.mapped('product_id').ids
                    impacted = self.env['mrp.production']
                    for pid in product_ids:
                        product = self.env['product.product'].browse(pid)
                        impacted |= alert_env._find_impact_mos(pid, product.qty_available)
                    alert_env._upsert_alert(
                        'po_cancelled', 'critical', 0,
                        _('OC %s cancelada') % po.name,
                        purchase_id=po.id,
                        impact_mo_ids=impacted.ids,
                    )
                    if impacted:
                        impacted.write({'x_reschedule_needed': True})
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al crear alerta de cancelación de OC %s: %s',
                        po.name, e,
                    )

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
