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

    def _auto_init(self):
        super()._auto_init()
        # Migrar valores existentes de las columnas globales res_partner.x_supplier_category
        # y x_customer_category (las columnas persisten en DB aunque el campo sea non-stored).
        self.env.cr.execute("SAVEPOINT migrate_partner_company_categories")
        try:
            self.env.cr.execute("""
                INSERT INTO mrp_partner_company_category
                    (partner_id, company_id, supplier_category, customer_category,
                     create_uid, create_date, write_uid, write_date)
                SELECT
                    rp.id,
                    (SELECT id FROM res_company ORDER BY id LIMIT 1),
                    rp.x_supplier_category,
                    rp.x_customer_category,
                    1, NOW() AT TIME ZONE 'UTC',
                    1, NOW() AT TIME ZONE 'UTC'
                FROM res_partner rp
                WHERE (rp.x_supplier_category IS NOT NULL OR rp.x_customer_category IS NOT NULL)
                  AND NOT EXISTS (
                      SELECT 1 FROM mrp_partner_company_category mpc
                       WHERE mpc.partner_id = rp.id
                         AND mpc.company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
                  )
            """)
            self.env.cr.execute("RELEASE SAVEPOINT migrate_partner_company_categories")
        except Exception:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT migrate_partner_company_categories")
