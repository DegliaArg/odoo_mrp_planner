"""
Módulo: product_template.py
Modelo: extensión de product.template

Extiende el modelo estándar de plantillas de producto de Odoo para incorporar
campos de clasificación usados por el planificador MRP.

Responsabilidades:
- Almacenar la categoría de venta ABC asignada al artículo.
- Relacionar el artículo con uno o varios tipos de producto del planificador.
- Exponer el flag de visibilidad que controla si la categoría de venta se
  muestra en la vista de formulario según la configuración activa.

Relacionado con:
- mrp.reschedule.config: fuente de la configuración que habilita/deshabilita la
  visualización de categorías de venta en el formulario del artículo.
- mrp.product.type: tabla maestra de tipos de producto usada en la relación M2M.
"""

from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_sale_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de venta',
        help='Clasificación A–E de rotación del artículo (A = mayor rotación). '
             'Se puede asignar manualmente o de forma automática desde Configuración del planificador.',
        compute='_compute_sale_category',
        inverse='_set_sale_category',
        search='_search_sale_category',
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

    mrp_enable_sale_cat = fields.Boolean(
        compute='_compute_mrp_sale_cat_flag',
        help='Indicador calculado: True si la configuración activa del planificador '
             'tiene habilitada la visualización de categorías de venta. '
             'Se usa en la vista para mostrar u ocultar el campo x_sale_category.',
    )

    @api.depends_context('company')
    def _compute_sale_category(self):
        cats = self.env['mrp.product.company.category'].search([
            ('product_tmpl_id', 'in', self.ids),
            ('company_id', '=', self.env.company.id),
        ])
        by_tmpl = {r.product_tmpl_id.id: r.sale_category for r in cats}
        for rec in self:
            rec.x_sale_category = by_tmpl.get(rec.id)

    def _set_sale_category(self):
        Cat = self.env['mrp.product.company.category']
        company_id = self.env.company.id
        existing = Cat.search([('product_tmpl_id', 'in', self.ids), ('company_id', '=', company_id)])
        by_tmpl = {r.product_tmpl_id.id: r for r in existing}
        to_create = []
        for rec in self:
            if rec.id in by_tmpl:
                by_tmpl[rec.id].sale_category = rec.x_sale_category
            else:
                to_create.append({
                    'product_tmpl_id': rec.id,
                    'company_id': company_id,
                    'sale_category': rec.x_sale_category,
                })
        if to_create:
            Cat.create(to_create)

    def _search_sale_category(self, operator, value):
        cats = self.env['mrp.product.company.category'].search([
            ('company_id', '=', self.env.company.id),
            ('sale_category', operator, value),
        ])
        return [('id', 'in', cats.mapped('product_tmpl_id').ids)]

    @api.depends_context('company')
    def _compute_mrp_sale_cat_flag(self):
        """
        Calcula mrp_enable_sale_cat para cada registro.

        Fórmula: lee el único registro de configuración del planificador y
        propaga su campo enable_sale_categories a todos los artículos del
        conjunto. Si no existe configuración, el flag se mantiene en False.
        Depende de: contexto de compañía (se recomputa al cambiar de compañía);
        mrp.reschedule.config.enable_sale_categories.
        """
        config = self.env['mrp.reschedule.config'].sudo().get_config()
        # Usa sudo() porque mrp.reschedule.config puede no ser accesible para
        # usuarios sin permisos de administración del planificador.
        enable = config.enable_sale_categories if config else False
        for rec in self:
            rec.mrp_enable_sale_cat = enable
