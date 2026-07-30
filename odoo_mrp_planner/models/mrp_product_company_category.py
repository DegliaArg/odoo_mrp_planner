from odoo import models, fields
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class MrpProductCompanyCategory(models.Model):
    _name = 'mrp.product.company.category'
    _description = 'Categoría ABC de venta por empresa'
    _sql_constraints = [
        ('uniq_product_company', 'UNIQUE(product_tmpl_id, company_id)',
         'Ya existe una categoría para este artículo en esta empresa.'),
    ]

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade', index=True, string='Artículo',
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True, string='Empresa',
    )
    sale_category = fields.Selection(SALE_CAT_SELECTION, string='Categoría de venta')

    # La migración de datos desde product_template.x_sale_category fue
    # movida a migrations/18.0.46.0.0/pre-migrate.py para ejecutarse una
    # sola vez en el upgrade y no en cada reinicio.
