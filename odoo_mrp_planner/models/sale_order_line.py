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
    unmet_amount = fields.Monetary(
        string='Valorización del pendiente',
        compute='_compute_demand_split',
        store=True,
        currency_field='currency_id',
        help='Valor real del pendiente de la línea: subtotal × (pendiente ÷ pedido). '
             'Valorización "real" (con descuentos) del backlog; usada por el drill '
             '"Ver" de la card de Valorización del pendiente.',
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

    @api.depends('qty_delivered', 'product_uom_qty', 'price_subtotal')
    def _compute_demand_split(self):
        for line in self:
            ordered   = line.product_uom_qty or 0.0
            delivered = line.qty_delivered or 0.0
            unmet     = max(0.0, ordered - delivered)
            line.unmet_qty    = unmet
            line.unmet_amount = (line.price_subtotal or 0.0) * (unmet / ordered) if ordered else 0.0
