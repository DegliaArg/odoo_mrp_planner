from odoo import models, fields
from odoo.addons.odoo_mrp_planner.models.product_template import SALE_CAT_SELECTION


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_supplier_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de proveedor',
        help='Clasificación A–E de calidad del proveedor.',
    )
    x_customer_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de cliente',
        help='Clasificación A–E de calidad del cliente.',
    )
