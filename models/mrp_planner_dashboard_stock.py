# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_stock.py
Modelo: extensión de mrp.planner.dashboard

Extiende el dashboard del planificador MRP con el widget de quiebres de stock.

Responsabilidades:
- Calcular el stock actual de productos vendibles en una o varias ubicaciones internas.
- Comparar ese stock contra el punto de reorden mínimo con ruta Fabricación.
- Clasificar cada producto como: en quiebre, OK o sin mínimo configurado.
- Exponer OFs activas por producto para el panel desplegable del widget.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende vía _inherit.
- stock.warehouse.orderpoint: fuente del punto de reorden mínimo (product_min_qty).
- stock.quant: fuente del stock físico en las ubicaciones seleccionadas.
- mrp.production: OFs activas mostradas en el acordeón por producto.
- mrp_reschedule.stock_location_id: parámetro de sistema con la ubicación por defecto.
"""
import logging
from datetime import date as _date, datetime as _datetime, timedelta

from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardStock(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Widget quiebres de stock ─────────────────────────────────────────────

    @api.model
    def get_stock_break_data(self, filter_type='all', sort_field=None, sort_dir='asc', page=1, page_size=20, search='', location_ids=None):
        """
        Devuelve KPIs y listado paginado de quiebres de stock para el widget del dashboard.

        Consulta productos con sale_ok=True activos (tipo 'consu'), compara su stock en
        las ubicaciones indicadas contra el punto de reorden mínimo con ruta Fabricación,
        y clasifica cada producto como: en quiebre (qty < min_qty), OK, o sin mínimo.

        La carga de display_name se difiere al momento de la paginación para evitar
        traer nombres de todos los productos cuando la lista es larga (optimización SB-02b).

        :param filter_type: str — filtro a aplicar: 'all', 'broken', 'ok' o 'no_min'.
        :param sort_field: str o None — campo de orden: 'name', 'qty', 'min_qty',
            'qty_forecast', 'status' o None (orden por defecto: quiebres primero).
        :param sort_dir: str — dirección de orden: 'asc' o 'desc'.
        :param page: int — número de página (base 1).
        :param page_size: int — cantidad de registros por página.
        :param search: str — texto para filtrar por nombre o referencia interna del producto.
        :param location_ids: list[int] | int | None — IDs de stock.location a considerar.
            Si es None o lista vacía, se usa el parámetro de sistema
            'mrp_reschedule.stock_location_id'.
        :returns: dict con las claves:
            - 'error': None o 'no_location' si no se pudo resolver ninguna ubicación.
            - 'kpis': dict con 'total', 'broken', 'ok', 'no_min'.
            - 'products': list[dict] con los registros de la página actual.
            - 'location_name': str con el nombre completo de la/s ubicación/es.
            - 'location_ids': list[int] con los IDs de ubicación resueltos.
            - 'location_id': int | False — ID de la primera ubicación (compatibilidad).
            - 'total_filtered': int — total de registros tras aplicar el filtro activo.
        """
        # Estructura vacía reutilizada en los retornos anticipados cuando no hay datos
        _empty_kpis = {'total': 0, 'broken': 0, 'ok': 0, 'no_min': 0}

        # Normalizar location_ids a lista de enteros
        if location_ids and isinstance(location_ids, int):
            location_ids = [location_ids]
        elif not location_ids:
            location_ids = []

        if location_ids:
            locations = self.env['stock.location'].browse(location_ids).filtered(lambda l: l.exists())
        else:
            loc_param = self.env['ir.config_parameter'].sudo().get_param(
                'mrp_reschedule.stock_location_id')
            try:
                loc_id = int(loc_param) if loc_param else False
            except (ValueError, TypeError):
                loc_id = False
            loc = self.env['stock.location'].browse(loc_id) if loc_id else self.env['stock.location']
            locations = loc if loc_id and loc.exists() else self.env['stock.location']

        if not locations:
            return {'error': 'no_location', 'kpis': _empty_kpis,
                    'products': [], 'location_name': '', 'location_ids': [],
                    'location_id': False, 'total_filtered': 0}

        location_name = ' + '.join(locations.mapped('complete_name'))

        # Ruta fabricación: primero por xmlid, fallback por nombre
        mfg_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        if not mfg_route:
            mfg_route = self.env['stock.route'].search(
                [('name', 'ilike', 'manufactur')], limit=1)

        # Productos vendibles activos
        product_domain = [('sale_ok', '=', True), ('active', '=', True), ('type', '=', 'consu')]
        if search:
            product_domain += ['|', ('name', 'ilike', search), ('default_code', 'ilike', search)]
        # Traer sólo los IDs primero; los campos se cargan luego sólo para la página.
        product_ids_all = self.env['product.product'].search(product_domain).ids
        if not product_ids_all:
            return {'error': None, 'kpis': _empty_kpis,
                    'products': [], 'location_name': location_name, 'total_filtered': 0}

        product_ids = product_ids_all

        # Puntos de reorden con ruta fabricación → min_qty por producto.
        # read_group no funciona con qty_forecast (campo computed no stored),
        # así que se usa .search() + loop tomando el máximo por producto.
        op_domain = [('product_id', 'in', product_ids)]
        if mfg_route:
            op_domain.append(('route_id', '=', mfg_route.id))
        orderpoints = self.env['stock.warehouse.orderpoint'].search(op_domain)
        min_qty_map = {}
        forecast_map = {}
        for op in orderpoints:
            pid = op.product_id.id
            op_min = op.product_min_qty
            if pid not in min_qty_map or op_min > min_qty_map[pid]:
                min_qty_map[pid] = op_min
                forecast_map[pid] = getattr(op, 'qty_forecast', None)

        # Stock en ubicaciones seleccionadas (batch via read_group)
        # Fix 17: añadir location_id.usage='internal' para excluir ubicaciones no internas
        quant_groups = self.env['stock.quant'].read_group(
            [('product_id', 'in', product_ids),
             ('location_id', 'child_of', locations.ids),
             ('location_id.usage', '=', 'internal')],
            ['product_id', 'quantity:sum'],
            ['product_id'],
        )
        qty_map = {g['product_id'][0]: g['quantity'] for g in quant_groups}

        # Config: rotación en quiebres
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        show_rotation        = (cfg.stock_break_show_rotation   if cfg else False)
        rotation_method      = (cfg.stock_break_rotation_method if cfg else None) or 'units'
        rotation_months_cfg  = (cfg.stock_break_rotation_months if cfg else 3) or 3
        rotation_period_days = rotation_months_cfg * 30

        rotation_days_map    = {}
        rotation_months_map  = {}
        rotation_avg_stock_map  = {}  # tooltip units: stock promedio
        rotation_period_out_map = {}  # tooltip units: salidas del período
        if show_rotation:
            d_rot        = _date.today() - timedelta(days=rotation_period_days)
            dt_rot_str   = fields.Datetime.to_string(_datetime(d_rot.year, d_rot.month, d_rot.day))
            dt_today_str = fields.Datetime.to_string(_datetime.combine(_date.today(), _datetime.max.time()))

            if rotation_method == 'units':
                try:
                    SM = self.env['stock.move'].sudo()
                    _sm_base = [
                        ('state', '=', 'done'),
                        ('product_id', 'in', product_ids),
                        ('company_id', '=', self.env.company.id),
                    ]
                    # Misma metodología que el forecast: 4 queries para reconstruir
                    # stock_start (al inicio del período) y stock_end (al final = hoy),
                    # ambos a nivel empresa (sin filtro de ubicación), para coherencia.
                    qty_in_start  = {}
                    qty_out_start = {}
                    qty_in_end    = {}
                    qty_out_end   = {}
                    for g in SM.read_group(_sm_base + [
                        ('date', '<', dt_rot_str),
                        ('location_dest_id.usage', '=', 'internal'),
                        ('location_id.usage', '!=', 'internal'),
                    ], ['product_id', 'product_qty:sum'], ['product_id']):
                        if g['product_id']:
                            qty_in_start[g['product_id'][0]] = g['product_qty'] or 0.0
                    for g in SM.read_group(_sm_base + [
                        ('date', '<', dt_rot_str),
                        ('location_id.usage', '=', 'internal'),
                        ('location_dest_id.usage', '!=', 'internal'),
                    ], ['product_id', 'product_qty:sum'], ['product_id']):
                        if g['product_id']:
                            qty_out_start[g['product_id'][0]] = g['product_qty'] or 0.0
                    for g in SM.read_group(_sm_base + [
                        ('date', '<=', dt_today_str),
                        ('location_dest_id.usage', '=', 'internal'),
                        ('location_id.usage', '!=', 'internal'),
                    ], ['product_id', 'product_qty:sum'], ['product_id']):
                        if g['product_id']:
                            qty_in_end[g['product_id'][0]] = g['product_qty'] or 0.0
                    for g in SM.read_group(_sm_base + [
                        ('date', '<=', dt_today_str),
                        ('location_id.usage', '=', 'internal'),
                        ('location_dest_id.usage', '!=', 'internal'),
                    ], ['product_id', 'product_qty:sum'], ['product_id']):
                        if g['product_id']:
                            qty_out_end[g['product_id'][0]] = g['product_qty'] or 0.0

                    for _pid in product_ids:
                        stock_start  = max(0.0, qty_in_start.get(_pid, 0.0) - qty_out_start.get(_pid, 0.0))
                        stock_end    = max(0.0, qty_in_end.get(_pid, 0.0)   - qty_out_end.get(_pid, 0.0))
                        avg_stock    = (stock_start + stock_end) / 2.0
                        _out         = qty_out_end.get(_pid, 0.0) - qty_out_start.get(_pid, 0.0)
                        _avg_monthly = _out / rotation_months_cfg
                        if _avg_monthly > 0 and avg_stock > 0:
                            rotation_days_map[_pid]      = int(round(avg_stock / _avg_monthly * 30))
                            rotation_months_map[_pid]    = round(avg_stock / _avg_monthly, 1)
                            rotation_avg_stock_map[_pid] = round(avg_stock, 2)
                            rotation_period_out_map[_pid]= round(_out, 2)
                except Exception:
                    pass

            elif rotation_method in ('cogs', 'sales') and 'stock.valuation.layer' in self.env:
                try:
                    SVL = self.env['stock.valuation.layer'].sudo()
                    cogs_map      = {}
                    inv_start_map = {}
                    inv_end_map   = {}
                    for g in SVL.read_group([
                        ('product_id', 'in', product_ids),
                        ('create_date', '>=', dt_rot_str),
                        ('create_date', '<=', dt_today_str),
                        ('value', '<', 0),
                        ('company_id', '=', self.env.company.id),
                    ], ['product_id', 'value:sum'], ['product_id']):
                        if g['product_id']:
                            cogs_map[g['product_id'][0]] = -(g['value'] or 0.0)
                    for g in SVL.read_group([
                        ('product_id', 'in', product_ids),
                        ('create_date', '<', dt_rot_str),
                        ('company_id', '=', self.env.company.id),
                    ], ['product_id', 'value:sum'], ['product_id']):
                        if g['product_id']:
                            inv_start_map[g['product_id'][0]] = g['value'] or 0.0
                    for g in SVL.read_group([
                        ('product_id', 'in', product_ids),
                        ('create_date', '<=', dt_today_str),
                        ('company_id', '=', self.env.company.id),
                    ], ['product_id', 'value:sum'], ['product_id']):
                        if g['product_id']:
                            inv_end_map[g['product_id'][0]] = g['value'] or 0.0

                    sales_map = {}
                    if rotation_method == 'sales':
                        for g in self.env['sale.order.line'].sudo().read_group([
                            ('order_id.state', 'in', ('sale', 'done')),
                            ('order_id.date_order', '>=', dt_rot_str),
                            ('order_id.date_order', '<=', dt_today_str),
                            ('product_id', 'in', product_ids),
                            ('company_id', '=', self.env.company.id),
                        ], ['product_id', 'price_subtotal:sum'], ['product_id']):
                            if g['product_id']:
                                sales_map[g['product_id'][0]] = g['price_subtotal'] or 0.0

                    for _pid in product_ids:
                        avg_inv = (inv_start_map.get(_pid, 0.0) + inv_end_map.get(_pid, 0.0)) / 2.0
                        if avg_inv <= 0:
                            continue
                        base = cogs_map.get(_pid, 0.0) if rotation_method == 'cogs' else sales_map.get(_pid, 0.0)
                        if base > 0:
                            dio = rotation_period_days * avg_inv / base
                            rotation_days_map[_pid]   = int(round(dio))
                            rotation_months_map[_pid] = round(dio / 30.0, 1)
                except Exception:
                    pass

        # Construir filas sólo con los IDs ya cargados (sin acceder a campos ORM aquí)
        rows = []
        for pid in product_ids_all:
            qty     = round(qty_map.get(pid, 0.0), 3)
            min_qty = min_qty_map.get(pid)
            has_min = min_qty is not None
            raw_forecast = forecast_map.get(pid)
            rows.append({
                'id':             pid,
                'name':           None,   # se rellena sólo para la página (ver SB-02b)
                'qty':            qty,
                'min_qty':        min_qty if has_min else None,
                'has_min':        has_min,
                'is_broken':      has_min and qty < (min_qty - 0.001),
                'qty_forecast':   round(raw_forecast, 3) if raw_forecast is not None else None,
                'rotation_days':      rotation_days_map.get(pid),
                'rotation_months':    rotation_months_map.get(pid),
                'rotation_avg_stock': rotation_avg_stock_map.get(pid),
                'rotation_period_out':rotation_period_out_map.get(pid),
            })

        # KPIs sobre el conjunto completo
        kpis = {
            'total':  len(rows),
            'broken': sum(1 for r in rows if r['is_broken']),
            'ok':     sum(1 for r in rows if r['has_min'] and not r['is_broken']),
            'no_min': sum(1 for r in rows if not r['has_min']),
        }

        # Filtro
        if filter_type == 'broken':
            rows = [r for r in rows if r['is_broken']]
        elif filter_type == 'ok':
            rows = [r for r in rows if r['has_min'] and not r['is_broken']]
        elif filter_type == 'no_min':
            rows = [r for r in rows if not r['has_min']]

        # Sort — para sort por nombre, cargar display_name de todos los IDs filtrados antes de ordenar
        # Se invierte la lógica booleana para pasar directamente a reverse= de list.sort()
        _rev = (sort_dir == 'desc')
        if sort_field == 'name':
            _all_pids_for_sort = [r['id'] for r in rows]
            _name_map_sort = {p['id']: p['display_name'] for p in
                              self.env['product.product'].browse(_all_pids_for_sort).read(['id', 'display_name'])}
            for r in rows:
                r['name'] = _name_map_sort.get(r['id'], '')
            rows.sort(key=lambda r: (r['name'] or '').lower(), reverse=_rev)
        elif sort_field == 'qty':
            rows.sort(key=lambda r: r['qty'], reverse=_rev)
        elif sort_field == 'min_qty':
            rows.sort(key=lambda r: (r['min_qty'] if r['min_qty'] is not None else -1), reverse=_rev)
        elif sort_field == 'qty_forecast':
            # -999999 empuja los productos sin forecast al final cuando se ordena ascendente
            rows.sort(key=lambda r: r['qty_forecast'] if r['qty_forecast'] is not None else -999999, reverse=_rev)
        elif sort_field == 'rotation':
            rows.sort(key=lambda r: r['rotation_days'] if r['rotation_days'] is not None else 999999, reverse=_rev)
        elif sort_field == 'status':
            rows.sort(key=lambda r: (0 if r['is_broken'] else 1 if not r['has_min'] else 2), reverse=_rev)
        else:
            # Default: quiebres primero, luego OK, luego sin mínimo; dentro de cada grupo por nombre
            rows.sort(key=lambda r: (
                0 if r['is_broken'] else 1 if not r['has_min'] else 2,
            ))

        total_filtered = len(rows)
        # max(1, page) protege contra valores de página ≤ 0 enviados desde el cliente
        offset = (max(1, page) - 1) * page_size
        page_rows = rows[offset:offset + page_size]

        # Después de paginar, cargar display_name sólo para los IDs de la página (SB-02b)
        page_pids = [r['id'] for r in page_rows]
        if page_pids:
            page_prods_map = {p['id']: p['display_name'] for p in
                              self.env['product.product'].browse(page_pids).read(['id', 'display_name'])}
            for r in page_rows:
                if r['name'] is None:
                    r['name'] = page_prods_map.get(r['id'], '')

        # Fix 18: calcular no_subcontract_domain UNA vez
        no_sc_domain = no_subcontract_domain(self.env)

        # Conteo de OFs activas para los productos de esta página
        if page_pids:
            mo_groups = self.env['mrp.production'].read_group(
                [('product_id', 'in', page_pids),
                 ('state', 'in', ['confirmed', 'progress', 'to_close'])] + no_sc_domain,
                ['product_id'],
                ['product_id'],
            )
            mo_count_map = {g['product_id'][0]: g['product_id_count'] for g in mo_groups}
        else:
            mo_count_map = {}
        for r in page_rows:
            r['mo_count'] = mo_count_map.get(r['id'], 0)

        # Tipos de producto para esta página (batch) — Fix 16
        if page_pids:
            page_prods = self.env['product.product'].browse(page_pids)
            page_tmpls = page_prods.mapped('product_tmpl_id')
            # Forzar prefetch de la M2M en una sola query antes del loop
            page_tmpls.mapped('x_product_type_ids')  # carga el batch completo
            tmpl_type_map = {
                t.id: ', '.join(t.x_product_type_ids.mapped('name'))
                for t in page_tmpls
            }
            prod_to_tmpl = {p.id: p.product_tmpl_id.id for p in page_prods}
        else:
            tmpl_type_map = {}
            prod_to_tmpl = {}
        for r in page_rows:
            tmpl_id = prod_to_tmpl.get(r['id'])
            r['product_types'] = tmpl_type_map.get(tmpl_id, '') if tmpl_id else ''

        rotation_unit          = (cfg.forecast_rotation_unit             if cfg else None) or 'days'
        rotation_warn_days     = (cfg.stock_break_rotation_warn_days     if cfg else 90)  or 90
        rotation_critical_days = (cfg.stock_break_rotation_critical_days if cfg else 180) or 180

        return {
            'error':          None,
            'kpis':           kpis,
            'products':       page_rows,
            'location_name':  location_name,
            'location_ids':   locations.ids,
            'location_id':    locations[0].id if locations else False,
            'total_filtered': total_filtered,
            'rotation_unit':          rotation_unit,
            'show_rotation':          show_rotation,
            'rotation_months':        rotation_months_cfg,
            'rotation_method':        rotation_method,
            'rotation_warn_days':     rotation_warn_days,
            'rotation_critical_days': rotation_critical_days,
        }

    @api.model
    def get_product_mos_for_stock_break(self, product_id):
        """
        Devuelve las órdenes de fabricación activas de un producto para el acordeón del widget.

        Consulta las OFs en estados 'confirmed', 'progress' o 'to_close' del producto
        indicado, excluyendo órdenes de subcontratación. El resultado se usa para poblar
        el panel desplegable de cada producto en el widget de quiebres de stock.

        :param product_id: int — ID del product.product a consultar.
        :returns: list[dict] con las claves:
            - 'id': int — ID de la OF.
            - 'name': str — referencia de la OF (ej. WH/MO/00001).
            - 'state': str — estado técnico de Odoo.
            - 'state_label': str — etiqueta en español del estado.
            - 'product_qty': float — cantidad planificada (redondeada a 2 decimales).
            - 'qty_produced': float — cantidad ya producida (redondeada a 2 decimales).
            - 'uom': str — nombre de la unidad de medida.
            - 'date_finished': str — fecha de fin planificada en formato dd/mm/YYYY o '—'.
        """
        # limit=50 evita cargar acordeones excesivamente largos para productos con muchas OFs
        mos = self.env['mrp.production'].search([
            ('product_id', '=', product_id),
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
        ] + no_subcontract_domain(self.env), limit=50, order='date_finished asc')
        state_labels = {
            'confirmed': 'Confirmada',
            'progress':  'En progreso',
            'to_close':  'Por cerrar',
        }
        return [{
            'id':            mo.id,
            'name':          mo.name,
            'state':         mo.state,
            'state_label':   state_labels.get(mo.state, mo.state),
            'product_qty':   round(mo.product_qty, 2),
            'qty_produced':  round(mo.qty_produced, 2),
            'uom':           mo.product_uom_id.name if mo.product_uom_id else '',
            'date_finished': mo.date_finished.strftime('%d/%m/%Y') if mo.date_finished else '—',
        } for mo in mos]
