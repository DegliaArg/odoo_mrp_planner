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
from datetime import datetime, date

from odoo import models, api, _

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
    def action_open_unmet_lines(self, period_from, period_to, warehouse_ids=None,
                                only_pending=True):
        """Drill-down de las cards: abre la lista de líneas de pedido del período.

        :param only_pending: si True, solo las líneas con backlog (pedido >
            entregado); si False, todas las líneas del período.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_sales_read',
                                   'odoo_mrp_planner.group_sales')
        d_from_str = period_from + ' 00:00:00'
        d_to_str   = period_to   + ' 23:59:59'
        try:
            cfg = self._ca_config()
        except Exception:
            cfg = {}
        exclude_services = bool(cfg.get('exclude_services'))

        allowed = self._get_wh_domains().allowed_ids
        if allowed is not None:
            allowed_set = set(allowed)
            warehouse_ids = [w for w in (warehouse_ids or []) if w in allowed_set] or allowed
            if not warehouse_ids:
                warehouse_ids = [-1]
        wh_domain  = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []
        company_id = self.env.company.id

        orders = self.env['sale.order'].sudo().search([
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', d_from_str),
            ('date_order', '<=', d_to_str),
        ] + wh_domain + [('company_id', '=', company_id)])
        svc_dom = [('product_id.type', '!=', 'service')] if exclude_services else []
        lines = self.env['sale.order.line'].sudo().search_read(
            [('order_id', 'in', orders.ids), ('product_id', '!=', False)] + svc_dom,
            ['id', 'product_uom_qty', 'qty_delivered'])
        if only_pending:
            ids = [l['id'] for l in lines
                   if (l['product_uom_qty'] or 0.0) - (l['qty_delivered'] or 0.0) > 1e-6]
        else:
            ids = [l['id'] for l in lines]

        return {
            'type': 'ir.actions.act_window',
            'name': _('Demanda insatisfecha — líneas') if only_pending else _('Líneas del período'),
            'res_model': 'sale.order.line',
            'domain': [('id', 'in', ids)],
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
            d_from_str = period_from + ' 00:00:00'
            d_to_str   = period_to   + ' 23:59:59'
            # Validación de formato (coherente con el análisis de clientes).
            datetime.strptime(period_from, '%Y-%m-%d')
            datetime.strptime(period_to,   '%Y-%m-%d')

            allowed = self._get_wh_domains().allowed_ids
            if allowed is not None:
                allowed_set = set(allowed)
                warehouse_ids = [w for w in (warehouse_ids or []) if w in allowed_set] or allowed
                if not warehouse_ids:
                    return _empty()
            wh_domain  = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []
            company_id = self.env.company.id

            # ── 1. Pedidos confirmados del período ───────────────────────────
            # sudo(): usuario del panel no tiene acceso directo a sale.order.
            orders = self.env['sale.order'].sudo().search([
                ('state', 'in', ['sale', 'done']),
                ('date_order', '>=', d_from_str),
                ('date_order', '<=', d_to_str),
            ] + wh_domain + [('company_id', '=', company_id)])
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
            svc_dom = [('product_id.type', '!=', 'service')] if exclude_services else []
            lines = self.env['sale.order.line'].sudo().search_read(
                [('order_id', 'in', orders.ids), ('product_id', '!=', False)] + svc_dom,
                ['order_id', 'product_id', 'product_uom_qty', 'qty_delivered', 'price_subtotal'],
            )
            if not lines:
                return _empty()

            prod_ids = list({l['product_id'][0] for l in lines})
            prod_info = {
                p['id']: p
                for p in self.env['product.product'].sudo().browse(prod_ids).read(
                    ['id', 'display_name', 'categ_id', 'lst_price', 'product_tmpl_id'])
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
            def _new(key, name, category=''):
                return {'key': key, 'name': name, 'category': category,
                        'qty_ordered': 0.0, 'qty_delivered': 0.0,
                        'unmet_qty': 0.0, 'unmet_amount': 0.0,
                        '_orders': set(), '_cross': set(),
                        '_age_num': 0.0, '_age_den': 0.0, '_age_oldest': 0}
            agg = {}
            all_unmet_orders = set()

            for l in lines:
                pid       = l['product_id'][0]
                pi        = prod_info.get(pid, {})
                oid       = l['order_id'][0]
                ordered   = l['product_uom_qty'] or 0.0
                delivered = l['qty_delivered']   or 0.0
                unmet     = ordered - delivered
                if unmet < 0:
                    unmet = 0.0
                if use_pxq:
                    unit = pi.get('lst_price') or 0.0
                else:
                    unit = (l['price_subtotal'] or 0.0) / ordered if ordered else 0.0
                unmet_amt = unmet * unit

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
                    d = _new(key, name, category)
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

            # ── 4. Filas (solo entidades con pendiente) ──────────────────────
            rows = []
            for d in agg.values():
                if d['unmet_qty'] <= 0:
                    continue
                ordered = d['qty_ordered']
                rows.append({
                    'key':             d['key'],
                    'name':            d['name'] or '(sin nombre)',
                    'category':        d['category'] or '',
                    'qty_ordered':     round(ordered, 1),
                    'qty_delivered':   round(d['qty_delivered'], 1),
                    'unmet_qty':       round(d['unmet_qty'], 1),
                    'unmet_amount':    round(d['unmet_amount'], 2),
                    'fulfillment_pct': round(d['qty_delivered'] / ordered * 100, 1) if ordered > 0 else None,
                    'unmet_pct':       round(d['unmet_qty'] / ordered * 100, 1) if ordered > 0 else None,
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

            # ── 5. KPIs globales ─────────────────────────────────────────────
            # Backlog (pendiente): sobre las filas; el front lo recalcula al filtrar
            # la tabla. Demanda/entregado/cumplimiento: TOTALES del período, con la
            # misma fuente que el panel de Ventas → Forecast ("Demanda real" y
            # "Cumplimiento de demanda"), independientes de la dimensión elegida
            # (cliente/producto/familia) y del backlog. Así los cards no bailan al
            # cambiar de dimensión y coinciden siempre entre paneles.
            tot_unmet_qty = sum(r['unmet_qty']    for r in rows)
            tot_unmet_amt = sum(r['unmet_amount'] for r in rows)
            so_data, demand_del_data = self._so_demand_delivered_by_product(period_from, period_to)
            tot_ordered   = sum(q for pd in so_data.values()         for q in pd.values())
            tot_delivered = sum(q for pd in demand_del_data.values() for q in pd.values())
            kpis = {
                'total_unmet_qty':    round(tot_unmet_qty, 1),
                'total_unmet_amount': round(tot_unmet_amt, 2),
                'total_ordered':      round(tot_ordered, 1),
                'total_delivered':    round(tot_delivered, 1),
                'fulfillment_pct':    round(tot_delivered / tot_ordered * 100, 1) if tot_ordered > 0 else None,
                'total_rows':         len(rows),
                'affected_orders':    len(all_unmet_orders),
            }
            return {'rows': rows, 'kpis': kpis, 'config': cfg, 'dimension': dimension}

        except Exception as e:
            _logger.error('[UnmetDemand] error: %s', e, exc_info=True)
            return _empty()
