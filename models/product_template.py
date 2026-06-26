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
    x_product_type_ids = fields.Many2many(
        'mrp.product.type',
        'mrp_product_type_product_rel',
        'product_tmpl_id',
        'type_id',
        string='Tipo de producto',
        help='Etiquetas de clasificación libre para categorizar el artículo '
             '(ej. Consumible, Materia prima, Producto terminado). '
             'Solo visible en artículos con venta habilitada.',
    )
