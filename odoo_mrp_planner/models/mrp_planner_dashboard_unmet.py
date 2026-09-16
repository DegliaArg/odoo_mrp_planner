# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_unmet.py
Modelo: extensión de mrp.planner.dashboard

Análisis de demanda insatisfecha: de los pedidos confirmados en el período,
cuánto se pidió vs se entregó y la brecha pendiente (backlog = pedido − entregado
a la fecha), valuada a precio unitario. El resultado se agrega por una dimensión
conmutable: cliente, producto o familia (categoría de producto).

Comparte la base del análisis de clientes (mismos estados de pedido, filtro de
empresa/almacén, exclusión de servicios y valorización PxQ/Real).

Relacionado con:
- mrp.planner.dashboard: clase base que este mixin extiende con _inherit.
- mrp_planner_dashboard_customer: comparte _ca_config() (config de valorización
  y exclusión de servicios).
- sale.order / sale.order.line: fuente de la demanda y las entregas.
"""
import logging
import pytz
from datetime import datetime, date, timedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardUnmet(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    @api.model
    def action_open_unmet_demand(self):
        """Abre el panel de análisis de demanda insatisfecha."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Análisis de demanda insatisfecha'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_unmet_demand_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def _unmet_period_bounds(self, period_from, period_to):
        """(dt_from, dt_to) en UTC naive para el período, usando la zona del usuario
        — igual que el panel de Forecast, para que los cortes por fecha coincidan."""
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)
        d_from = datetime.strptime(period_from, '%Y-%m-%d').date()
        d_to   = datetime.strptime(period_to,   '%Y-%m-%d').date()
        dt_from = user_tz.localize(datetime.combine(d_from, datetime.min.time())).astimezone(pytz.utc).replace(tzinfo=None)
        dt_to   = user_tz.localize(datetime.combine(d_to,   datetime.max.time())).astimezone(pytz.utc).replace(tzinfo=None)
        return dt_from, dt_to

    @api.model
    def _unmet_line_domain(self, period_from, period_to):
        """Dominio de sale.order.line del período, IDÉNTICO a la 'Demanda real' del
        panel de Forecast: pedidos confirmados (sale/done), producto vendible
        (sale_ok), exclusión de servicios según config, a nivel compañía. Así la
        demanda/entregado/pendiente de este panel coinciden con el Forecast."""
        dt_from, dt_to = self._unmet_period_bounds(period_from, period_to)
        try:
            cfg = self._ca_config()
        except Exception:
            cfg = {}
        svc_dom = [('product_id.type', '!=', 'service')] if bool(cfg.get('exclude_services')) else []
        return [
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', fields.Datetime.to_string(dt_from)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(dt_to)),
            ('product_id.sale_ok', '=', True),
            ('company_id', '=', self.env.company.id),
        ] + svc_dom

    @api.model
    def action_open_unmet_lines(self, period_from, period_to, warehouse_ids=None,
                                focus='pending', group_dimension=None):
        """Drill-down de las cards: abre la lista de líneas de pedido del período,
        enfocada según la card desde la que se abre.

        :param focus: qué card lo abre, define columna visible y filtro de filas:
            - 'ordered'     → todas las líneas, columna Pedido.
            - 'delivered'   → líneas con algo entregado, columna Entregado.
            - 'pending'     → líneas con backlog (pedido > entregado), columna Pendiente.
            - 'value'       → líneas con backlog, columnas Pendiente y Valorización (real).
            - 'fulfillment' → todas las líneas, columnas Pedido y Entregado.
        :param group_dimension: si se pasa ('customer' | 'product' | 'family'),
            la lista se abre agrupada por esa dimensión (para la card de afectados).
        """
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        if focus not in ('ordered', 'delivered', 'pending', 'value', 'fulfillment'):
            focus = 'pending'

        # Agrupar por la dimensión activa (card de afectados). Clientes por casa
        # matriz (unifica sucursales, coincide con el conteo de la card) y familia
        # por categoría de producto.
        group_field = {'customer': 'commercial_partner_id',
                       'product':  'product_id',
                       'family':   'product_categ_id'}.get(group_dimension)

        # Mismo dominio que las cards (y que el Forecast), sin sudo → el "Ver" suma
        # exactamente lo mismo que la card (ambos respetan las reglas del usuario).
        read_fields = ['id', 'product_uom_qty', 'qty_delivered']
        if group_field:
            read_fields.append(group_field)
        lines = self.env['sale.order.line'].search_read(
            self._unmet_line_domain(period_from, period_to), read_fields)

        def _ordered(l):   return l['product_uom_qty'] or 0.0
        # Entregado topeado en 0 (devoluciones no cuentan), igual que el panel.
        def _delivered(l): return max(0.0, l['qty_delivered'] or 0.0)
        def _gkey(l):      return (l[group_field][0] if l[group_field] else False) if group_field else None

        # Drill de afectados (agrupado): limitar a entidades con pendiente NETO > 0,
        # mismo criterio que la card, para que el conteo de grupos coincida (p. ej.
        # excluye productos con una línea faltante compensada por sobre-entrega).
        allowed_keys = None
        if group_field:
            net = {}
            for l in lines:
                k = _gkey(l)
                a = net.setdefault(k, [0.0, 0.0])
                a[0] += _ordered(l); a[1] += _delivered(l)
            allowed_keys = {k for k, (o, d) in net.items() if o - d > 1e-6}

        def _in_scope(l):
            return allowed_keys is None or _gkey(l) in allowed_keys

        if focus in ('pending', 'value'):
            ids = [l['id'] for l in lines if _ordered(l) - _delivered(l) > 1e-6 and _in_scope(l)]
        elif focus == 'delivered':
            ids = [l['id'] for l in lines if _delivered(l) > 1e-6 and _in_scope(l)]
        else:  # ordered / fulfillment
            ids = [l['id'] for l in lines if _in_scope(l)]

        titles = {
            'ordered':     _('Demanda del período — líneas'),
            'delivered':   _('Entregado del período — líneas'),
            'pending':     _('Demanda insatisfecha — líneas'),
            'value':       _('Valorización del pendiente — líneas'),
            'fulfillment': _('Cumplimiento del período — líneas'),
        }
        ctx = {
            'unmet_show_ordered':   focus in ('ordered', 'fulfillment'),
            'unmet_show_delivered': focus in ('delivered', 'fulfillment'),
            'unmet_show_pending':   focus in ('pending', 'value'),
            'unmet_show_amount':    focus == 'value',
        }
        if group_field:
            ctx['group_by'] = [group_field]

        return {
            'type': 'ir.actions.act_window',
            'name': titles.get(focus, titles['pending']),
            'res_model': 'sale.order.line',
            'domain': [('id', 'in', ids)],
            'context': ctx,
            'view_mode': 'list',
            'views': [[self.env.ref('odoo_mrp_planner.view_sale_order_line_unmet_list').id, 'list']],
            'target': 'current',
        }

    @api.model
    def get_unmet_demand_data(self, period_from, period_to, dimension='customer',
                              warehouse_ids=None, amount_method_override=None,
                              include_all=False):
        """
        Devuelve las filas de demanda insatisfecha del período, agregadas por la
        dimensión pedida, más los KPIs globales.

        :param period_from: str 'YYYY-MM-DD'.
        :param period_to:   str 'YYYY-MM-DD'.
        :param dimension:   'customer' | 'product' | 'family'.
        :param warehouse_ids: list[int] | None.
        :param amount_method_override: 'pxq' | 'real' | None (hereda de config).
        :param include_all: si True, incluye también las entidades sin pendiente
            (para el toggle "mostrar todo": el footer de la tabla cuadra con las
            cards). Si False (defecto), solo las entidades con pendiente neto.
            'total_rows' (afectados) cuenta solo las con pendiente en ambos casos.
        :returns: dict con 'rows', 'kpis', 'config', 'dimension'.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        if dimension not in ('customer', 'product', 'family'):
            dimension = 'customer'

        empty_kpis = {
            'total_unmet_qty': 0.0, 'total_unmet_amount': 0.0,
            'total_ordered': 0.0, 'total_delivered': 0.0,
            'fulfillment_pct': None, 'total_rows': 0, 'affected_orders': 0,
        }
        try:
            cfg = self._ca_config()
        except Exception as e:
            _logger.error('[UnmetDemand] _ca_config error: %s', e, exc_info=True)
            cfg = {}
        if amount_method_override in ('pxq', 'real'):
            cfg = dict(cfg, amount_method=amount_method_override)
        use_pxq          = cfg.get('amount_method', 'pxq') == 'pxq'
        exclude_services = bool(cfg.get('exclude_services'))
        age_method       = cfg.get('backlog_age_method', 'weighted')

        def _empty(reason=None):
            return {'rows': [], 'kpis': empty_kpis, 'config': cfg, 'dimension': dimension}

        try:
            # Período en UTC con la zona del usuario (mismo criterio que el Forecast).
            dt_from, dt_to = self._unmet_period_bounds(period_from, period_to)
            company_id = self.env.company.id

            # ── 1. Pedidos confirmados del período ───────────────────────────
            # A nivel compañía (sin filtro de almacén) y SIN sudo: respeta las
            # reglas de registro del usuario, igual que la "Demanda real" del
            # Forecast → los totales coinciden entre paneles.
            orders = self.env['sale.order'].search([
                ('state', 'in', ['sale', 'done']),
                ('date_order', '>=', fields.Datetime.to_string(dt_from)),
                ('date_order', '<=', fields.Datetime.to_string(dt_to)),
                ('company_id', '=', company_id),
            ])
            if not orders:
                return _empty()
            order_rows    = orders.read(['partner_id', 'date_order'])
            order_partner = {o['id']: (o['partner_id'] or (0, '')) for o in order_rows}
            order_date    = {o['id']: o['date_order'] for o in order_rows}
            today         = date.today()

            # ── Info de clientes (categoría + unificación por casa matriz) ────
            # Reusa el mismo criterio del análisis de clientes: unifica por
            # dígitos del CUIT (flag customer_unify_by_vat) y muestra la casa
            # matriz como nombre. Solo aplica a la dimensión 'customer'.
            unify = bool(cfg.get('unify_by_vat')) and dimension == 'customer'
            partner_ids = list({p[0] for p in order_partner.values() if p[0]})
            pinfo = {}
            if partner_ids:
                for p in self.env['res.partner'].sudo().browse(partner_ids).read(
                        ['id', 'display_name', 'x_customer_category', 'vat', 'parent_id']):
                    pinfo[p['id']] = p

            def _vat_digits(pid):
                vat = (pinfo.get(pid, {}) or {}).get('vat') or ''
                return ''.join(ch for ch in vat if ch.isdigit())

            # Clave de unificación por cliente y nombre de casa matriz por clave.
            cust_key_by_pid  = {}
            cust_name_by_key = {}
            cust_cat_by_key  = {}
            if dimension == 'customer':
                groups = {}
                for pid in partner_ids:
                    vk = _vat_digits(pid) if unify else ''
                    key = vk or ('p%s' % pid)
                    cust_key_by_pid[pid] = key
                    groups.setdefault(key, []).append(pid)
                for key, pids_g in groups.items():
                    # Nombre = casa matriz: un miembro raíz (sin parent) o el
                    # parent común; si no, el partner de mayor id como fallback.
                    roots = [q for q in pids_g if not (pinfo.get(q, {}) or {}).get('parent_id')]
                    if roots:
                        main = roots[0]
                        cust_name_by_key[key] = (pinfo.get(main, {}) or {}).get('display_name', '')
                    else:
                        votes = {}
                        for q in pids_g:
                            par = (pinfo.get(q, {}) or {}).get('parent_id')
                            if par:
                                votes.setdefault(par[0], [0, par[1]])
                                votes[par[0]][0] += 1
                        if votes:
                            _mid, (_n, _name) = max(votes.items(), key=lambda kv: kv[1][0])
                            cust_name_by_key[key] = _name
                        else:
                            main = pids_g[0]
                            cust_name_by_key[key] = (pinfo.get(main, {}) or {}).get('display_name', '')
                    # Categoría del cliente: la del primer miembro con categoría.
                    _cat = ''
                    for q in pids_g:
                        _c = (pinfo.get(q, {}) or {}).get('x_customer_category')
                        if _c:
                            _cat = _c
                            break
                    cust_cat_by_key[key] = _cat

            # ── 2. Líneas de pedido ──────────────────────────────────────────
            # sale_ok=True + exclusión de servicios: mismo filtro que el Forecast.
            # Sin sudo: respeta las reglas de registro del usuario (igual que el Forecast).
            svc_dom = [('product_id.type', '!=', 'service')] if exclude_services else []
            lines = self.env['sale.order.line'].search_read(
                [('order_id', 'in', orders.ids), ('product_id.sale_ok', '=', True)] + svc_dom,
                ['order_id', 'product_id', 'product_uom_qty', 'qty_delivered', 'price_subtotal'],
            )
            if not lines:
                return _empty()

            prod_ids = list({l['product_id'][0] for l in lines})
            prod_info = {
                p['id']: p
                for p in self.env['product.product'].sudo().browse(prod_ids).read(
                    ['id', 'display_name', 'default_code', 'categ_id', 'lst_price', 'product_tmpl_id'])
            }
            # Nombre HOJA de la familia (no el path completo "Todo / … / X"),
            # igual que el panel de ventas y el análisis de clientes.
            categ_ids = list({p['categ_id'][0] for p in prod_info.values() if p.get('categ_id')})
            categ_leaf = {}
            if categ_ids:
                for c in self.env['product.category'].sudo().browse(categ_ids).read(['id', 'name']):
                    categ_leaf[c['id']] = c['name']
            # Categoría de venta A–E: vive en product.template (campo computado),
            # no en la variante. Batch read tmpl → x_sale_category.
            sale_cat_by_tmpl = {}
            _tmpl_ids = list({p['product_tmpl_id'][0] for p in prod_info.values() if p.get('product_tmpl_id')})
            if _tmpl_ids:
                for t in self.env['product.template'].sudo().browse(_tmpl_ids).read(['id', 'x_sale_category']):
                    sale_cat_by_tmpl[t['id']] = t.get('x_sale_category') or ''

            # ── 3. Agregación por la dimensión elegida ───────────────────────
            def _new(key, name, category='', code=''):
                return {'key': key, 'name': name, 'category': category, 'code': code,
                        'qty_ordered': 0.0, 'qty_delivered': 0.0,
                        'unmet_qty': 0.0, 'unmet_amount': 0.0,
                        '_orders': set(), '_cross': set(),
                        '_age_num': 0.0, '_age_den': 0.0, '_age_oldest': 0,
                        '_pend_lines': []}   # [(order_date, unmet)] por línea pendiente (para entregabilidad)
            agg = {}
            all_unmet_orders = set()

            # Totales del período sobre TODAS las líneas analizadas (las mismas del
            # dominio de la Demanda real):
            #   Demanda real = Σ pedido; Cumplimiento = Σ entregado (qty_delivered,
            #   directo del pedido, sin importar la fecha de entrega).
            #   Pendiente = Demanda − Cumplimiento (derivación pura: pedí X, entregué
            #   Y, debo X−Y), no una suma independiente.
            period_ordered   = 0.0
            period_delivered = 0.0
            period_unmet_amt = 0.0

            for l in lines:
                pid       = l['product_id'][0]
                pi        = prod_info.get(pid, {})
                oid       = l['order_id'][0]
                ordered   = l['product_uom_qty'] or 0.0
                # Entregado hacia la demanda: se topea en 0 para no restar las
                # devoluciones (qty_delivered negativo). Así el cumplimiento cuenta
                # lo que salió, igual que el Forecast (movimientos de salida done).
                delivered = max(0.0, l['qty_delivered'] or 0.0)
                unmet     = ordered - delivered
                if unmet < 0:
                    unmet = 0.0
                if use_pxq:
                    unit = pi.get('lst_price') or 0.0
                else:
                    unit = (l['price_subtotal'] or 0.0) / ordered if ordered else 0.0
                unmet_amt = unmet * unit

                period_ordered   += ordered
                period_delivered += delivered
                period_unmet_amt += unmet_amt

                code = ''
                if dimension == 'customer':
                    partner = order_partner.get(oid) or (0, '')
                    pid_c = partner[0]
                    key   = cust_key_by_pid.get(pid_c, 'p%s' % pid_c)
                    name  = cust_name_by_key.get(key) or partner[1]
                    category = cust_cat_by_key.get(key, '')
                    cross = pid
                elif dimension == 'product':
                    partner = order_partner.get(oid) or (0, '')
                    key, name = pid, pi.get('display_name', '')
                    code  = pi.get('default_code') or ''   # referencia interna (eje X del gráfico)
                    _tmpl = pi.get('product_tmpl_id')
                    category  = sale_cat_by_tmpl.get(_tmpl[0], '') if _tmpl else ''
                    cross = partner[0]
                else:  # family
                    categ = pi.get('categ_id') or (0, '')
                    key, name = categ[0], categ_leaf.get(categ[0], 'Sin familia')
                    category  = ''
                    cross = pid

                d = agg.get(key)
                if d is None:
                    d = _new(key, name, category, code)
                    agg[key] = d
                # Pedido/entregado se acumulan sobre TODAS las líneas de la entidad
                # (para que el % de cumplimiento refleje su desempeño global).
                d['qty_ordered']   += ordered
                d['qty_delivered'] += delivered
                if unmet > 0:
                    d['unmet_qty']    += unmet
                    d['unmet_amount'] += unmet_amt
                    d['_orders'].add(oid)
                    d['_cross'].add(cross)
                    all_unmet_orders.add(oid)
                    # Antigüedad del backlog: días desde la confirmación del pedido.
                    _od = order_date.get(oid)
                    if _od:
                        _days = max(0, (today - self._to_date(_od)).days)
                        d['_age_num']    += unmet * _days
                        d['_age_den']    += unmet
                        if _days > d['_age_oldest']:
                            d['_age_oldest'] = _days
                        if dimension == 'product':
                            d['_pend_lines'].append((_od, unmet))

            # ── 4. Filas: desagregación del pendiente por entidad ─────────────
            # Pendiente por entidad = pedido − entregado (misma derivación que la
            # card). Así la suma de la columna Pendiente de la tabla coincide con el
            # total de la card. La valorización (unmet_amount) y la antigüedad son
            # el detalle del backlog por línea de esa entidad.
            rows = []
            n_affected = 0   # entidades con pendiente (card "afectados"), sin importar include_all
            for d in agg.values():
                ordered   = d['qty_ordered']
                delivered = d['qty_delivered']
                unmet     = ordered - delivered
                has_pending = unmet > 1e-6
                if has_pending:
                    n_affected += 1
                elif not include_all:
                    continue   # sin pendiente: se omite salvo en modo "mostrar todo"
                rows.append({
                    'key':             d['key'],
                    'name':            d['name'] or '(sin nombre)',
                    'code':            d['code'] or '',
                    'category':        d['category'] or '',
                    'qty_ordered':     round(ordered, 1),
                    'qty_delivered':   round(delivered, 1),
                    'unmet_qty':       round(unmet, 1),
                    'unmet_amount':    round(d['unmet_amount'], 2),
                    'fulfillment_pct': round(delivered / ordered * 100, 1) if ordered > 0 else None,
                    'unmet_pct':       round(unmet / ordered * 100, 1) if ordered > 0 else None,
                    'affected_orders': len(d['_orders']),
                    'cross_count':     len(d['_cross']),
                    'pending_age_weighted': round(d['_age_num'] / d['_age_den'], 1) if d['_age_den'] > 0 else None,
                    'pending_age_oldest':   d['_age_oldest'],
                    'pending_age':          (round(d['_age_num'] / d['_age_den'], 1) if d['_age_den'] > 0 else None)
                                            if age_method == 'weighted' else d['_age_oldest'],
                })

            rows.sort(key=lambda r: r['unmet_amount'], reverse=True)

            # ── 4b. Situación por fila = entregabilidad histórica (solo producto) ──
            # Por cada pedido pendiente se cuentan los días de su ventana en que el
            # stock alcanzaba para cubrirlo; la columna resume "durante X de los Y
            # días pendientes hubo stock disponible para entregar". Batch: pocas
            # consultas para todos los productos de la tabla.
            if dimension == 'product' and rows:
                pids = [r['key'] for r in rows]
                bd_map = self._stock_break_days_map(pids)
                all_dates = [od for r in rows for (od, _q) in agg[r['key']]['_pend_lines'] if od]
                curves = self._stock_curves_batch(pids, min(all_dates)) if all_dates else {}
                now_dt = fields.Datetime.now()
                for r in rows:
                    r['break_days'] = bd_map.get(r['key'])
                    xw, yw, _qs = self._coverage_days(curves.get(r['key'], []),
                                                      agg[r['key']]['_pend_lines'], now_dt)
                    r['deliv_days'] = round(xw / _qs, 1) if _qs else 0.0
                    r['pend_days']  = round(yw / _qs, 1) if _qs else 0.0
                    pct = round(xw / yw * 100, 1) if yw > 0 else None
                    r['deliv_pct'] = pct
                    if pct is None:
                        r['diagnosis'] = 'na'
                    elif pct >= 66:
                        r['diagnosis'] = 'fulfillment'
                    elif pct <= 33:
                        r['diagnosis'] = 'shortage'
                    else:
                        r['diagnosis'] = 'mixed'

            # ── 5. KPIs globales del período ─────────────────────────────────
            # Demanda real y Cumplimiento son totales FIJOS del período (Σ pedido y
            # Σ entregado sobre las mismas líneas, directo del pedido). Pendiente se
            # DERIVA de ambos (Demanda − Cumplimiento): pedí X, entregué Y, debo X−Y.
            # No dependen de la dimensión ni de los filtros de la tabla.
            kpis = {
                'total_unmet_qty':    round(period_ordered - period_delivered, 1),
                'total_unmet_amount': round(period_unmet_amt, 2),
                'total_ordered':      round(period_ordered, 1),
                'total_delivered':    round(period_delivered, 1),
                'fulfillment_pct':    round(period_delivered / period_ordered * 100, 1) if period_ordered > 0 else None,
                'total_rows':         n_affected,
                'affected_orders':    len(all_unmet_orders),
            }
            return {'rows': rows, 'kpis': kpis, 'config': cfg, 'dimension': dimension}

        except Exception as e:
            _logger.error('[UnmetDemand] error: %s', e, exc_info=True)
            return _empty()

    # ── Curva de stock histórica (para el análisis de entregabilidad) ────────────
    @api.model
    def _stock_curve_segments(self, product_id, date_from):
        """Reconstruye la curva de stock on-hand del producto (ubicaciones internas
        de la compañía) desde `date_from` hasta ahora, partiendo del stock actual y
        aplicando hacia atrás todas las entradas y salidas (capta reposiciones).

        :returns: list[(start_dt, end_dt, stock_level)] — segmentos con stock
            constante, en orden cronológico.
        """
        company_id = self.env.company.id
        now = fields.Datetime.now()
        quant_groups = self.env['stock.quant'].sudo().read_group(
            [('product_id', '=', product_id), ('location_id.usage', '=', 'internal'),
             ('company_id', '=', company_id)], ['quantity:sum'], [])
        stock_now = (quant_groups[0]['quantity'] if quant_groups else 0.0) or 0.0

        df = fields.Datetime.to_string(date_from)
        base = [('product_id', '=', product_id), ('state', '=', 'done'),
                ('date', '>=', df), ('company_id', '=', company_id)]
        ins = self.env['stock.move'].sudo().search_read(
            base + [('location_id.usage', '!=', 'internal'),
                    ('location_dest_id.usage', '=', 'internal')], ['date', 'quantity'])
        outs = self.env['stock.move'].sudo().search_read(
            base + [('location_id.usage', '=', 'internal'),
                    ('location_dest_id.usage', '!=', 'internal')], ['date', 'quantity'])
        deltas = [(m['date'], (m['quantity'] or 0.0)) for m in ins]
        deltas += [(m['date'], -(m['quantity'] or 0.0)) for m in outs]
        deltas.sort(key=lambda x: x[0])

        stock_start = stock_now - sum(d for _, d in deltas)
        segments = []
        cur_stock = stock_start
        cur_start = date_from
        for dt, delta in deltas:
            if dt > cur_start:
                segments.append((cur_start, dt, cur_stock))
            cur_stock += delta
            cur_start = dt
        if now > cur_start:
            segments.append((cur_start, now, cur_stock))
        return segments

    @api.model
    def _stock_curves_batch(self, product_ids, date_from):
        """Como _stock_curve_segments pero para muchos productos en pocos queries
        (1 read_group de stock + 2 search_read de movimientos). Devuelve
        {product_id: [(start_dt, end_dt, level), ...]}."""
        product_ids = list(product_ids)
        if not product_ids:
            return {}
        company_id = self.env.company.id
        now = fields.Datetime.now()
        stock_now = {}
        for g in self.env['stock.quant'].sudo().read_group(
                [('product_id', 'in', product_ids), ('location_id.usage', '=', 'internal'),
                 ('company_id', '=', company_id)], ['product_id', 'quantity:sum'], ['product_id']):
            stock_now[g['product_id'][0]] = g['quantity'] or 0.0

        df = fields.Datetime.to_string(date_from)
        base = [('product_id', 'in', product_ids), ('state', '=', 'done'),
                ('date', '>=', df), ('company_id', '=', company_id)]
        deltas = {pid: [] for pid in product_ids}
        for m in self.env['stock.move'].sudo().search_read(
                base + [('location_id.usage', '!=', 'internal'),
                        ('location_dest_id.usage', '=', 'internal')], ['date', 'quantity', 'product_id']):
            if m['product_id']:
                deltas.setdefault(m['product_id'][0], []).append((m['date'], m['quantity'] or 0.0))
        for m in self.env['stock.move'].sudo().search_read(
                base + [('location_id.usage', '=', 'internal'),
                        ('location_dest_id.usage', '!=', 'internal')], ['date', 'quantity', 'product_id']):
            if m['product_id']:
                deltas.setdefault(m['product_id'][0], []).append((m['date'], -(m['quantity'] or 0.0)))

        curves = {}
        for pid in product_ids:
            dl = sorted(deltas.get(pid, []), key=lambda x: x[0])
            cur = (stock_now.get(pid, 0.0)) - sum(d for _, d in dl)
            segs = []
            cur_start = date_from
            for dt, delta in dl:
                if dt > cur_start:
                    segs.append((cur_start, dt, cur))
                cur += delta
                cur_start = dt
            if now > cur_start:
                segs.append((cur_start, now, cur))
            curves[pid] = segs
        return curves

    @api.model
    def _coverage_days(self, segments, pend_lines, now):
        """Días con stock para entregar al menos una parte, ponderados por cantidad.

        Por cada pedido pendiente (fecha, cantidad), cuenta los días de su ventana
        [fecha, hoy] en que había stock > 0 (podías entregar al menos una pieza del
        pedido).

        :returns: (x, y, Σqty) — x = días-ponderados con stock; y = días-ponderados
            totales. El promedio es x/Σqty e y/Σqty; el índice es x/y.
        """
        xw = yw = qsum = 0.0
        for start, qty in pend_lines:
            if not start or qty <= 0:
                continue
            total = max(0.0, (now - start).total_seconds() / 86400.0)
            dstock = 0.0
            for s, e, lvl in segments:
                lo = max(s, start)
                hi = min(e, now)
                if hi > lo and lvl > 1e-6:
                    dstock += (hi - lo).total_seconds() / 86400.0
            xw += qty * dstock
            yw += qty * total
            qsum += qty
        return xw, yw, qsum

    # ── Análisis de entregabilidad (on-demand, al expandir un producto) ──────────
    @api.model
    def get_unmet_delivery_analysis(self, product_id, period_from, period_to):
        """Análisis de entregabilidad de un producto (on-demand al expandir su fila).

        Por cada pedido pendiente cuenta los días de su ventana en que el stock
        alcanzaba para cubrirlo (stock(t) >= cantidad del pedido). Resume "durante X
        de los Y días pendientes hubo stock disponible para entregar". Así distingue
        "tener algo" de "tener suficiente": 2 unidades de un pendiente de 68 dan 0
        días con stock (falta de stock), no ~98% como el criterio binario stock>0.

        :returns: dict con index_pct, diagnosis, days_stock, days_pending, stock_now y lines[].
        """
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        empty = {'index_pct': None, 'diagnosis': 'na', 'total_pending': 0.0,
                 'days_stock': 0.0, 'days_pending': 0.0, 'stock_now': 0.0, 'lines': []}
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return empty
        try:
            dom = self._unmet_line_domain(period_from, period_to) + [('product_id', '=', product_id)]
            sol = self.env['sale.order.line'].search_read(
                dom, ['product_uom_qty', 'qty_delivered', 'order_id'])
            pend = []
            for l in sol:
                ordered = l['product_uom_qty'] or 0.0
                delivered = max(0.0, l['qty_delivered'] or 0.0)
                unmet = ordered - delivered
                if unmet > 1e-6:
                    pend.append((l['order_id'][0], unmet))
            if not pend:
                return empty
            total_pending = sum(u for _o, u in pend)

            # Fecha de referencia por pedido: confirmación (date_order), igual que la
            # columna "Antig. pendiente" y la columna Situación, para que coincidan.
            order_ids = list({oid for oid, _q in pend})
            orders = {o['id']: o for o in self.env['sale.order'].sudo().browse(order_ids).read(['date_order', 'name'])}

            def _start_dt(oid):
                return (orders.get(oid) or {}).get('date_order')

            now = fields.Datetime.now()
            starts = [_start_dt(oid) for oid, _q in pend if _start_dt(oid)]
            if not starts:
                return empty
            segments = self._stock_curve_segments(product_id, min(starts))

            def _days_with_stock(start_dt):
                """Días entre start_dt y ahora en que hubo stock > 0 (entrega parcial)."""
                d = 0.0
                for s, e, lvl in segments:
                    lo = max(s, start_dt); hi = min(e, now)
                    if hi > lo and lvl > 1e-6:
                        d += (hi - lo).total_seconds() / 86400.0
                return d

            lines = []
            xw = yw = 0.0
            for oid, unmet in pend:
                sdt = _start_dt(oid)
                if not sdt:
                    continue
                total = max(0.0, (now - sdt).total_seconds() / 86400.0)
                dstock = _days_with_stock(sdt)
                pct = round(dstock / total * 100, 1) if total > 0 else None
                xw += unmet * dstock
                yw += unmet * total
                lines.append({
                    'order_id':   oid,
                    'order':      (orders.get(oid) or {}).get('name') or '',
                    'pending':    round(unmet, 1),
                    'days_total': round(total, 1),
                    'days_stock': round(dstock, 1),
                    'pct':        pct,
                })
            lines.sort(key=lambda r: r['pending'], reverse=True)

            index_pct = round(xw / yw * 100, 1) if yw > 0 else None
            if index_pct is None:
                diagnosis = 'na'
            elif index_pct >= 66:
                diagnosis = 'fulfillment'   # hubo stock la mayor parte del tiempo y no entregaste
            elif index_pct <= 33:
                diagnosis = 'shortage'      # casi nunca hubo stock
            else:
                diagnosis = 'mixed'

            # Serie de la curva de stock (para el mini-gráfico): puntos [ts_ms, nivel]
            # al inicio y fin de cada tramo (línea escalonada).
            _epoch = datetime(1970, 1, 1)
            def _ms(dt):
                return int((dt - _epoch).total_seconds() * 1000)
            curve = []
            for s, e, lvl in segments:
                curve.append([_ms(s), round(lvl, 1)])
                curve.append([_ms(e), round(lvl, 1)])

            return {
                'index_pct':     index_pct,
                'diagnosis':     diagnosis,
                'total_pending': round(total_pending, 1),
                'days_stock':    round(xw / total_pending, 1) if total_pending > 0 else 0.0,
                'days_pending':  round(yw / total_pending, 1) if total_pending > 0 else 0.0,
                'stock_now':     round(segments[-1][2], 1) if segments else 0.0,
                'curve':         curve,
                'lines':         lines,
            }
        except Exception as e:
            _logger.error('[UnmetDemand] delivery analysis error: %s', e, exc_info=True)
            return empty
