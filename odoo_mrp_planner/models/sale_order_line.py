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
    # Campos related almacenados para agrupar el drill "Ver" del análisis de
    # demanda insatisfecha por casa matriz (clientes con sucursales unificadas) y
    # por categoría de producto (familia), coincidiendo con las cards del panel.
    commercial_partner_id = fields.Many2one(
        'res.partner', string='Casa matriz',
        related='order_partner_id.commercial_partner_id', store=True, index=True,
    )
    product_categ_id = fields.Many2one(
        'product.category', string='Categoría de producto',
        related='product_id.categ_id', store=True, index=True,
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
            # Entregado topeado en 0: una devolución (qty_delivered negativo) no
            # aumenta el pendiente. Coherente con el cálculo del panel y el Forecast.
            delivered = max(0.0, line.qty_delivered or 0.0)
            unmet     = max(0.0, ordered - delivered)
            line.unmet_qty    = unmet
            line.unmet_amount = (line.price_subtotal or 0.0) * (unmet / ordered) if ordered else 0.0
