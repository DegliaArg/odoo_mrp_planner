from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    delivery_status = fields.Selection(
        selection=[('pending', 'Pendiente'), ('partial', 'Parcial'), ('full', 'Completo')],
        string='Estado de entrega',
        compute='_compute_line_delivery_status',
        store=True,
    )

    @api.depends('qty_delivered', 'product_uom_qty')
    def _compute_line_delivery_status(self):
        for line in self:
            if line.qty_delivered >= line.product_uom_qty:
                line.delivery_status = 'full'
            elif line.qty_delivered > 0:
                line.delivery_status = 'partial'
            else:
                line.delivery_status = 'pending'
