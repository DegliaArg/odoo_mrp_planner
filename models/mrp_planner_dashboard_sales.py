# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_sales.py
Modelo: extensión de mrp.planner.dashboard

Provee los métodos del dashboard orientados a ventas y análisis de proveedores.

Responsabilidades:
- Calcular los datos del gráfico de ventas por producto (ventas confirmadas, RFQs
  o movimientos de stock de salida) con filtros de fecha, categoría y tipo de documento.
- Devolver las categorías de producto disponibles para los filtros del gráfico.
- Generar el análisis de proveedores con KPIs de cumplimiento, lead time,
  variación de precio y volumen de compras.
- Listar las órdenes de compra individuales de un proveedor para el acordeón
  del widget de análisis.

Relacionado con:
- mrp.planner.dashboard: clase base que este mixin extiende vía _inherit.
- mrp.reschedule.config: lee la configuración de campos de fecha y umbrales
  de semáforo para el análisis de proveedores.
- sale.order.line / stock.move.line: fuentes de datos para el gráfico de ventas.
- purchase.order / stock.picking / account.move: fuentes de datos para el
  análisis de proveedores.
"""
import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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
            Devuelve ``[]`` ante cualquier error o cuando no hay datos.
        """
        tmpl_qty = {}
        tmpl_amount = {}

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
            ]
            if product_categ_id:
                sol_domain.append(('product_id.categ_id', '=', int(product_categ_id)))
            try:
                # read_group en lugar de search+loop para evitar N queries ORM
                groups = self.env['sale.order.line'].read_group(
                    sol_domain,
                    ['product_id', 'product_uom_qty:sum', 'price_subtotal:sum'],
                    ['product_id'],
                )
                for g in groups:
                    if not g['product_id']:
                        continue
                    pp = self.env['product.product'].browse(g['product_id'][0])
                    tid = pp.product_tmpl_id.id
                    tmpl_qty[tid] = tmpl_qty.get(tid, 0.0) + (g['product_uom_qty'] or 0.0)
                    tmpl_amount[tid] = tmpl_amount.get(tid, 0.0) + (g['price_subtotal'] or 0.0)
            except Exception:
                # El módulo sale puede no estar instalado; devolvemos lista vacía
                return []
        else:
            domain = [
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'outgoing'),
                ('date', '>=', date_from + ' 00:00:00'),
                ('date', '<=', date_to + ' 23:59:59'),
                ('product_id', '!=', False),
                ('product_id.sale_ok', '=', True),
            ]
            if product_categ_id:
                domain.append(('product_id.categ_id', '=', int(product_categ_id)))
            groups = self.env['stock.move.line'].read_group(
                domain,
                ['product_id', 'quantity:sum'],
                ['product_id'],
            )
            for g in groups:
                if not g['product_id']:
                    continue
                pp = self.env['product.product'].browse(g['product_id'][0])
                tid = pp.product_tmpl_id.id
                tmpl_qty[tid] = tmpl_qty.get(tid, 0.0) + (g['quantity'] or 0.0)

        if not tmpl_qty:
            return []

        if sale_category is not None and sale_category != '':
            tmpls_all = self.env['product.template'].browse(list(tmpl_qty.keys()))
            tmpl_by_id_f = {t.id: t for t in tmpls_all}
            if sale_category == '__none__':
                keep = {tid for tid in tmpl_qty
                        if not (tmpl_by_id_f.get(tid) and tmpl_by_id_f[tid].x_sale_category)}
            else:
                keep = {tid for tid in tmpl_qty
                        if tmpl_by_id_f.get(tid) and tmpl_by_id_f[tid].x_sale_category == sale_category}
            tmpl_qty   = {tid: q for tid, q in tmpl_qty.items()   if tid in keep}
            tmpl_amount = {tid: a for tid, a in tmpl_amount.items() if tid in keep}
            if not tmpl_qty:
                return []

        all_ids    = list(tmpl_qty.keys())
        templates  = self.env['product.template'].browse(all_ids)
        tmpl_by_id = {t.id: t for t in templates}

        rows = []
        for tid in all_ids:
            t = tmpl_by_id.get(tid)
            if not t:
                continue
            qty    = round(tmpl_qty[tid], 2)
            # Si no hay importe registrado (caso delivery), se estima con precio de lista
            amount = round(tmpl_amount[tid], 2) if tid in tmpl_amount else round(qty * (t.list_price or 0.0), 2)
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
        groups = self.env['product.template'].read_group(
            [('sale_ok', '=', True)],
            ['categ_id'],
            ['categ_id'],
        )
        active_categ_ids = {g['categ_id'][0] for g in groups if g.get('categ_id')}
        cats = self.env['product.category'].search([('id', 'in', list(active_categ_ids))])
        return sorted(
            [{'id': c.id, 'name': c.complete_name} for c in cats],
            key=lambda x: x['name'],
        )

    @api.model
    def get_supplier_analysis_data(self, period_from, period_to, search='', po_type='all'):
        """
        Devuelve el análisis de proveedores con KPIs de rendimiento y filas por proveedor.

        Calcula para cada proveedor que tiene órdenes de compra confirmadas en el
        período dado:

        * Conteo de órdenes y monto total.
        * Porcentaje de entregas a tiempo (on_time_pct) y días promedio de retraso.
        * Porcentaje de recepciones completas (sin backorder).
        * Lead time promedio real (desde aprobación de OC hasta recepción).
        * Variación de precio promedio respecto al costo estándar del producto.
        * Monto pendiente de factura (si el módulo account está disponible).

        Los KPIs globales se calculan como promedios ponderados / agregaciones
        sobre el total de pickings, no como promedios de promedios por proveedor.

        :param period_from: str — fecha de inicio, acepta ``'YYYY-MM'`` o
            ``'YYYY-MM-DD'``.
        :param period_to: str — fecha de fin, acepta ``'YYYY-MM'`` (se expande
            al último día del mes) o ``'YYYY-MM-DD'``.
        :param search: str — filtro de texto sobre el nombre del proveedor
            (búsqueda ``ilike``); ``''`` no aplica filtro.
        :param po_type: str — ``'all'`` incluye todas las OCs; ``'goods'`` solo
            OCs con al menos una línea de producto no-servicio; ``'services'``
            solo OCs sin líneas de bienes.
        :returns: dict con claves:

            * ``'rows'``: list[dict] — una fila por proveedor, ordenada de mayor
              a menor por ``total_amount``.
            * ``'kpis'``: dict — métricas agregadas del período.
            * ``'has_invoices'``: bool — indica si el módulo account está
              disponible y se pudieron calcular los pendientes.
            * ``'config'``: dict — umbrales de semáforo verde/amarillo leídos
              desde ``mrp.reschedule.config``.
            * ``'show_supplier_cat'``: bool — si se debe mostrar la columna
              de categoría de proveedor personalizada.

            Ante error de parseo de fechas devuelve
            ``{'rows': [], 'kpis': {…vacío}, 'has_invoices': False}``.
        """
        import calendar as _cal
        from datetime import date as _date

        def _parse_date(s, last_day=False):
            """Convierte 'YYYY-MM' o 'YYYY-MM-DD' a un objeto date."""
            parts = s.split('-')
            y, m = int(parts[0]), int(parts[1])
            if len(parts) >= 3:
                return _date(y, m, int(parts[2]))
            # Sin día explícito: primer o último día del mes según last_day
            return _date(y, m, _cal.monthrange(y, m)[1] if last_day else 1)

        try:
            d_from = _parse_date(period_from)
            d_to   = _parse_date(period_to, last_day=True)
        except Exception:
            return {'rows': [], 'kpis': {}, 'has_invoices': False}

        dt_from = fields.Datetime.to_string(datetime.combine(d_from, datetime.min.time()))
        dt_to   = fields.Datetime.to_string(datetime.combine(d_to,   datetime.max.time()))

        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        # date_field determina qué campo de fecha usa el filtro principal de OCs;
        # 'date_approve' es el campo estándar de Odoo para la fecha de confirmación.
        date_field = (cfg and cfg.supplier_analysis_date_field) or 'date_approve'
        # Nota: reemplazar todas las referencias posteriores a cfg_sa por cfg,
        # y eliminar la segunda búsqueda en línea 2510 (cfg = self.env[...].search(...)).

        po_domain = [
            ('state', 'in', ['purchase', 'done']),
            (date_field, '>=', dt_from),
            (date_field, '<=', dt_to),
            ('company_id', '=', self.env.company.id),
        ]
        if search:
            po_domain.append(('partner_id.name', 'ilike', search))

        # Pre-clasificar OCs por tipo usando SQL antes del search principal.
        # Hacerlo en una sola read_group evita cargar todos los registros en memoria.
        if po_type in ('goods', 'services'):
            # 1 query: obtener IDs de OCs con al menos una línea de producto no-servicio
            goods_line_groups = self.env['purchase.order.line'].read_group(
                [('order_id.state', 'in', ['purchase', 'done']),
                 ('product_id.type', '!=', 'service'),
                 ('product_id', '!=', False)],
                ['order_id'],
                ['order_id'],
            )
            goods_po_ids = {g['order_id'][0] for g in goods_line_groups if g['order_id']}
            if po_type == 'goods':
                po_domain.append(('id', 'in', list(goods_po_ids)))
            else:  # services: OCs sin ninguna línea de bien
                po_domain.append(('id', 'not in', list(goods_po_ids)))

        pos = self.env['purchase.order'].search(po_domain)

        # KPIs vacíos devueltos cuando no hay OCs en el período, para que el
        # frontend no deba manejar la ausencia de claves.
        _empty_kpis = {
            'supplier_count': 0, 'total_amount': 0, 'total_orders': 0,
            'avg_on_time_pct': None, 'avg_lead_time_days': None, 'avg_price_var_pct': None,
        }
        if not pos:
            return {'rows': [], 'kpis': _empty_kpis, 'has_invoices': False}

        # Agregación por proveedor usando los IDs ya filtrados para no duplicar
        # los predicados de fecha/empresa en una segunda query independiente.
        po_groups = self.env['purchase.order'].read_group(
            [('id', 'in', pos.ids)], ['partner_id', 'amount_total:sum'], ['partner_id'],
        )

        partner_data = {}
        for g in po_groups:
            if not g['partner_id']:
                continue
            pid = g['partner_id'][0]
            partner_data[pid] = {
                'partner_id':   pid,
                'partner_name': g['partner_id'][1],
                'order_count':  g['partner_id_count'],
                'total_amount': round(g['amount_total'] or 0.0, 2),
                'products':     set(),
                'pick_count':   0, 'on_time_count': 0,
                'delay_sum':    0.0, 'delay_count': 0,
                'complete_count': 0,
                'lt_sum':       0.0, 'lt_count': 0,
                'pvar_sum':     0.0, 'pvar_count': 0,
                'pending_inv':  0.0,
            }

        # Prefetch partner_id para garantizar que el dict comprehension no genere lazy-loads
        pos.mapped('partner_id')
        # Índice po_id → (partner_id, date_approve) para lookups O(1) en los loops siguientes
        po_map = {po.id: (po.partner_id.id, po.date_approve) for po in pos}

        # Líneas de OC: traemos solo los campos necesarios para calcular
        # productos distintos por proveedor y variación de precio vs. costo estándar.
        po_line_data = self.env['purchase.order.line'].search_read(
            [('order_id', 'in', pos.ids), ('product_id', '!=', False)],
            ['order_id', 'product_id', 'price_unit'],
        )
        all_prod_ids = list({ln['product_id'][0] for ln in po_line_data if ln['product_id']})
        if all_prod_ids:
            # Una sola query para obtener los costos estándar de todos los productos
            std_map = {r['id']: r['standard_price']
                       for r in self.env['product.product'].search_read(
                           [('id', 'in', all_prod_ids)], ['id', 'standard_price'])}
        else:
            std_map = {}

        for ln in po_line_data:
            po_id    = ln['order_id'][0] if isinstance(ln['order_id'], (list, tuple)) else ln['order_id']
            prod_id  = ln['product_id'][0] if isinstance(ln['product_id'], (list, tuple)) else ln['product_id']
            partner_id = po_map.get(po_id, (None,))[0]
            if partner_id not in partner_data:
                continue
            pd = partner_data[partner_id]
            pd['products'].add(prod_id)
            std = std_map.get(prod_id, 0.0)
            if std > 0 and ln['price_unit'] > 0:
                pd['pvar_sum']   += (ln['price_unit'] - std) / std * 100
                pd['pvar_count'] += 1

        # Solo recepciones completadas de tipo entrante para calcular cumplimiento
        pickings = self.env['stock.picking'].search([
            ('purchase_id', 'in', pos.ids),
            ('state', '=', 'done'),
            ('picking_type_code', '=', 'incoming'),
        ])
        # Pickings con backorder = fueron recibidos parcialmente en ese picking;
        # se excluyen del conteo de 'complete_count' para el KPI de completitud.
        partial_ids = set(
            self.env['stock.picking'].search(
                [('backorder_id', 'in', pickings.ids)]
            ).mapped('backorder_id').ids
        )

        pickings.mapped('purchase_id')  # prefetch en 1 query
        for picking in pickings:
            po_id = picking.purchase_id.id if picking.purchase_id else None
            if not po_id or po_id not in po_map:
                continue
            partner_id, date_approve = po_map[po_id]
            if partner_id not in partner_data:
                continue
            pd = partner_data[partner_id]
            pd['pick_count'] += 1

            sched = picking.scheduled_date
            done  = picking.date_done
            if sched and done:
                delay = (done - sched).days
                # delay <= 0 significa entrega en fecha o antes: cuenta como a tiempo
                if delay <= 0:
                    pd['on_time_count'] += 1
                else:
                    pd['delay_sum']   += delay
                    pd['delay_count'] += 1

            if picking.id not in partial_ids:
                pd['complete_count'] += 1

            if date_approve and done:
                lt = (done - date_approve).days
                if lt >= 0:
                    pd['lt_sum']   += lt
                    pd['lt_count'] += 1

        # Facturas pendientes: se intenta calcular; si account no está instalado
        # o falla, has_invoices queda en False y la columna no se muestra en el frontend.
        has_invoices = False
        try:
            inv_groups = self.env['account.move'].read_group(
                [('move_type', '=', 'in_invoice'),
                 ('partner_id', 'in', list(partner_data.keys())),
                 ('payment_state', 'not in', ['paid', 'reversed']),
                 ('state', '=', 'posted'),
                 ('company_id', '=', self.env.company.id)],
                ['partner_id', 'amount_residual:sum'],
                ['partner_id'],
            )
            for g in inv_groups:
                if g['partner_id'] and g['partner_id'][0] in partner_data:
                    partner_data[g['partner_id'][0]]['pending_inv'] = round(g['amount_residual'] or 0.0, 2)
            has_invoices = True
        except Exception:
            pass

        # Construir filas serializables (sin sets ni objetos ORM) para JSON
        rows = []
        for pid, d in partner_data.items():
            pc = d['pick_count']
            rows.append({
                'partner_id':        pid,
                'partner_name':      d['partner_name'],
                'order_count':       d['order_count'],
                'total_amount':      d['total_amount'],
                'distinct_products': len(d['products']),
                'pick_count':        pc,
                'on_time_pct':   round(d['on_time_count'] / pc * 100, 1) if pc > 0 else None,
                'avg_delay_days': round(d['delay_sum'] / d['delay_count'], 1) if d['delay_count'] > 0 else None,
                'complete_pct':  round(d['complete_count'] / pc * 100, 1) if pc > 0 else None,
                'avg_lead_time': round(d['lt_sum'] / d['lt_count'], 1) if d['lt_count'] > 0 else None,
                'avg_price_var_pct': round(d['pvar_sum'] / d['pvar_count'], 1) if d['pvar_count'] > 0 else None,
                'pending_inv':   d['pending_inv'] if has_invoices else None,
            })

        rows.sort(key=lambda r: r['total_amount'], reverse=True)

        def _wavg(rows, key):
            """Promedio simple de los valores no-nulos de ``key`` en ``rows``."""
            vals = [r[key] for r in rows if r[key] is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        total_pickings = sum(r['pick_count'] for r in rows)
        # on_time_abs se suma desde partner_data (antes de round) para mayor precisión
        on_time_abs    = sum(d['on_time_count'] for d in partner_data.values())
        kpis = {
            'supplier_count':     len(rows),
            'total_amount':       round(sum(r['total_amount'] for r in rows), 2),
            'total_orders':       sum(r['order_count'] for r in rows),
            'avg_on_time_pct':    round(on_time_abs / total_pickings * 100, 1) if total_pickings > 0 else None,
            'avg_lead_time_days': _wavg(rows, 'avg_lead_time'),
            'avg_price_var_pct':  _wavg(rows, 'avg_price_var_pct'),
        }

        # La columna de categoría de proveedor se muestra solo si está habilitada
        # en la config para no exponer campos personalizados que podrían no existir.
        show_supplier_cat = bool(cfg and cfg.enable_supplier_categories)
        if show_supplier_cat:
            cat_map = {r['id']: r['x_supplier_category'] or ''
                       for r in self.env['res.partner'].search_read(
                           [('id', 'in', list(partner_data.keys()))],
                           ['id', 'x_supplier_category']
                       )}
            for row in rows:
                row['supplier_cat'] = cat_map.get(row['partner_id'], '')

        # Valores por defecto del semáforo cuando no hay config:
        # on_time verde ≥ 90 %, amarillo ≥ 70 %; delay verde ≤ 1 día, amarillo ≤ 3 días;
        # completitud verde ≥ 95 %, amarillo ≥ 80 %; variación precio verde ≤ 3 %, amarillo ≤ 10 %.
        sup_config = {
            'sup_on_time_green':   cfg.sup_on_time_green_pct   if cfg else 90,
            'sup_on_time_yellow':  cfg.sup_on_time_yellow_pct  if cfg else 70,
            'sup_delay_green':     cfg.sup_delay_green_days    if cfg else 1,
            'sup_delay_yellow':    cfg.sup_delay_yellow_days   if cfg else 3,
            'sup_complete_green':  cfg.sup_complete_green_pct  if cfg else 95,
            'sup_complete_yellow': cfg.sup_complete_yellow_pct if cfg else 80,
            'sup_price_var_green':  cfg.sup_price_var_green_pct  if cfg else 3.0,
            'sup_price_var_yellow': cfg.sup_price_var_yellow_pct if cfg else 10.0,
        }

        return {
            'rows': rows, 'kpis': kpis, 'has_invoices': has_invoices,
            'config': sup_config, 'show_supplier_cat': show_supplier_cat,
        }

    @api.model
    def get_supplier_pos_for_analysis(self, partner_id, period_from, period_to):
        """
        Devuelve las órdenes de compra de un proveedor para el acordeón del widget de análisis.

        Se usa cuando el usuario expande la fila de un proveedor en el widget de
        análisis de proveedores para ver el detalle de cada orden individualmente.

        El estado de recepción (``receipt_status``) se calcula evaluando los
        pickings de entrada no cancelados asociados a cada OC:

        * ``'none'``    — sin pickings asociados.
        * ``'full'``    — todos los pickings en estado ``done``.
        * ``'partial'`` — algunos pickings en ``done``, otros pendientes.
        * ``'pending'`` — pickings existentes pero ninguno completado.

        :param partner_id: int — ID del ``res.partner`` proveedor.
        :param period_from: str — fecha de inicio en formato ``'YYYY-MM'`` o
            ``'YYYY-MM-DD'``.
        :param period_to: str — fecha de fin en formato ``'YYYY-MM'`` o
            ``'YYYY-MM-DD'`` (el mes se expande al último día).
        :returns: list[dict] — lista de dicts con claves ``po_id``, ``name``,
            ``date_approve``, ``date_planned``, ``amount_total``,
            ``product_count`` y ``receipt_status``, ordenada por fecha de orden
            descendente. Devuelve ``[]`` si las fechas no se pueden parsear.
        """
        import calendar as _cal
        from datetime import date as _date
        def _parse_date(s, last_day=False):
            """Convierte 'YYYY-MM' o 'YYYY-MM-DD' a un objeto date."""
            parts = s.split('-')
            y, m = int(parts[0]), int(parts[1])
            if len(parts) >= 3:
                return _date(y, m, int(parts[2]))
            # Sin día explícito: primer o último día del mes según last_day
            return _date(y, m, _cal.monthrange(y, m)[1] if last_day else 1)

        try:
            d_from = _parse_date(period_from)
            d_to   = _parse_date(period_to, last_day=True)
        except Exception:
            return []

        dt_from = fields.Datetime.to_string(datetime.combine(d_from, datetime.min.time()))
        dt_to   = fields.Datetime.to_string(datetime.combine(d_to,   datetime.max.time()))

        pos = self.env['purchase.order'].search([
            ('partner_id', '=', partner_id),
            ('state', 'in', ['purchase', 'done']),
            ('date_order', '>=', dt_from),
            ('date_order', '<=', dt_to),
            ('company_id', '=', self.env.company.id),
        ], order='date_order desc')

        rows = []
        for po in pos:
            pickings = po.picking_ids.filtered(
                lambda p: p.state != 'cancel' and p.picking_type_code == 'incoming'
            )
            done_picks = pickings.filtered(lambda p: p.state == 'done')
            if not pickings:
                receipt_status = 'none'
            elif len(done_picks) == len(pickings):
                receipt_status = 'full'
            elif done_picks:
                receipt_status = 'partial'
            else:
                receipt_status = 'pending'

            rows.append({
                'po_id':          po.id,
                'name':           po.name,
                'date_approve':   po.date_approve.strftime('%d/%m/%Y') if po.date_approve else '',
                'date_planned':   po.date_planned.strftime('%d/%m/%Y') if po.date_planned else '',
                'amount_total':   round(po.amount_total, 2),
                'product_count':  len(po.order_line.mapped('product_id')),
                'receipt_status': receipt_status,
            })
        return rows
