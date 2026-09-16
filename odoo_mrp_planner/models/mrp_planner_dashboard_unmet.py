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
from datetime import datetime, date

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Umbral (días) a partir del cual se considera "viejo" el backlog de un producto,
# usado por el diagnóstico del cruce con los días en quiebre.
BACKLOG_OLD_DAYS = 15


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

        # Mismo dominio que las cards (y que el Forecast), sin sudo → el "Ver" suma
        # exactamente lo mismo que la card (ambos respetan las reglas del usuario).
        lines = self.env['sale.order.line'].search_read(
            self._unmet_line_domain(period_from, period_to),
            ['id', 'product_uom_qty', 'qty_delivered'])

        def _ordered(l):   return l['product_uom_qty'] or 0.0
        def _delivered(l): return l['qty_delivered'] or 0.0
        if focus in ('pending', 'value'):
            ids = [l['id'] for l in lines if _ordered(l) - _delivered(l) > 1e-6]
        elif focus == 'delivered':
            ids = [l['id'] for l in lines if _delivered(l) > 1e-6]
        else:  # ordered / fulfillment
            ids = [l['id'] for l in lines]

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
        # Agrupar por la dimensión activa (card de afectados). Clientes por casa
        # matriz (unifica sucursales, coincide con el conteo de la card) y familia
        # por categoría de producto.
        group_field = {'customer': 'commercial_partner_id',
                       'product':  'product_id',
                       'family':   'product_categ_id'}.get(group_dimension)
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
    def _unmet_diagnosis(self, break_days, backlog_age):
        """Diagnóstico del cruce quiebre × backlog (solo productos):
        - 'chronic'     : en quiebre + backlog viejo (sin stock hace rato y venís fallando).
        - 'supply'      : en quiebre + backlog reciente (reponé y se limpia).
        - 'fulfillment' : sin quiebre + backlog viejo (hay stock pero no entregás).
        - 'ok'          : sin quiebre + backlog reciente.
        """
        old    = (backlog_age or 0) >= BACKLOG_OLD_DAYS
        broken = break_days is not None
        if broken and old:
            return 'chronic'
        if broken:
            return 'supply'
        if old:
            return 'fulfillment'
        return 'ok'

    @api.model
    def get_unmet_demand_data(self, period_from, period_to, dimension='customer',
                              warehouse_ids=None, amount_method_override=None):
        """
        Devuelve las filas de demanda insatisfecha del período, agregadas por la
        dimensión pedida, más los KPIs globales.

        :param period_from: str 'YYYY-MM-DD'.
        :param period_to:   str 'YYYY-MM-DD'.
        :param dimension:   'customer' | 'product' | 'family'.
        :param warehouse_ids: list[int] | None.
        :param amount_method_override: 'pxq' | 'real' | None (hereda de config).
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
                        '_age_num': 0.0, '_age_den': 0.0, '_age_oldest': 0}
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

            # ── 4. Filas: desagregación del pendiente por entidad ─────────────
            # Pendiente por entidad = pedido − entregado (misma derivación que la
            # card). Así la suma de la columna Pendiente de la tabla coincide con el
            # total de la card. La valorización (unmet_amount) y la antigüedad son
            # el detalle del backlog por línea de esa entidad.
            rows = []
            for d in agg.values():
                ordered   = d['qty_ordered']
                delivered = d['qty_delivered']
                unmet     = ordered - delivered
                if unmet <= 1e-6:
                    continue
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

            # ── 4b. Cruce con quiebre de stock (solo modo producto) ──────────
            # Días en quiebre (bajo mínimo) + diagnóstico del panorama.
            if dimension == 'product' and rows:
                bd_map = self._stock_break_days_map([r['key'] for r in rows])
                for r in rows:
                    bd = bd_map.get(r['key'])
                    r['break_days'] = bd
                    r['diagnosis']  = self._unmet_diagnosis(bd, r['pending_age'])

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
                'total_rows':         len(rows),
                'affected_orders':    len(all_unmet_orders),
            }
            return {'rows': rows, 'kpis': kpis, 'config': cfg, 'dimension': dimension}

        except Exception as e:
            _logger.error('[UnmetDemand] error: %s', e, exc_info=True)
            return _empty()
