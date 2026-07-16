"""
Módulo: res_partner.py
Modelo: extensión de 'res.partner'

Extiende el modelo de contactos (clientes y proveedores) con campos de
clasificación ABC propios del planificador MRP y flags de visibilidad que
reflejan la configuración activa del módulo.

Responsabilidades:
- Agregar categorías A–E de proveedor y cliente al contacto.
- Exponer flags booleanos de visibilidad para que las vistas oculten o
  muestren esos campos según la configuración del planificador.

Relacionado con:
- mrp.reschedule.config: fuente de los flags enable_supplier_categories y
  enable_customer_categories que controlan la visibilidad de los campos.
- const.SALE_CAT_SELECTION: lista de valores A/B/C/D/E compartida con otros
  modelos del planificador.
"""
from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_supplier_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de proveedor',
        compute='_compute_supplier_category',
        inverse='_set_supplier_category',
        search='_search_supplier_category',
    )
    x_customer_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de cliente',
        compute='_compute_customer_category',
        inverse='_set_customer_category',
        search='_search_customer_category',
    )

    mrp_enable_supplier_cat = fields.Boolean(
        compute='_compute_mrp_cat_flags',
        help='Indica si la categoría de proveedor está habilitada en la '
             'configuración del planificador. Usado para ocultar/mostrar el '
             'campo x_supplier_category en las vistas.',
    )
    mrp_enable_customer_cat = fields.Boolean(
        compute='_compute_mrp_cat_flags',
        help='Indica si la categoría de cliente está habilitada en la '
             'configuración del planificador. Usado para ocultar/mostrar el '
             'campo x_customer_category en las vistas.',
    )

    @api.depends_context('company')
    def _compute_supplier_category(self):
        cats = self.env['mrp.partner.company.category'].search([
            ('partner_id', 'in', self.ids),
            ('company_id', '=', self.env.company.id),
        ])
        by_partner = {r.partner_id.id: r.supplier_category for r in cats}
        for rec in self:
            rec.x_supplier_category = by_partner.get(rec.id)

    def _set_supplier_category(self):
        Cat = self.env['mrp.partner.company.category']
        company_id = self.env.company.id
        existing = Cat.search([('partner_id', 'in', self.ids), ('company_id', '=', company_id)])
        by_partner = {r.partner_id.id: r for r in existing}
        to_create = []
        for rec in self:
            if rec.id in by_partner:
                by_partner[rec.id].supplier_category = rec.x_supplier_category
            else:
                to_create.append({
                    'partner_id': rec.id,
                    'company_id': company_id,
                    'supplier_category': rec.x_supplier_category,
                })
        if to_create:
            Cat.create(to_create)

    def _search_supplier_category(self, operator, value):
        cats = self.env['mrp.partner.company.category'].search([
            ('company_id', '=', self.env.company.id),
            ('supplier_category', operator, value),
        ])
        return [('id', 'in', cats.mapped('partner_id').ids)]

    @api.depends_context('company')
    def _compute_customer_category(self):
        cats = self.env['mrp.partner.company.category'].search([
            ('partner_id', 'in', self.ids),
            ('company_id', '=', self.env.company.id),
        ])
        by_partner = {r.partner_id.id: r.customer_category for r in cats}
        for rec in self:
            rec.x_customer_category = by_partner.get(rec.id)

    def _set_customer_category(self):
        Cat = self.env['mrp.partner.company.category']
        company_id = self.env.company.id
        existing = Cat.search([('partner_id', 'in', self.ids), ('company_id', '=', company_id)])
        by_partner = {r.partner_id.id: r for r in existing}
        to_create = []
        for rec in self:
            if rec.id in by_partner:
                by_partner[rec.id].customer_category = rec.x_customer_category
            else:
                to_create.append({
                    'partner_id': rec.id,
                    'company_id': company_id,
                    'customer_category': rec.x_customer_category,
                })
        if to_create:
            Cat.create(to_create)

    def _search_customer_category(self, operator, value):
        cats = self.env['mrp.partner.company.category'].search([
            ('company_id', '=', self.env.company.id),
            ('customer_category', operator, value),
        ])
        return [('id', 'in', cats.mapped('partner_id').ids)]

    # Usar @api.depends con la ruta cross-model para que Odoo invalide el cache
    # cuando cambia la configuración del planificador.
    @api.depends_context('company')
    def _compute_mrp_cat_flags(self):
        """
        Calcula mrp_enable_supplier_cat y mrp_enable_customer_cat para cada registro.

        Fórmula: lee los flags enable_supplier_categories / enable_customer_categories
        del único registro de mrp.reschedule.config existente; si no hay
        configuración creada aún, ambos flags quedan en False.
        Depende de: contexto de compañía (company); los cambios en
        mrp.reschedule.config invalidan el caché vía depends_context.
        """
        config = self.env['mrp.reschedule.config'].sudo().get_config()
        enable_sup  = config.enable_supplier_categories if config else False
        enable_cust = config.enable_customer_categories if config else False
        for rec in self:
            rec.mrp_enable_supplier_cat = enable_sup
            rec.mrp_enable_customer_cat = enable_cust
