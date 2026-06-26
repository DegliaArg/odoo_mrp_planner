from odoo import models, fields, api

SALE_CAT_SELECTION = [
    ('A', 'A — Alta rotación'),
    ('B', 'B'),
    ('C', 'C'),
    ('D', 'D'),
    ('E', 'E — Baja rotación'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_sale_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de venta',
        help='Clasificación A–E de rotación del artículo (A = mayor rotación). '
             'Se puede asignar manualmente o de forma automática desde Configuración del planificador.',
    )
