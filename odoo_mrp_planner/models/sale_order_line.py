from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    delivery_status = fields.Selection(
        selection=[('pending', 'Pendiente'), ('partial', 'Parcial'), ('full', 'Completo')],
        string='Estado de entrega',
        compute='_compute_line_delivery_status',
        store=True,
    )

    unmet_qty = fields.Float(
        string='Pendiente',
        compute='_compute_demand_split',
        store=True,
        digits='Product Unit of Measure',
        help='Cantidad pedida aún no entregada: pedido − entregado (mínimo 0). '
             'Usada por el drill "Ver" del análisis de demanda insatisfecha.',
    )
    fulfilled_qty = fields.Float(
        string='Entregado',
        compute='_compute_demand_split',
        store=True,
        digits='Product Unit of Measure',
        help='Entregado hacia lo pedido: mín(pedido, entregado). No cuenta las '
             'sobre-entregas. Es el "Cumplimiento de demanda" que cierra con el '
             'pedido y el pendiente en el análisis de demanda insatisfecha.',
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

    @api.depends('qty_delivered', 'product_uom_qty')
    def _compute_demand_split(self):
        for line in self:
            ordered   = line.product_uom_qty or 0.0
            delivered = line.qty_delivered or 0.0
            line.unmet_qty     = max(0.0, ordered - delivered)
            line.fulfilled_qty = min(ordered, delivered)
