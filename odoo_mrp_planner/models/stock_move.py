"""
Módulo: stock_move.py
Modelo: extensión de stock.move

Agrega dos columnas de categoría usadas por el drill "Disponible no hecho —
líneas" del Panel de Inventario:
- x_product_categ_id: la categoría de producto estándar (product_id.categ_id).
- x_sale_category: la categoría de venta ABC del módulo (vive por empresa en
  mrp.product.company.category, vía product.template.x_sale_category).

NO se almacenan (stock_move es una tabla enorme): se calculan por lectura para
mostrarlas y se resuelven por SQL (_field_to_sql) para poder FILTRAR, AGRUPAR y
ORDENAR sin agregar columnas nuevas. Mismo patrón que
product.template._field_to_sql para x_sale_category.
"""
from odoo import models, fields, api
from odoo.tools import SQL
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_product_categ_id = fields.Many2one(
        'product.category', string='Categoría de producto',
        compute='_compute_x_product_categ_id', search='_search_x_product_categ_id',
        help='Categoría de producto estándar del artículo del movimiento.')
    x_sale_category = fields.Selection(
        SALE_CAT_SELECTION, string='Categoría de venta',
        compute='_compute_x_sale_category', search='_search_x_sale_category',
        help='Categoría de venta ABC del artículo (por empresa).')

    @api.depends('product_id')
    def _compute_x_product_categ_id(self):
        for move in self:
            move.x_product_categ_id = move.product_id.categ_id

    def _search_x_product_categ_id(self, operator, value):
        return [('product_id.categ_id', operator, value)]

    @api.depends('product_id')
    def _compute_x_sale_category(self):
        # x_sale_category es no-almacenado y por empresa (mrp.product.company.
        # category): se lee de la plantilla con la empresa del contexto.
        for move in self:
            move.x_sale_category = move.product_id.product_tmpl_id.x_sale_category

    def _search_x_sale_category(self, operator, value):
        return [('product_id.product_tmpl_id.x_sale_category', operator, value)]

    def _field_to_sql(self, alias, fname, query=None, flush=True):
        """Expresión SQL de las categorías para filtrar/agrupar/ordenar sin
        almacenarlas. Resuelve las categorías vía JOIN al producto/plantilla
        (y, para la de venta, a la tabla por empresa), igual que
        product.template._field_to_sql."""
        if fname == 'x_product_categ_id':
            pp = query.make_alias(alias, 'x_pcateg_pp')
            query.add_join('LEFT JOIN', pp, 'product_product', SQL(
                "%s = %s", SQL.identifier(pp, 'id'),
                SQL.identifier(alias, 'product_id')))
            pt = query.make_alias(pp, 'x_pcateg_pt')
            query.add_join('LEFT JOIN', pt, 'product_template', SQL(
                "%s = %s", SQL.identifier(pt, 'id'),
                SQL.identifier(pp, 'product_tmpl_id')))
            return SQL.identifier(pt, 'categ_id')
        if fname == 'x_sale_category':
            if flush:
                self.env['mrp.product.company.category'].flush_model(
                    ['product_tmpl_id', 'company_id', 'sale_category'])
            pp = query.make_alias(alias, 'x_scat_pp')
            query.add_join('LEFT JOIN', pp, 'product_product', SQL(
                "%s = %s", SQL.identifier(pp, 'id'),
                SQL.identifier(alias, 'product_id')))
            cat = query.make_alias(pp, 'x_scat_cat')
            query.add_join('LEFT JOIN', cat, 'mrp_product_company_category', SQL(
                "%s = %s AND %s = %s",
                SQL.identifier(cat, 'product_tmpl_id'),
                SQL.identifier(pp, 'product_tmpl_id'),
                SQL.identifier(cat, 'company_id'), self.env.company.id))
            return SQL.identifier(cat, 'sale_category')
        return super()._field_to_sql(alias, fname, query, flush)
