from odoo import models, fields
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class MrpPartnerCompanyCategory(models.Model):
    _name = 'mrp.partner.company.category'
    _description = 'Categoría ABC de proveedor/cliente por empresa'
    _sql_constraints = [
        ('uniq_partner_company', 'UNIQUE(partner_id, company_id)',
         'Ya existe una categoría para este contacto en esta empresa.'),
    ]

    partner_id = fields.Many2one(
        'res.partner', required=True, ondelete='cascade', index=True, string='Contacto',
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True, string='Empresa',
    )
    supplier_category = fields.Selection(SALE_CAT_SELECTION, string='Categoría de proveedor')
    customer_category = fields.Selection(SALE_CAT_SELECTION, string='Categoría de cliente')

    # La migración de datos desde res_partner.x_supplier_category /
    # x_customer_category fue movida a migrations/18.0.46.0.0/pre-migrate.py
    # para ejecutarse una sola vez en el upgrade y no en cada reinicio.
