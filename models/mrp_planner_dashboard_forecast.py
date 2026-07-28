# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_forecast.py
Modelo: extensión de 'mrp.planner.dashboard'

Extiende el dashboard del planificador MRP con toda la lógica de Forecast:
consulta líneas de forecast, ÓFs planificadas, entregas y demanda real de ventas
para construir una tabla pivotada por producto × mes con KPIs de cobertura,
precisión de forecast y rotación de stock.

Responsabilidades:
- Exponer la lista de almacenes disponibles para el filtro de forecast.
- Calcular y retornar el payload completo del widget de forecast (KPIs + tabla).
- Proveer el drill-down de ÓFs por producto para el acordeón del widget.
- Generar y devolver un archivo Excel (.xlsx) con el resumen de forecast vs. OFs.

Relacionado con:
- mrp.planner.dashboard: clase base que este mixin extiende con _inherit.
- mrp.forecast.line: líneas de forecast agrupadas por producto y período.
- mrp.production: órdenes de fabricación consultadas para cobertura de forecast.
- mrp.reschedule.config: configuración de umbrales, fórmula de precisión y estados de OF.
- stock.move.line: movimientos de salida completados (entregas reales).
- sale.order.line: demanda real de pedidos de venta confirmados.
- stock.quant: stock actual para cálculo de rotación.
"""
import logging
import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

from .const import FORECAST_WARNING_PCT, FORECAST_CRITICAL_PCT

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardForecast(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Forecast ─────────────────────────────────────────────────────────────

    @api.model
    def get_warehouses_for_forecast(self):
        """
        Retorna la lista de almacenes accesibles por el usuario actual para el filtro de forecast.

        Si el usuario tiene el flag 'mrp_planner_all_warehouses' activo, o no tiene
        almacenes asignados, se devuelven todos los almacenes de la base de datos.
        En caso contrario, solo se devuelven los almacenes explícitamente asignados al usuario.

        :returns: list[dict] — lista de dicts con 'id' (int) y 'name' (str) de cada almacén,
                  ordenados alfabéticamente por nombre.
        """
        user = self.env.user
        if user.mrp_planner_all_warehouses or not user.mrp_planner_warehouse_ids:
            whs = self.env['stock.warehouse'].search([], order='name')
        else:
            whs = user.mrp_planner_warehouse_ids.sorted('name')
        return [{'id': w.id, 'name': w.name} for w in whs]

    @api.model
    def get_forecast_dashboard_data(self, period_from, period_to, warehouse_ids=None):
        """
        Devuelve KPIs y tabla pivotada forecast vs ÓFs para el rango de meses indicado.

        Requiere pertenecer a un grupo de ventas del planificador (lee con sudo).

        Construye el payload completo que consume el widget de forecast del dashboard.
        El proceso interno sigue este orden:
        1. Parsear rango de fechas y convertir a UTC para dominios Datetime.
        2. Leer configuración (umbrales, fórmula de precisión, estados de OF aceptados).
        3. Consultar mrp.forecast.line en el período.
        4. Consultar mrp.production filtradas por estado, fecha y exclusión de subcontratación.
        5. Consultar stock.move.line (entregas completadas) para los productos con forecast.
        6. Consultar sale.order.line (demanda real) para los productos con forecast.
        7. Consultar stock.quant (snapshot de stock actual) por almacén si se filtra.
        8. Construir filas por producto con celdas mensuales y totales.
        9. Calcular KPIs globales y métricas para productos sin línea de forecast.

        :param period_from: str — fecha de inicio en formato 'YYYY-MM' o 'YYYY-MM-DD'.
        :param period_to:   str — fecha de fin en formato 'YYYY-MM' o 'YYYY-MM-DD'.
        :param warehouse_ids: list[int] | None — IDs de almacenes para filtrar stock y OFs.
                              Si es None o lista vacía, se consideran todos los almacenes.
        :returns: dict con las claves:
            - 'kpis' (dict): métricas globales del período.
            - 'months' (list[str]): lista de meses 'YYYY-MM' en el rango.
            - 'month_totals' (list[dict]): totales por mes de forecast, OFs, entregado y demanda.
            - 'rows' (list[dict]): una fila por producto con 'cells', totales y métricas de precisión.
            - 'warning_pct' (float): umbral de alerta configurado (defecto 70 %).
            - 'critical_pct' (float): umbral crítico configurado (defecto 50 %).
            - 'rotation_unit' (str): unidad de rotación 'days' o 'months'.
            - 'acc_formula' (str): fórmula de precisión activa ('simple', 'mape', 'wape', 'wmape', 'bias').
            - 'mo_states' (list[str]): estados de OF incluidos en el cálculo.
        """
        from datetime import date as _date
        import calendar as _calendar

        # Guard de grupo: lee ventas/stock con sudo(); panel de ventas.
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        warehouse_ids = warehouse_ids or []

        def _parse_ym(ym):
            """Convierte 'YYYY-MM' o 'YYYY-MM-DD' a un objeto date (día 1 si no se especifica)."""
            parts = ym.split('-')
            y, m = int(parts[0]), int(parts[1])
            d = int(parts[2]) if len(parts) >= 3 else 1
            return _date(y, m, d)

        def _months_between(d_from, d_to):
            """Genera lista de strings 'YYYY-MM' para cada mes entre d_from y d_to inclusive."""
            months = []
            d = _date(d_from.year, d_from.month, 1)
            while d <= _date(d_to.year, d_to.month, 1):
                months.append(f"{d.year}-{d.month:02d}")
                if d.month == 12:
                    d = _date(d.year + 1, 1, 1)
                else:
                    d = _date(d.year, d.month + 1, 1)
            return months

        try:
            d_from = _parse_ym(period_from)
            d_to   = _parse_ym(period_to)
        except Exception:
            return {'kpis': {}, 'months': [], 'month_totals': [], 'rows': [],
                    'warning_pct': FORECAST_WARNING_PCT, 'critical_pct': FORECAST_CRITICAL_PCT}

        months = _months_between(d_from, d_to)

        cfg = self.env['mrp.reschedule.config'].get_config()
        warning_pct    = cfg.forecast_warning_pct    if cfg else FORECAST_WARNING_PCT    # umbral de alerta (cobertura aceptable mínima)
        critical_pct   = cfg.forecast_critical_pct   if cfg else FORECAST_CRITICAL_PCT   # umbral crítico (cobertura insuficiente)
        rotation_unit   = (cfg.forecast_rotation_unit   if cfg else None) or 'days'
        rotation_method = (cfg.forecast_rotation_method if cfg else None) or 'units'
        acc_formula      = (cfg.forecast_acc_formula      if cfg else None) or 'simple'
        precision_source = (cfg.forecast_precision_source if cfg else None) or 'demand'
        coverage_unit            = (cfg.forecast_coverage_unit            if cfg else None) or 'days'
        coverage_demand_source   = (cfg.forecast_coverage_demand_source   if cfg else None) or 'forecast'
        coverage_alerts_enabled  = bool(cfg.forecast_coverage_alerts_enabled) if cfg else False
        coverage_warn_days       = (cfg.forecast_coverage_warn_days       if cfg else None) or 30
        coverage_critical_days   = (cfg.forecast_coverage_critical_days   if cfg else None) or 15
        mo_coverage_show_pct     = bool(cfg.forecast_mo_coverage_show_pct) if cfg else True
        mo_coverage_denominator  = (cfg.forecast_mo_coverage_denominator  if cfg else None) or 'forecast'
        mo_coverage_color_scope  = (cfg.forecast_mo_coverage_color_scope  if cfg else None) or 'both'

        # Estados de OF configurados
        mo_states = []
        if cfg:
            if cfg.forecast_mo_state_draft:     mo_states.append('draft')
            if cfg.forecast_mo_state_confirmed: mo_states.append('confirmed')
            if cfg.forecast_mo_state_progress:  mo_states.append('progress')
            if cfg.forecast_mo_state_to_close:  mo_states.append('to_close')
            if cfg.forecast_mo_state_done:      mo_states.append('done')
        if not mo_states:
            # Fallback a los estados productivos más relevantes si la config no especifica ninguno
            mo_states = ['confirmed', 'progress', 'to_close']

        last_day_of_to = d_to  # día exacto seleccionado por el usuario

        # Conversión a UTC para dominios Datetime (Odoo guarda en UTC)
        tz_name  = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz  = pytz.timezone(tz_name)

        def _to_utc(dt_naive):
            """Localiza un datetime naive en la zona del usuario y lo convierte a UTC naive."""
            return user_tz.localize(dt_naive).astimezone(pytz.utc).replace(tzinfo=None)

        def _dt_ym(dt_utc):
            """Devuelve 'YYYY-MM' en hora local a partir de un Datetime UTC."""
            return pytz.utc.localize(dt_utc).astimezone(user_tz).strftime('%Y-%m')

        dt_from = _to_utc(datetime.combine(d_from, datetime.min.time()))
        dt_to   = _to_utc(datetime.combine(last_day_of_to, datetime.max.time()))

        # ── Forecast lines ────────────────────────────────────────────────────
        fc_domain = [
            ('period', '>=', _date(d_from.year, d_from.month, 1)),
            ('period', '<=', last_day_of_to),
            ('company_id', '=', self.env.company.id),
        ]

        fc_lines = self.env['mrp.forecast.line'].search(fc_domain)

        # Precarga en un solo SELECT todos los campos relacionales necesarios
        _product_ids_fc = fc_lines.mapped('product_id')
        _product_read   = {r['id']: r for r in _product_ids_fc.read(['id', 'display_name', 'product_tmpl_id'])}

        # Estructura: {product_id: {month_str: forecast_qty}}
        fc_data = {}
        for line in fc_lines:
            pid = line.product_id.id
            ym  = f"{line.period.year}-{line.period.month:02d}"
            if pid not in fc_data:
                _pr = _product_read.get(pid, {})
                fc_data[pid] = {
                    'product':         _pr.get('display_name', ''),
                    'product_tmpl_id': _pr.get('product_tmpl_id', [False])[0],
                }
            fc_data[pid][ym] = fc_data[pid].get(ym, 0.0) + line.forecast_qty

        # ── ÓFs planificadas ──────────────────────────────────────────────────
        mo_mode = (cfg.comparison_date_mode if cfg else None) or 'finish_date'

        no_sc_domain = no_subcontract_domain(self.env)
        wh_filter = [('picking_type_id.warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []

        mo_data = {}  # {product_id: {month_str: qty}}

        if mo_mode == 'finish_date':
            mo_domain = [
                ('state', 'in', mo_states),
                ('date_finished', '>=', fields.Datetime.to_string(dt_from)),
                ('date_finished', '<=', fields.Datetime.to_string(dt_to)),
            ] + no_sc_domain + wh_filter
            mos = self.env['mrp.production'].search(mo_domain)
            for _mo in mos.read(['product_id', 'date_finished', 'product_qty']):
                pid = _mo['product_id'][0] if _mo['product_id'] else False
                df  = _mo['date_finished']
                if not pid or not df:
                    continue
                ym = _dt_ym(df)
                if ym not in months:
                    continue
                if pid not in mo_data:
                    mo_data[pid] = {}
                mo_data[pid][ym] = mo_data[pid].get(ym, 0.0) + _mo['product_qty']
        elif mo_mode == 'start_date':
            mo_domain = [
                ('state', 'in', mo_states),
                ('date_start', '>=', fields.Datetime.to_string(dt_from)),
                ('date_start', '<=', fields.Datetime.to_string(dt_to)),
            ] + no_sc_domain + wh_filter
            mos = self.env['mrp.production'].search(mo_domain)
            for _mo in mos.read(['product_id', 'date_start', 'product_qty']):
                pid = _mo['product_id'][0] if _mo['product_id'] else False
                ds  = _mo['date_start']
                if not pid or not ds:
                    continue
                ym = _dt_ym(ds)
                if ym not in months:
                    continue
                if pid not in mo_data:
                    mo_data[pid] = {}
                mo_data[pid][ym] = mo_data[pid].get(ym, 0.0) + _mo['product_qty']
        else:
            # overlap y proportional: OFs que solapan el rango completo
            mo_domain_wide = [
                ('state', 'in', mo_states),
                ('date_start', '<=', fields.Datetime.to_string(dt_to)),
                '|',
                ('date_finished', '>=', fields.Datetime.to_string(dt_from)),
                ('date_finished', '=', False),
            ] + no_sc_domain + wh_filter
            mos_wide = self.env['mrp.production'].search(mo_domain_wide)

            # Límites UTC de cada mes para cálculo de solapamiento
            def _month_bounds_utc(ym_str):
                y, m = int(ym_str[:4]), int(ym_str[5:])
                m_start = _to_utc(datetime(y, m, 1, 0, 0, 0))
                if m == 12:
                    m_end = _to_utc(datetime(y + 1, 1, 1, 0, 0, 0)) - timedelta(seconds=1)
                else:
                    m_end = _to_utc(datetime(y, m + 1, 1, 0, 0, 0)) - timedelta(seconds=1)
                return m_start, m_end

            month_bounds = {ym: _month_bounds_utc(ym) for ym in months}

            for _mo in mos_wide.read(['product_id', 'date_start', 'date_finished', 'product_qty']):
                pid = _mo['product_id'][0] if _mo['product_id'] else False
                if not pid:
                    continue
                mo_start = _mo['date_start']
                mo_end   = _mo['date_finished']
                qty      = _mo['product_qty']

                if mo_mode == 'overlap':
                    for ym, (m_start, m_end) in month_bounds.items():
                        if mo_start and mo_start <= m_end and (not mo_end or mo_end >= m_start):
                            if pid not in mo_data:
                                mo_data[pid] = {}
                            mo_data[pid][ym] = mo_data[pid].get(ym, 0.0) + qty
                else:  # proportional
                    if mo_start and mo_end and mo_start < mo_end:
                        total_secs = (mo_end - mo_start).total_seconds()
                        for ym, (m_start, m_end) in month_bounds.items():
                            ov_start = max(mo_start, m_start)
                            ov_end   = min(mo_end, m_end)
                            overlap_secs = max(0.0, (ov_end - ov_start).total_seconds())
                            if overlap_secs > 0:
                                if pid not in mo_data:
                                    mo_data[pid] = {}
                                mo_data[pid][ym] = mo_data[pid].get(ym, 0.0) + qty * (overlap_secs / total_secs)
                    elif mo_end:
                        # sin date_start: fallback a mes de cierre
                        ym = _dt_ym(mo_end)
                        if ym in months:
                            if pid not in mo_data:
                                mo_data[pid] = {}
                            mo_data[pid][ym] = mo_data[pid].get(ym, 0.0) + qty

        # ── Ids de productos con forecast ──────────────────────────────────────
        all_product_ids      = set(fc_data.keys())
        all_product_ids_list = list(all_product_ids)
        # n_months para cálculo de rotación: duración real en meses, no meses de calendario tocados.
        # Ej: 08/04 → 08/07 = 91 días ≈ 3,03 meses, pero len(months) = 4 (abr, may, jun, jul).
        _period_days = max(1, (last_day_of_to - d_from).days)
        n_months     = max(1.0, _period_days / 30.0)

        # ── Movimientos de salida completados (entregado) ──────────────────────
        del_line_domain = [
            ('state', '=', 'done'),
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('date', '>=', fields.Datetime.to_string(dt_from)),
            ('date', '<=', fields.Datetime.to_string(dt_to)),
            ('product_id', 'in', all_product_ids_list),
            ('company_id', '=', self.env.company.id),
        ]
        del_data = {}           # {product_id: {ym: qty}}
        del_by_order_month = {} # {product_id: {order_ym: qty}} — para tooltip por mes de OV
        _del_lines = self.env['stock.move.line'].search(del_line_domain).read(
            ['product_id', 'date', 'quantity', 'picking_id'])

        # Batch-fetch sale_id por picking y date_order por sale para el tooltip
        _del_pick_ids = list({ml['picking_id'][0] for ml in _del_lines if ml['picking_id']})
        _pick_to_sale = {}
        if _del_pick_ids:
            for _p in self.env['stock.picking'].browse(_del_pick_ids).read(['id', 'sale_id']):
                _pick_to_sale[_p['id']] = _p['sale_id'][0] if _p['sale_id'] else None
        _del_sale_ids = list({sid for sid in _pick_to_sale.values() if sid})
        _del_sale_dates = {}
        if _del_sale_ids:
            for _s in self.env['sale.order'].browse(_del_sale_ids).read(['id', 'date_order']):
                _del_sale_dates[_s['id']] = _s['date_order']

        for _ml in _del_lines:
            pid = _ml['product_id'][0] if _ml['product_id'] else False
            dt  = _ml['date']
            if not pid or not dt:
                continue
            ym = _dt_ym(dt)
            if ym not in months:
                continue
            qty = _ml['quantity']
            del_data.setdefault(pid, {})
            del_data[pid][ym] = del_data[pid].get(ym, 0.0) + qty

            # Acumular por mes de confirmación del pedido origen. Las salidas sin
            # pedido de venta vinculado (devoluciones a proveedor, remitos manuales,
            # transferencias de tipo salida) van a la clave '' para que el desglose
            # del tooltip siempre sume igual que el total.
            _pick_id  = _ml['picking_id'][0] if _ml['picking_id'] else None
            _sale_id  = _pick_to_sale.get(_pick_id) if _pick_id else None
            _order_dt = _del_sale_dates.get(_sale_id) if _sale_id else None
            if _order_dt:
                _oym = _order_dt.strftime('%Y-%m') if hasattr(_order_dt, 'strftime') else str(_order_dt)[:7]
            else:
                _oym = ''
            del_by_order_month.setdefault(pid, {})
            del_by_order_month[pid][_oym] = del_by_order_month[pid].get(_oym, 0.0) + qty

        # ── Demanda real: pedidos de venta confirmados ─────────────────────────
        so_data = {}    # {product_id: {ym: qty}}
        try:
            so_domain = [
                ('order_id.state', 'in', ('sale', 'done')),
                ('order_id.date_order', '>=', fields.Datetime.to_string(dt_from)),
                ('order_id.date_order', '<=', fields.Datetime.to_string(dt_to)),
                ('product_id', 'in', all_product_ids_list),
                ('company_id', '=', self.env.company.id),
            ]
            sol_rows = self.env['sale.order.line'].search(so_domain).read(
                ['product_id', 'product_uom_qty', 'order_id']
            )
            # Precarga date_order de todas las sale.order en un solo SELECT
            _order_ids  = list({r['order_id'][0] for r in sol_rows if r['order_id']})
            _order_dates = {o['id']: o['date_order'] for o in
                            self.env['sale.order'].browse(_order_ids).read(['id', 'date_order'])}
            for _sl in sol_rows:
                pid = _sl['product_id'][0] if _sl['product_id'] else False
                if not pid:
                    continue
                dt  = _order_dates.get(_sl['order_id'][0]) if _sl['order_id'] else None
                if not dt:
                    continue
                ym  = _dt_ym(dt)
                if ym not in months:
                    continue
                so_data.setdefault(pid, {})
                so_data[pid][ym] = so_data[pid].get(ym, 0.0) + _sl['product_uom_qty']
        except Exception:
            pass    # módulo sale no disponible

        # ── Cumplimiento de demanda: entregas de pedidos del período, por mes del pedido ──
        demand_del_data = {}  # {product_id: {ym: qty}} — agrupado por mes de confirmación del SO
        _period_so_ids  = []
        try:
            _period_sos = self.env['sale.order'].search([
                ('state', 'in', ('sale', 'done')),
                ('date_order', '>=', fields.Datetime.to_string(dt_from)),
                ('date_order', '<=', fields.Datetime.to_string(dt_to)),
                ('company_id', '=', self.env.company.id),
            ])
            _period_so_ids = _period_sos.ids
            # Mapa SO → mes de confirmación
            _so_to_ym = {
                so.id: so.date_order.strftime('%Y-%m')
                for so in _period_sos if so.date_order
            }
            if _period_so_ids and all_product_ids_list:
                demand_del_dom = [
                    ('state', '=', 'done'),
                    ('picking_id.picking_type_id.code', '=', 'outgoing'),
                    ('picking_id.sale_id', 'in', _period_so_ids),
                    ('product_id', 'in', all_product_ids_list),
                    ('company_id', '=', self.env.company.id),
                ]
                _dd_lines = self.env['stock.move.line'].search(demand_del_dom).read(
                    ['product_id', 'quantity', 'picking_id'])
                # Mapa picking → SO id
                _dd_pick_ids = list({ml['picking_id'][0] for ml in _dd_lines if ml['picking_id']})
                _dd_pick_to_so = {}
                if _dd_pick_ids:
                    for _p in self.env['stock.picking'].browse(_dd_pick_ids).read(['id', 'sale_id']):
                        if _p['sale_id']:
                            _dd_pick_to_so[_p['id']] = _p['sale_id'][0]
                for _ml in _dd_lines:
                    _pid   = _ml['product_id'][0] if _ml['product_id'] else False
                    _pick  = _ml['picking_id'][0]  if _ml['picking_id'] else False
                    if not _pid or not _pick:
                        continue
                    _so_id = _dd_pick_to_so.get(_pick)
                    _ym    = _so_to_ym.get(_so_id) if _so_id else None
                    if _ym:
                        demand_del_data.setdefault(_pid, {})
                        demand_del_data[_pid][_ym] = demand_del_data[_pid].get(_ym, 0.0) + _ml['quantity']
        except Exception:
            pass

        # ── Stock actual (snapshot) ───────────────────────────────────────────
        stock_data = {}   # {product_id: qty}
        quant_domain = [
            ('location_id.usage', '=', 'internal'),
            ('product_id', 'in', all_product_ids_list),
            ('company_id', '=', self.env.company.id),
        ]
        # Ubicaciones del filtro de depósito; se reutilizan para que la rotación (stock
        # promedio) tome exactamente el mismo alcance que el snapshot de stock actual.
        rotation_loc_ids = None
        if warehouse_ids:
            wh_recs  = self.env['stock.warehouse'].browse(warehouse_ids)
            loc_ids  = wh_recs.mapped('lot_stock_id').ids
            if loc_ids:
                quant_domain.append(('location_id', 'in', loc_ids))
                rotation_loc_ids = loc_ids
        for _qg in self.env['stock.quant'].read_group(
                quant_domain, ['product_id', 'quantity:sum'], ['product_id']):
            pid = _qg['product_id'][0] if _qg['product_id'] else False
            if pid:
                stock_data[pid] = round(_qg['quantity'] or 0.0, 6)

        # ── Datos de rotación + construcción de filas ─────────────────────────
        dt_from_str    = fields.Datetime.to_string(dt_from)
        dt_to_str      = fields.Datetime.to_string(dt_to)
        rotation_data  = self._fc_rotation_data(
            all_product_ids_list, rotation_method, dt_from_str, dt_to_str,
            location_ids=rotation_loc_ids)

        query = {
            'fc_data':           fc_data,
            'mo_data':           mo_data,
            'del_data':          del_data,
            'del_by_order_month': del_by_order_month,
            'so_data':           so_data,
            'demand_del_data':   demand_del_data,
            'stock_data':        stock_data,
            'rotation':          rotation_data,
            'all_product_ids':   all_product_ids,
        }
        cfg_build = {
            'acc_formula':            acc_formula,
            'precision_source':       precision_source,
            'coverage_demand_source': coverage_demand_source,
            'coverage_unit':          coverage_unit,
            'rotation_method':        rotation_method,
            'rotation_unit':          rotation_unit,
        }
        # ── Construir filas ────────────────────────────────────────────────────
        rows = self._fc_build_rows(query, cfg_build, months, n_months, _period_days)

        # ── Totales por mes ────────────────────────────────────────────────────
        month_totals = []
        for i, ym in enumerate(months):
            mfc = sum(r['cells'][i]['forecast']  for r in rows)
            mmo = sum(r['cells'][i]['mos']       for r in rows)
            mdl = sum(r['cells'][i]['delivered'] for r in rows)
            mso = sum(r['cells'][i]['so_demand'] for r in rows)
            month_totals.append({
                'month':     ym,
                'forecast':  round(mfc, 2),
                'mos':       round(mmo, 2),
                'delivered': round(mdl, 2),
                'so_demand': round(mso, 2),
            })

        # ── KPIs globales ──────────────────────────────────────────────────────
        total_fc   = sum(r['total_forecast']  for r in rows)
        total_mos  = sum(r['total_mos']       for r in rows)
        total_del  = sum(r['total_delivered'] for r in rows)
        total_so   = sum(r['total_so_demand'] for r in rows)

        (mos_no_fc, delivered_no_fc, demand_delivered_no_fc, so_demand_no_fc) = \
            self._fc_no_fc_stats(mo_data, all_product_ids, all_product_ids_list, dt_from, dt_to)

        coverage   = round(total_mos / total_fc * 100, 1) if total_fc > 0 else 0.0
        at_risk    = sum(1 for r in rows if r['total_forecast'] > 0 and r['total_pct'] < warning_pct)
        ovr_svc         = round(total_del / total_so * 100, 1) if total_so > 0 else None
        total_demand_del = sum(r['total_demand_delivered'] for r in rows)
        ovr_demand_svc   = round(total_demand_del / total_so * 100, 1) if total_so > 0 else None
        _all_mape_sum   = sum(r['_mape_acc_sum']   for r in rows)
        _all_mape_count = sum(r['_mape_acc_count'] for r in rows)
        _all_wape_err   = sum(r['_wape_abs_err']   for r in rows)
        _all_wmape_err  = sum(r['_wmape_abs_err']  for r in rows)
        _total_fc_wmape = sum(r['total_forecast']  for r in rows if r['total_forecast'] > 0)
        total_actual = total_del if precision_source == 'delivery' else total_so
        acc_all = {
            'simple': round(total_actual / total_fc * 100, 1) if total_fc > 0 else None,
            'mape':   round(_all_mape_sum / _all_mape_count, 1) if _all_mape_count > 0 else None,
            'wape':   round(max(0.0, 100.0 - _all_wape_err / total_actual * 100), 1) if total_actual > 0 else None,
            'wmape':  round(max(0.0, 100.0 - _all_wmape_err / _total_fc_wmape * 100), 1) if _total_fc_wmape > 0 else None,
            'bias':   round((total_actual - total_fc) / total_fc * 100, 1) if total_fc > 0 else None,
        }
        ovr_acc = acc_all[acc_formula]

        # Los acumuladores por artículo (_mape_acc_sum, _mape_acc_count, _wape_abs_err,
        # _wmape_abs_err) se ENVÍAN al frontend a propósito: el widget recalcula la
        # precisión global (acc_all) sobre las filas filtradas con el mismo método
        # agregado que usa el server, para que card, columna y fila Total sean
        # consistentes entre sí y respeten el filtro/búsqueda de la tabla.

        return {
            'kpis': {
                'total_forecast':       round(total_fc,  2),
                'total_so_demand':      round(total_so,  2),
                'total_mos':            round(total_mos, 2),
                'total_delivered':      round(total_del, 2),
                'gap':                  round(total_mos - total_fc, 2),
                'mos_gap_pct':          round((total_mos - total_fc) / total_fc * 100, 1) if total_fc > 0 else None,
                'demand_gap':           round(total_so - total_fc, 2),
                'demand_gap_pct':       round((total_so - total_fc) / total_fc * 100, 1) if total_fc > 0 else None,
                'coverage_pct':         coverage,
                'at_risk':              at_risk,
                'total_products':       len(rows),
                'overall_service_rate':        ovr_svc,
                'total_demand_delivered':      round(total_demand_del, 2),
                'overall_demand_service_rate': ovr_demand_svc,
                'overall_forecast_acc': ovr_acc,
                'acc_all':              acc_all,
                'so_demand_no_fc':           so_demand_no_fc,
                'mos_no_fc':                mos_no_fc,
                'delivered_no_fc':          delivered_no_fc,
                'demand_delivered_no_fc':   demand_delivered_no_fc,
            },
            'months':        months,
            'month_totals':  month_totals,
            'rows':          rows,
            'warning_pct':   warning_pct,
            'critical_pct':  critical_pct,
            'rotation_unit':    rotation_unit,
            'rotation_method':  rotation_method,
            'rotation_n_months': round(n_months, 2),
            'acc_formula':      acc_formula,
            'precision_source': precision_source,
            'mo_states':        mo_states,
            'coverage_unit':            coverage_unit,
            'coverage_demand_source':   coverage_demand_source,
            'coverage_alerts_enabled':  coverage_alerts_enabled,
            'coverage_warn_days':       coverage_warn_days,
            'coverage_critical_days':   coverage_critical_days,
            'mo_coverage_show_pct':     mo_coverage_show_pct,
            'mo_coverage_denominator':  mo_coverage_denominator,
            'mo_coverage_color_scope':  mo_coverage_color_scope,
            'mo_mode':                  mo_mode,
        }

    @api.model
    def get_product_mos_for_forecast(self, product_id, period_from, period_to, warehouse_ids=None):
        """
        Retorna las ÓFs de un producto para el acordeón de drill-down del widget de forecast.

        Usa la misma conversión UTC que get_forecast_dashboard_data para que los
        rangos de fecha sean consistentes entre la tabla principal y el drill-down.
        Las ÓFs se filtran por fecha de fin (date_finished) dentro del período y,
        opcionalmente, por ubicación destino de los almacenes seleccionados.

        :param product_id:   int — ID del product.product a consultar.
        :param period_from:  str — mes de inicio en formato 'YYYY-MM'.
        :param period_to:    str — mes de fin en formato 'YYYY-MM' (se toma el último día del mes).
        :param warehouse_ids: list[int] | None — IDs de almacenes para filtrar por location_dest_id.
                              Si es None o vacío, no se filtra por almacén.
        :returns: list[dict] — hasta 100 registros ordenados por date_finished asc, cada uno con:
            'id', 'name', 'state', 'state_label', 'product_qty', 'qty_produced',
            'uom', 'date_start', 'date_finished'.
        """
        from datetime import date as _date, datetime
        import calendar as _cal

        d_from = _date(int(period_from[:4]), int(period_from[5:7]), 1)
        d_to_y, d_to_m = int(period_to[:4]), int(period_to[5:7])
        last_day = _date(d_to_y, d_to_m, _cal.monthrange(d_to_y, d_to_m)[1])

        # Conversión a UTC para consistencia con get_forecast_dashboard_data.
        # Sin esta conversión, para un usuario en UTC-3 el acordeón y la tabla
        # principal mostrarían conjuntos de OFs distintos en los límites de mes.
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)
        dt_from = user_tz.localize(
            datetime.combine(d_from, datetime.min.time())
        ).astimezone(pytz.utc).replace(tzinfo=None)
        dt_to = user_tz.localize(
            datetime.combine(last_day, datetime.max.time())
        ).astimezone(pytz.utc).replace(tzinfo=None)

        cfg     = self.env['mrp.reschedule.config'].get_config()
        mo_mode = (cfg.comparison_date_mode if cfg else None) or 'finish_date'

        mo_states = []
        if cfg:
            if cfg.forecast_mo_state_draft:     mo_states.append('draft')
            if cfg.forecast_mo_state_confirmed: mo_states.append('confirmed')
            if cfg.forecast_mo_state_progress:  mo_states.append('progress')
            if cfg.forecast_mo_state_to_close:  mo_states.append('to_close')
            if cfg.forecast_mo_state_done:      mo_states.append('done')
        if not mo_states:
            mo_states = ['confirmed', 'progress', 'to_close']

        dt_from_s = fields.Datetime.to_string(dt_from)
        dt_to_s   = fields.Datetime.to_string(dt_to)

        base_domain = [('product_id', '=', product_id), ('state', 'in', mo_states)] \
                      + no_subcontract_domain(self.env)

        if warehouse_ids:
            wh_recs = self.env['stock.warehouse'].browse(warehouse_ids)
            loc_ids = wh_recs.mapped('lot_stock_id').ids
            if loc_ids:
                base_domain.append(('location_dest_id', 'in', loc_ids))

        if mo_mode == 'finish_date':
            domain = base_domain + [
                ('date_finished', '>=', dt_from_s),
                ('date_finished', '<=', dt_to_s),
            ]
            order = 'date_finished asc'
        elif mo_mode == 'start_date':
            domain = base_domain + [
                ('date_start', '>=', dt_from_s),
                ('date_start', '<=', dt_to_s),
            ]
            order = 'date_start asc'
        else:
            # overlap y proportional: OFs que solapan el período
            domain = base_domain + [
                ('date_start', '<=', dt_to_s),
                '|',
                ('date_finished', '>=', dt_from_s),
                ('date_finished', '=', False),
            ]
            order = 'date_start asc'

        mos = self.env['mrp.production'].search(domain, limit=100, order=order)

        if mo_mode == 'proportional':
            mos.mapped('move_finished_ids')  # prefetch

        state_labels = {
            'draft':     'Borrador',
            'confirmed': 'Confirmada',
            'progress':  'En progreso',
            'to_close':  'Por cerrar',
            'done':      'Hecha',
            'cancel':    'Cancelada',
        }
        result = []
        for mo in mos:
            if mo_mode == 'proportional':
                mo_start = mo.date_start
                mo_end   = mo.date_finished
                if mo_start and mo_end and mo_start < mo_end:
                    total_secs   = (mo_end - mo_start).total_seconds()
                    ov_start     = max(mo_start, dt_from)
                    ov_end       = min(mo_end, dt_to)
                    overlap_secs = max(0.0, (ov_end - ov_start).total_seconds())
                    qty_period   = mo.product_qty * (overlap_secs / total_secs)
                else:
                    qty_period = mo.product_qty
                done_in_period = mo.move_finished_ids.filtered(
                    lambda m, p=mo.product_id: (
                        m.state == 'done'
                        and m.product_id == p
                        and m.date >= dt_from
                        and m.date <= dt_to
                    )
                )
                qty_produced_period = sum(
                    getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                    for m in done_in_period
                )
            else:
                qty_period          = mo.product_qty
                qty_produced_period = mo.qty_produced

            result.append({
                'id':                 mo.id,
                'name':               mo.name,
                'state':              mo.state,
                'state_label':        state_labels.get(mo.state, mo.state),
                'product_qty':        round(mo.product_qty, 2),
                'qty_produced':       round(mo.qty_produced, 2),
                'qty_period':         round(qty_period, 2),
                'qty_produced_period': round(qty_produced_period, 2),
                'uom':                mo.product_uom_id.name if mo.product_uom_id else '',
                'date_start':         mo.date_start.strftime('%Y-%m-%d')    if mo.date_start    else None,
                'date_finished':      mo.date_finished.strftime('%Y-%m-%d') if mo.date_finished else None,
            })
        return result

