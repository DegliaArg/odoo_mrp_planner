"""
Módulo: mrp_planner_dashboard_customer.py
Modelo: extensión de mrp.planner.dashboard

Análisis de comportamiento de clientes: métricas de compra, entrega, puntualidad
y frecuencia por cliente en un período configurable.

Métodos expuestos al frontend:
- get_customer_analysis_data(period_from, period_to, warehouse_ids)
- get_customer_detail(partner_id, period_from, period_to, warehouse_ids)
"""
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardCustomer(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Helpers privados ─────────────────────────────────────────────────────

    def _ca_config(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        return {
            'ontime_method':   cfg.customer_analysis_ontime_method or 'commitment_date',
            'sla_days':        cfg.customer_analysis_sla_days or 5,
            'delivery_warn':   cfg.customer_analysis_delivery_warn_pct or 80,
            'delivery_crit':   cfg.customer_analysis_delivery_crit_pct or 60,
            'ontime_warn':     cfg.customer_analysis_ontime_warn_pct or 80,
            'ontime_crit':     cfg.customer_analysis_ontime_crit_pct or 60,
            'risk_days':       cfg.customer_analysis_risk_days or 90,
            'default_period':  cfg.customer_analysis_default_period or 'quarter',
            'abc_a_pct':       cfg.customer_analysis_abc_a_pct or 20,
            'abc_b_pct':       cfg.customer_analysis_abc_b_pct or 50,
            'show_category':   cfg.enable_customer_categories,
        }

    @staticmethod
    def _to_date(val):
        if val is None:
            return None
        if hasattr(val, 'date'):
            return val.date()
        if isinstance(val, str):
            return datetime.strptime(val[:10], '%Y-%m-%d').date()
        return val

    @staticmethod
    def _freq_segment(avg_days, days_since, risk_days):
        if days_since is not None and days_since > risk_days:
            return 'en_riesgo'
        if avg_days is None:
            return 'ocasional'
        if avg_days <= 30:
            return 'frecuente'
        if avg_days <= 90:
            return 'ocasional'
        return 'inactivo'

    @staticmethod
    def _abc_segments(rows, pct_a, pct_b):
        total = sum(r['total_amount'] for r in rows)
        if total <= 0:
            return {r['partner_id']: 'C' for r in rows}
        sorted_rows = sorted(rows, key=lambda r: r['total_amount'], reverse=True)
        result = {}
        cumulative = 0.0
        for r in sorted_rows:
            cumulative += r['total_amount'] / total * 100
            if cumulative <= pct_a:
                result[r['partner_id']] = 'A'
            elif cumulative <= pct_a + pct_b:
                result[r['partner_id']] = 'B'
            else:
                result[r['partner_id']] = 'C'
        return result

    # ── Método principal ─────────────────────────────────────────────────────

    @api.model
    def get_customer_analysis_data(self, period_from, period_to, warehouse_ids=None):
        """
        Retorna todas las filas de clientes con sus métricas para el período dado.
        El front carga todo de una vez y gestiona sort/filter/paginación en memoria.

        :param period_from: str 'YYYY-MM-DD' — inicio del período.
        :param period_to:   str 'YYYY-MM-DD' — fin del período.
        :param warehouse_ids: list[int] | None — almacenes a incluir; None = todos.
        :returns: dict con claves 'rows' (list) y 'config' (dict de umbrales).
        """
        cfg = self._ca_config()
        today = fields.Date.today()

        d_from_str = period_from + ' 00:00:00'
        d_to_str   = period_to   + ' 23:59:59'
        d_from = datetime.strptime(period_from, '%Y-%m-%d')
        d_to   = datetime.strptime(period_to,   '%Y-%m-%d')
        wh_domain = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []

        # ── 1. Órdenes de venta confirmadas en el período ────────────────────
        so_domain = [
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', d_from_str),
            ('date_order', '<=', d_to_str),
        ] + wh_domain
        orders = self.env['sale.order'].search(so_domain)
        _logger.info('[CustomerAnalysis] period %s – %s → %d orders', period_from, period_to, len(orders))
        if not orders:
            return {'rows': [], 'kpis': {'total_customers': 0, 'avg_ticket': 0, 'avg_delivery_pct': None, 'avg_ontime_pct': None, 'avg_days_between': None}, 'config': cfg}

        so_data = orders.read([
            'id', 'name', 'partner_id', 'date_order',
            'amount_untaxed', 'commitment_date', 'user_id', 'state',
        ])

        # ── 2. Líneas: qty pedida, entregada y monto por orden ───────────────
        sol_groups = self.env['sale.order.line'].read_group(
            [('order_id', 'in', orders.ids)],
            ['order_id', 'product_uom_qty:sum', 'qty_delivered:sum'],
            ['order_id'],
        )
        sol_qty_by_order = {
            g['order_id'][0]: {
                'ordered':   g['product_uom_qty'] or 0.0,
                'delivered': g['qty_delivered']   or 0.0,
            }
            for g in sol_groups
        }

        # Top producto y familia: necesitamos granularidad por (partner, producto)
        sol_detail = self.env['sale.order.line'].read_group(
            [('order_id', 'in', orders.ids)],
            ['order_id', 'product_id', 'price_subtotal:sum'],
            ['order_id', 'product_id'],
            lazy=False,
        )
        order_to_partner = {s['id']: s['partner_id'][0] for s in so_data}

        prod_ids = list({g['product_id'][0] for g in sol_detail if g.get('product_id')})
        prod_info_list = self.env['product.product'].browse(prod_ids).read(
            ['id', 'product_tmpl_id', 'categ_id']
        )
        prod_info = {p['id']: p for p in prod_info_list}

        partner_prod  = defaultdict(lambda: defaultdict(float))  # pid → {tmpl_name: amt}
        partner_fam   = defaultdict(lambda: defaultdict(float))  # pid → {categ_name: amt}

        for g in sol_detail:
            if not g.get('product_id'):
                continue
            oid = g['order_id'][0]
            pid = order_to_partner.get(oid)
            if not pid:
                continue
            pi = prod_info.get(g['product_id'][0], {})
            tmpl_name  = (pi.get('product_tmpl_id') or (0, ''))[1]
            categ_name = (pi.get('categ_id')        or (0, ''))[1]
            amt = g.get('price_subtotal') or 0.0
            if tmpl_name:
                partner_prod[pid][tmpl_name] += amt
            if categ_name:
                partner_fam[pid][categ_name] += amt

        # ── 3. Pickings de salida para cálculo de puntualidad ────────────────
        pickings = self.env['stock.picking'].search([
            ('sale_id', 'in', orders.ids),
            ('state', '=', 'done'),
            ('picking_type_code', '=', 'outgoing'),
        ]).read(['id', 'sale_id', 'date_done', 'scheduled_date'])
        pick_by_so = defaultdict(list)
        for p in pickings:
            pick_by_so[p['sale_id'][0]].append(p)

        so_commitment = {s['id']: s.get('commitment_date') for s in so_data}
        so_date_order = {s['id']: s['date_order']          for s in so_data}

        # ── 4. Período anterior para tendencia ───────────────────────────────
        duration_days = max(1, (d_to - d_from).days)
        d_from_prev   = d_from - timedelta(days=duration_days + 1)
        d_to_prev     = d_from - timedelta(days=1)
        prev_groups   = self.env['sale.order'].read_group(
            [('state', 'in', ['sale', 'done']),
             ('date_order', '>=', d_from_prev),
             ('date_order', '<=', d_to_prev)] + wh_domain,
            ['partner_id', 'amount_untaxed:sum'],
            ['partner_id'],
        )
        prev_amount = {g['partner_id'][0]: (g['amount_untaxed'] or 0.0) for g in prev_groups}

        # ── 5. Agrupar SOs por partner ───────────────────────────────────────
        partner_sos = defaultdict(list)
        for s in so_data:
            partner_sos[s['partner_id'][0]].append(s)

        # Info de partners (bulk)
        partner_ids = list(partner_sos.keys())
        partners_read = self.env['res.partner'].browse(partner_ids).read(
            ['id', 'name', 'x_customer_category', 'country_id', 'state_id']
        )
        partner_info = {p['id']: p for p in partners_read}

        # ── 6. Construir filas ───────────────────────────────────────────────
        ontime_method = cfg['ontime_method']
        sla_days      = cfg['sla_days']
        risk_days     = cfg['risk_days']
        rows = []

        for pid, sos in partner_sos.items():
            pinfo       = partner_info.get(pid, {})
            order_count = len(sos)
            dates       = sorted(self._to_date(s['date_order']) for s in sos)
            last_date   = dates[-1]
            days_since  = (today - last_date).days

            if len(dates) > 1:
                gaps            = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
                avg_days_between = round(sum(gaps) / len(gaps), 1)
            else:
                avg_days_between = None

            total_amount  = sum(s['amount_untaxed'] or 0.0 for s in sos)
            total_ordered = sum(sol_qty_by_order.get(s['id'], {}).get('ordered',   0.0) for s in sos)
            total_deliv   = sum(sol_qty_by_order.get(s['id'], {}).get('delivered', 0.0) for s in sos)
            delivery_pct  = round(total_deliv / total_ordered * 100, 1) if total_ordered > 0 else None

            # Puntualidad
            ot_total = ot_ok = 0
            for s in sos:
                for p in pick_by_so.get(s['id'], []):
                    if not p.get('date_done'):
                        continue
                    date_done = self._to_date(p['date_done'])
                    if ontime_method == 'commitment_date':
                        raw = so_commitment.get(s['id'])
                        if not raw:
                            continue
                        deadline = self._to_date(raw)
                    elif ontime_method == 'scheduled_date':
                        raw = p.get('scheduled_date')
                        if not raw:
                            continue
                        deadline = self._to_date(raw)
                    else:  # sla_days
                        deadline = self._to_date(so_date_order[s['id']]) + timedelta(days=sla_days)
                    ot_total += 1
                    if date_done <= deadline:
                        ot_ok += 1
            ontime_pct = round(ot_ok / ot_total * 100, 1) if ot_total > 0 else None

            prods      = partner_prod.get(pid, {})
            fams       = partner_fam.get(pid, {})
            top_product = max(prods, key=prods.get) if prods else ''
            top_family  = max(fams,  key=fams.get)  if fams  else ''

            prev_amt  = prev_amount.get(pid, 0.0)
            trend_pct = round((total_amount - prev_amt) / prev_amt * 100, 1) if prev_amt > 0 else None

            sp_counts = defaultdict(int)
            for s in sos:
                if s.get('user_id'):
                    sp_counts[s['user_id'][1]] += 1
            salesperson = max(sp_counts, key=sp_counts.get) if sp_counts else ''

            rows.append({
                'partner_id':        pid,
                'partner_name':      pinfo.get('name', ''),
                'customer_category': pinfo.get('x_customer_category') or '',
                'salesperson':       salesperson,
                'country':           (pinfo.get('country_id')  or (0, ''))[1],
                'province':          (pinfo.get('state_id')    or (0, ''))[1],
                'order_count':       order_count,
                'total_amount':      round(total_amount, 2),
                'avg_ticket':        round(total_amount / order_count, 2) if order_count else 0.0,
                'delivery_pct':      delivery_pct,
                'ontime_pct':        ontime_pct,
                'avg_days_between':  avg_days_between,
                'days_since_last':   days_since,
                'last_order_date':   last_date.isoformat(),
                'distinct_products': len(prods),
                'top_product':       top_product,
                'top_family':        top_family,
                'trend_pct':         trend_pct,
                'abc_segment':       '',   # se asigna abajo
                'frequency_segment': self._freq_segment(avg_days_between, days_since, risk_days),
            })

        abc_map = self._abc_segments(rows, cfg['abc_a_pct'], cfg['abc_b_pct'])
        for row in rows:
            row['abc_segment'] = abc_map.get(row['partner_id'], 'C')

        # KPIs globales
        total_customers  = len(rows)
        avg_ticket_global = round(
            sum(r['total_amount'] for r in rows) / total_customers, 2
        ) if total_customers else 0.0
        delivery_vals = [r['delivery_pct'] for r in rows if r['delivery_pct'] is not None]
        avg_delivery  = round(sum(delivery_vals) / len(delivery_vals), 1) if delivery_vals else None
        ontime_vals   = [r['ontime_pct'] for r in rows if r['ontime_pct'] is not None]
        avg_ontime    = round(sum(ontime_vals) / len(ontime_vals), 1) if ontime_vals else None
        freq_vals     = [r['avg_days_between'] for r in rows if r['avg_days_between'] is not None]
        avg_freq      = round(sum(freq_vals) / len(freq_vals), 1) if freq_vals else None

        return {
            'rows': rows,
            'kpis': {
                'total_customers':  total_customers,
                'avg_ticket':       avg_ticket_global,
                'avg_delivery_pct': avg_delivery,
                'avg_ontime_pct':   avg_ontime,
                'avg_days_between': avg_freq,
            },
            'config': cfg,
        }

    # ── Detalle de un cliente (panel lateral) ────────────────────────────────

    @api.model
    def get_customer_detail(self, partner_id, period_from, period_to, warehouse_ids=None):
        """
        Retorna datos detallados de un cliente para el panel lateral:
        evolución mensual, mix de familias y lista de OVs.

        :param partner_id:  int — ID del partner.
        :param period_from: str 'YYYY-MM-DD'.
        :param period_to:   str 'YYYY-MM-DD'.
        :param warehouse_ids: list[int] | None.
        :returns: dict con claves 'partner_name', 'monthly_data', 'family_mix', 'orders'.
        """
        d_from_str = period_from + ' 00:00:00'
        d_to_str   = period_to   + ' 23:59:59'
        wh_domain = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []

        orders = self.env['sale.order'].search([
            ('partner_id', '=', partner_id),
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', d_from_str),
            ('date_order', '<=', d_to_str),
        ] + wh_domain)

        partner = self.env['res.partner'].browse(partner_id)

        if not orders:
            return {
                'partner_name': partner.name,
                'monthly_data': [],
                'family_mix':   [],
                'orders':       [],
            }

        so_data   = orders.read(['id', 'name', 'date_order', 'amount_untaxed', 'state'])
        lines     = self.env['sale.order.line'].search([('order_id', 'in', orders.ids)])
        lines_data = lines.read(['order_id', 'product_id', 'product_uom_qty', 'qty_delivered', 'price_subtotal'])

        prod_ids  = list({l['product_id'][0] for l in lines_data if l.get('product_id')})
        prods     = self.env['product.product'].browse(prod_ids).read(['id', 'categ_id'])
        categ_by_prod = {p['id']: (p.get('categ_id') or (0, 'Sin familia'))[1] for p in prods}

        sol_by_order = defaultdict(list)
        for l in lines_data:
            sol_by_order[l['order_id'][0]].append(l)

        # Evolución mensual
        monthly = defaultdict(lambda: {'amount': 0.0, 'orders': 0, 'qty_ordered': 0.0, 'qty_delivered': 0.0})
        for s in so_data:
            mk = str(s['date_order'])[:7]
            monthly[mk]['amount']  += s['amount_untaxed'] or 0.0
            monthly[mk]['orders']  += 1
            for l in sol_by_order.get(s['id'], []):
                monthly[mk]['qty_ordered']   += l['product_uom_qty'] or 0.0
                monthly[mk]['qty_delivered'] += l['qty_delivered']   or 0.0

        monthly_data = []
        for mk in sorted(monthly.keys()):
            m  = monthly[mk]
            dp = round(m['qty_delivered'] / m['qty_ordered'] * 100, 1) if m['qty_ordered'] > 0 else None
            monthly_data.append({
                'month':        mk,
                'amount':       round(m['amount'], 2),
                'orders':       m['orders'],
                'delivery_pct': dp,
            })

        # Mix de familias
        fam_amounts = defaultdict(float)
        total_fam   = 0.0
        for l in lines_data:
            if not l.get('product_id'):
                continue
            categ = categ_by_prod.get(l['product_id'][0], 'Sin familia')
            amt   = l['price_subtotal'] or 0.0
            fam_amounts[categ] += amt
            total_fam          += amt

        family_mix = sorted([
            {
                'name':   k,
                'amount': round(v, 2),
                'pct':    round(v / total_fam * 100, 1) if total_fam else 0.0,
            }
            for k, v in fam_amounts.items()
        ], key=lambda x: x['amount'], reverse=True)[:10]

        # Lista de OVs
        order_list = []
        for s in sorted(so_data, key=lambda x: x['date_order'], reverse=True):
            sols      = sol_by_order.get(s['id'], [])
            ord_qty   = sum(l['product_uom_qty'] or 0 for l in sols)
            del_qty   = sum(l['qty_delivered']   or 0 for l in sols)
            dp        = round(del_qty / ord_qty * 100, 1) if ord_qty > 0 else None
            state_map = {'sale': 'Confirmado', 'done': 'Hecho', 'cancel': 'Cancelado', 'draft': 'Borrador'}
            order_list.append({
                'name':         s['name'],
                'date':         str(s['date_order'])[:10],
                'amount':       round(s['amount_untaxed'] or 0.0, 2),
                'delivery_pct': dp,
                'state':        state_map.get(s['state'], s['state']),
                'order_id':     s['id'],
            })

        return {
            'partner_name': partner.name,
            'monthly_data': monthly_data,
            'family_mix':   family_mix,
            'orders':       order_list,
        }
