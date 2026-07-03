from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


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

    mrp_enable_sale_cat = fields.Boolean(compute='_compute_mrp_sale_cat_flag')

    @api.depends_context('company')
    def _compute_mrp_sale_cat_flag(self):
        config = self.env['mrp.reschedule.config'].sudo().search([], limit=1)
        enable = config.enable_sale_categories if config else False
        for rec in self:
            rec.mrp_enable_sale_cat = enable
