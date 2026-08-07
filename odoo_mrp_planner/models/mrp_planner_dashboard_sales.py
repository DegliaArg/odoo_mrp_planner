# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_sales.py
Modelo: extensión de mrp.planner.dashboard

Provee los métodos del dashboard orientados a ventas.

Responsabilidades:
- Calcular los datos del gráfico de ventas por producto (ventas confirmadas, RFQs
  o movimientos de stock de salida) con filtros de fecha, categoría y tipo de documento.
- Devolver las categorías de producto disponibles para los filtros del gráfico.
- Exponer la función auxiliar ``_parse_date`` usada también por el módulo de proveedores.

Relacionado con:
- mrp.planner.dashboard: clase base que este mixin extiende vía _inherit.
- sale.order.line / stock.move.line: fuentes de datos para el gráfico de ventas.
- mrp_planner_dashboard_supplier: extiende el dashboard con el análisis de proveedores.
"""
import calendar
import logging
from datetime import date, datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


def _parse_date(s, last_day=False):
    """Convierte 'YYYY-MM' o 'YYYY-MM-DD' a un objeto date.

    :param s: str — fecha en formato ``'YYYY-MM'`` o ``'YYYY-MM-DD'``.
    :param last_day: bool — si True, devuelve el último día del mes cuando no
        se especifica día explícito.
    :returns: date o None si el string no se puede parsear.
    """
    parts = s.split('-')
    y, m = int(parts[0]), int(parts[1])
    if len(parts) >= 3:
        return date(y, m, int(parts[2]))
    # Sin día explícito: primer o último día del mes según last_day
    return date(y, m, calendar.monthrange(y, m)[1] if last_day else 1)


class MrpPlannerDashboardSales(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    @api.model
    def get_sales_chart_data(self, date_from, date_to, top_n=20, sale_category=None, product_categ_id=None, sort_by='qty', doc_type='sales'):
        """
        Devuelve los datos del gráfico de ventas por plantilla de producto.

        Soporta tres fuentes de datos según ``doc_type``:

        * ``'sales'`` / ``'rfq'`` / ``'all'``: agrega líneas de órdenes de venta
          (sale.order.line) filtrando por los estados correspondientes.
        * cualquier otro valor (p. ej. ``'delivery'``): agrega movimientos de
          stock completados de tipo saliente (stock.move.line).

        Los resultados se agregan a nivel de plantilla de producto (no variante)
        para que un artículo con múltiples variantes aparezca como una sola barra.

        :param date_from: str — fecha de inicio en formato ``'YYYY-MM-DD'``.
        :param date_to: str — fecha de fin en formato ``'YYYY-MM-DD'``.
        :param top_n: int — máximo de registros a devolver; 0 ó None devuelve todos.
        :param sale_category: str — valor de ``x_sale_category`` para filtrar;
            ``'__none__'`` filtra productos sin categoría de venta asignada;
            ``None`` o ``''`` no aplica filtro.
        :param product_categ_id: int o str — ID de ``product.category`` para
            filtrar; ``None`` no aplica filtro.
        :param sort_by: str — campo de ordenamiento: ``'qty'`` (por defecto) o
            ``'amount'``.
        :param doc_type: str — tipo de documento origen: ``'sales'``, ``'rfq'``,
            ``'all'`` (combina ventas y RFQs) o cualquier otro valor para
            movimientos de stock de entrega.
        :returns: list[dict] — lista de dicts con claves ``tmpl_id``, ``name``,
            ``code``, ``sale_category``, ``qty`` y ``amount``, ordenada de mayor
            a menor según ``sort_by`` y recortada a ``top_n`` elementos.
            Devuelve ``[]`` cuando no hay datos; ante un error al leer
            sale.order.line lo registra en el log y re-lanza la excepción.
        """
        # Guard de grupo: lee ventas/movimientos con sudo(), no puede quedar abierto
        # a cualquier empleado con acceso al modelo transient.
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        tmpl_qty = {}
        allowed_ids = self._get_wh_domains().allowed_ids
        if allowed_ids is not None and not allowed_ids:
            return []
        # Filtro de empresa activa en ambas fuentes (multiempresa).
        company_id = self.env.company.id

        if doc_type in ('sales', 'rfq', 'all'):
            so_states = []
            if doc_type in ('sales', 'all'):
                # 'sale' = confirmado, 'done' = bloqueado/facturado
                so_states += ['sale', 'done']
            if doc_type in ('rfq', 'all'):
                # 'draft' = borrador, 'sent' = cotización enviada
                so_states += ['draft', 'sent']
            sol_domain = [
                ('order_id.state', 'in', so_states),
                ('order_id.date_order', '>=', date_from + ' 00:00:00'),
                ('order_id.date_order', '<=', date_to + ' 23:59:59'),
                ('product_id', '!=', False),
                ('product_id.sale_ok', '=', True),
                ('company_id', '=', company_id),
            ]
            if allowed_ids is not None:
                sol_domain.append(('order_id.warehouse_id', 'in', allowed_ids))
            if product_categ_id:
                sol_domain.append(('product_id.categ_id', '=', int(product_categ_id)))
            try:
                # sudo(): sale.order.line no es accesible para usuarios de producción/logística
                # read_group en lugar de search+loop para evitar N queries ORM
                groups = self.env['sale.order.line'].sudo().read_group(
                    sol_domain,
                    ['product_id', 'product_uom_qty:sum'],
                    ['product_id'],
                )
                # D-02: batch-load product→template mapping; evita un browse individual por fila de read_group
                sol_prod_ids = [g['product_id'][0] for g in groups if g['product_id']]
                sol_tmpl_map = {r['id']: r['product_tmpl_id'][0]
                                for r in self.env['product.product'].sudo().browse(sol_prod_ids)
                                .read(['id', 'product_tmpl_id'])} if sol_prod_ids else {}
                for g in groups:
                    if not g['product_id']:
                        continue
                    tid = sol_tmpl_map.get(g['product_id'][0])
                    if not tid:
                        continue
                    tmpl_qty[tid] = tmpl_qty.get(tid, 0.0) + (g['product_uom_qty'] or 0.0)
            except Exception as e:
                _logger.error('[SalesChart] Error al leer sale.order.line: %s', e, exc_info=True)
                raise
        else:
            domain = [
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'outgoing'),
                ('date', '>=', date_from + ' 00:00:00'),
                ('date', '<=', date_to + ' 23:59:59'),
                ('product_id', '!=', False),
                ('product_id.sale_ok', '=', True),
                ('company_id', '=', company_id),
            ]
            if allowed_ids is not None:
                domain.append(('picking_id.picking_type_id.warehouse_id', 'in', allowed_ids))
            if product_categ_id:
                domain.append(('product_id.categ_id', '=', int(product_categ_id)))
            # sudo(): stock.move.line no es accesible para usuarios de ventas/producción sin permisos de inventario
            groups = self.env['stock.move.line'].sudo().read_group(
                domain,
                ['product_id', 'quantity:sum'],
                ['product_id'],
            )
            # D-02: batch-load product→template mapping; evita un browse individual por fila de read_group
            sml_prod_ids = [g['product_id'][0] for g in groups if g['product_id']]
            sml_tmpl_map = {r['id']: r['product_tmpl_id'][0]
                            for r in self.env['product.product'].sudo().browse(sml_prod_ids)
                            .read(['id', 'product_tmpl_id'])} if sml_prod_ids else {}
            for g in groups:
                if not g['product_id']:
                    continue
                tid = sml_tmpl_map.get(g['product_id'][0])
                if not tid:
                    continue
                tmpl_qty[tid] = tmpl_qty.get(tid, 0.0) + (g['quantity'] or 0.0)

        if not tmpl_qty:
            return []

        if sale_category is not None and sale_category != '':
            # sudo(): product.template no es accesible para todos los grupos del módulo
            tmpls_all = self.env['product.template'].sudo().browse(list(tmpl_qty.keys()))
            tmpl_by_id_f = {t.id: t for t in tmpls_all}
            if sale_category == '__none__':
                keep = {tid for tid in tmpl_qty
                        if not (tmpl_by_id_f.get(tid) and tmpl_by_id_f[tid].x_sale_category)}
            else:
                keep = {tid for tid in tmpl_qty
                        if tmpl_by_id_f.get(tid) and tmpl_by_id_f[tid].x_sale_category == sale_category}
            tmpl_qty   = {tid: q for tid, q in tmpl_qty.items()   if tid in keep}
            if not tmpl_qty:
                return []

        all_ids    = list(tmpl_qty.keys())
        # sudo(): product.template no es accesible para todos los grupos del módulo
        templates  = self.env['product.template'].sudo().browse(all_ids)
        tmpl_by_id = {t.id: t for t in templates}

        rows = []
        for tid in all_ids:
            t = tmpl_by_id.get(tid)
            if not t:
                continue
            qty    = round(tmpl_qty[tid], 2)
            # PxQ = precio de lista del artículo × cantidad (demandada o entregada según la fuente).
            # Se usa list_price en ambas fuentes para que el importe sea comparable y no dependa
            # de descuentos/impuestos de la línea de venta.
            amount = round(qty * (t.list_price or 0.0), 2)
            rows.append({
                'tmpl_id':       tid,
                'name':          t.name,
                'code':          t.default_code or '',
                'sale_category': t.x_sale_category or '',
                'qty':           qty,
                'amount':        amount,
            })

        sort_key = 'amount' if sort_by == 'amount' else 'qty'
        result = sorted(rows, key=lambda r: r[sort_key], reverse=True)
        if top_n:
            result = result[:int(top_n)]
        return result

    @api.model
    def get_product_categories_for_chart(self):
        """Categorías de producto que tienen al menos un artículo vendible.

        Usa una sola read_group para obtener los categ_id activos, evitando el
        N+1 original (un search_count por categoría).
        """
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        # sudo(): product.template y product.category no son accesibles para usuarios de producción/ventas sin permisos de catálogo
        groups = self.env['product.template'].sudo().read_group(
            [('sale_ok', '=', True)],
            ['categ_id'],
            ['categ_id'],
        )
        active_categ_ids = {g['categ_id'][0] for g in groups if g.get('categ_id')}
        cats = self.env['product.category'].sudo().search([('id', 'in', list(active_categ_ids))])
        return sorted(
            [{'id': c.id, 'name': c.name} for c in cats],
            key=lambda x: x['name'],
        )

