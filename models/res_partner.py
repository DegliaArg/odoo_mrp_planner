from odoo import models, fields, api
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

    mrp_enable_supplier_cat = fields.Boolean(compute='_compute_mrp_cat_flags')
    mrp_enable_customer_cat = fields.Boolean(compute='_compute_mrp_cat_flags')

    @api.depends()
    def _compute_mrp_cat_flags(self):
        config = self.env['mrp.reschedule.config'].sudo().search([], limit=1)
        enable_sup  = config.enable_supplier_categories if config else False
        enable_cust = config.enable_customer_categories if config else False
        for rec in self:
            rec.mrp_enable_supplier_cat = enable_sup
            rec.mrp_enable_customer_cat = enable_cust
