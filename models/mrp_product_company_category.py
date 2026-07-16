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

    def _auto_init(self):
        super()._auto_init()
        # Migrar valores existentes de la columna global product_template.x_sale_category
        # (la columna persiste en DB aunque el campo sea non-stored).
        self.env.cr.execute("SAVEPOINT migrate_product_company_categories")
        try:
            self.env.cr.execute("""
                INSERT INTO mrp_product_company_category
                    (product_tmpl_id, company_id, sale_category,
                     create_uid, create_date, write_uid, write_date)
                SELECT
                    pt.id,
                    (SELECT id FROM res_company ORDER BY id LIMIT 1),
                    pt.x_sale_category,
                    1, NOW() AT TIME ZONE 'UTC',
                    1, NOW() AT TIME ZONE 'UTC'
                FROM product_template pt
                WHERE pt.x_sale_category IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM mrp_product_company_category mpc
                       WHERE mpc.product_tmpl_id = pt.id
                         AND mpc.company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
                  )
            """)
            self.env.cr.execute("RELEASE SAVEPOINT migrate_product_company_categories")
        except Exception:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT migrate_product_company_categories")
