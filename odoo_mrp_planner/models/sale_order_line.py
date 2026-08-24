from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Campo stored para poder agrupar líneas por estado de entrega del pedido
    # en el drilldown de cumplimiento del análisis de clientes.
    # delivery_status vive en sale.order (módulo sale_stock).
    delivery_status = fields.Selection(
        related='order_id.delivery_status',
        string='Estado de entrega',
        store=True,
    )
