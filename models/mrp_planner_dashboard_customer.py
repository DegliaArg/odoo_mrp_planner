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
from odoo.exceptions import AccessError
from odoo.tools.translate import _

from .const import DEFAULT_RISK_DAYS

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
            'risk_days':       cfg.customer_analysis_risk_days or DEFAULT_RISK_DAYS,
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

    # ── Método principal ─────────────────────────────────────────────────────

    @api.model
    def get_customer_analysis_data(self, period_from, period_to, warehouse_ids=None):
        """
        Retorna todas las filas de clientes con sus métricas para el período dado.
        El front carga todo de una vez y gestiona sort/filter/paginación en memoria.
        """
        empty_kpis = {
            'total_customers': 0, 'avg_ticket': 0,
            'avg_delivery_pct': None, 'avg_physical_pct': None,
            'avg_ontime_pct': None, 'avg_days_between': None,
        }
        try:
            cfg = self._ca_config()
        except Exception as e:
            _logger.error('[CustomerAnalysis] _ca_config error: %s', e, exc_info=True)
            cfg = {}

        try:
            today      = fields.Date.today()
            d_from_str = period_from + ' 00:00:00'
            d_to_str   = period_to   + ' 23:59:59'
            d_from     = datetime.strptime(period_from, '%Y-%m-%d')
            d_to       = datetime.strptime(period_to,   '%Y-%m-%d')
            allowed    = self._get_wh_domains().allowed_ids
            if allowed is not None:
                allowed_set = set(allowed)
                warehouse_ids = [w for w in (warehouse_ids or []) if w in allowed_set] or allowed
            wh_domain  = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []

            # ── 1. Órdenes confirmadas en el período ─────────────────────────
            # sudo(): usuario no tiene acceso directo a sale.order; se lee sólo el agregado para el dashboard
            orders = self.env['sale.order'].sudo().search([
                ('state', 'in', ['sale', 'done']),
                ('date_order', '>=', d_from_str),
                ('date_order', '<=', d_to_str),
            ] + wh_domain)
            _logger.info('[CustomerAnalysis] %s – %s → %d orders', period_from, period_to, len(orders))
            if not orders:
                return {'rows': [], 'kpis': empty_kpis, 'config': cfg}

            so_data = orders.read([
                'id', 'name', 'partner_id', 'date_order',
                'amount_untaxed', 'commitment_date', 'user_id', 'state',
            ])

            # ── 2. Qty pedida / entregada por orden ──────────────────────────
            # sudo(): usuario no tiene acceso directo a sale.order.line; se lee sólo el agregado para el dashboard
            sol_groups = self.env['sale.order.line'].sudo().read_group(
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

            # ── 3. Top producto / familia ────────────────────────────────────
            # sudo(): usuario no tiene acceso directo a sale.order.line; se lee sólo el agregado para el dashboard
            sol_detail = self.env['sale.order.line'].sudo().read_group(
                [('order_id', 'in', orders.ids)],
                ['order_id', 'product_id', 'price_subtotal:sum'],
                ['order_id', 'product_id'],
                lazy=False,
            )
            order_to_partner = {s['id']: s['partner_id'][0] for s in so_data}
            prod_ids = list({g['product_id'][0] for g in sol_detail if g.get('product_id')})
            prod_info = {
                p['id']: p
                # sudo(): usuario no tiene acceso directo a product.product; se lee sólo el agregado para el dashboard
                for p in self.env['product.product'].sudo().browse(prod_ids).read(
                    ['id', 'product_tmpl_id', 'categ_id']
                )
            }
            partner_prod = defaultdict(lambda: defaultdict(float))
            partner_fam  = defaultdict(lambda: defaultdict(float))
            for g in sol_detail:
                if not g.get('product_id'):
                    continue
                pid = order_to_partner.get(g['order_id'][0])
                if not pid:
                    continue
                pi = prod_info.get(g['product_id'][0], {})
                tmpl  = (pi.get('product_tmpl_id') or (0, ''))[1]
                categ = (pi.get('categ_id')        or (0, ''))[1]
                amt   = g.get('price_subtotal') or 0.0
                if tmpl:
                    partner_prod[pid][tmpl]  += amt
                if categ:
                    partner_fam[pid][categ]  += amt

            # ── 4. Pickings para puntualidad ─────────────────────────────────
            # sudo(): usuario no tiene acceso directo a stock.picking; se lee sólo el agregado para el dashboard
            pickings = self.env['stock.picking'].sudo().search([
                ('sale_id', 'in', orders.ids),
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'outgoing'),
            ]).read(['id', 'sale_id', 'date_done', 'scheduled_date'])
            pick_by_so    = defaultdict(list)
            for p in pickings:
                pick_by_so[p['sale_id'][0]].append(p)
            so_commitment = {s['id']: s.get('commitment_date') for s in so_data}
            so_date_order = {s['id']: s['date_order']          for s in so_data}

            # ── 5. Período anterior (tendencia) ──────────────────────────────
            dur           = max(1, (d_to - d_from).days)
            d_prev_from   = (d_from - timedelta(days=dur + 1)).strftime('%Y-%m-%d 00:00:00')
            d_prev_to     = (d_from - timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
            # sudo(): usuario no tiene acceso directo a sale.order; se lee sólo el agregado para el dashboard
            prev_groups   = self.env['sale.order'].sudo().read_group(
                [('state', 'in', ['sale', 'done']),
                 ('date_order', '>=', d_prev_from),
                 ('date_order', '<=', d_prev_to)] + wh_domain,
                ['partner_id', 'amount_untaxed:sum'],
                ['partner_id'],
            )
            prev_amount = {g['partner_id'][0]: (g['amount_untaxed'] or 0.0) for g in prev_groups}

            # ── 5b. Entregas físicas del período (tasa física) ────────────────
            # Salidas completadas cuya fecha de efectivización cae DENTRO del
            # período, de CUALQUIER pedido del cliente (incluso confirmado antes).
            # Se vinculan al cliente vía el pedido de venta del remito, y se
            # guarda el mes de confirmación del pedido para el desglose del tooltip.
            phys_pick_domain = [
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'outgoing'),
                ('sale_id', '!=', False),
                ('date_done', '>=', d_from_str),
                ('date_done', '<=', d_to_str),
            ]
            if warehouse_ids:
                phys_pick_domain.append(('picking_type_id.warehouse_id', 'in', warehouse_ids))
            # sudo(): usuario no tiene acceso directo a stock.picking; solo agregado para el dashboard
            phys_picks = self.env['stock.picking'].sudo().search_read(
                phys_pick_domain, ['id', 'sale_id'])
            phys_so_ids  = list({p['sale_id'][0] for p in phys_picks})
            phys_so_info = {
                s['id']: s
                for s in self.env['sale.order'].sudo().browse(phys_so_ids).read(
                    ['id', 'partner_id', 'date_order'])
            } if phys_so_ids else {}
            phys_qty_by_pick = {}
            if phys_picks:
                for g in self.env['stock.move.line'].sudo().read_group(
                    [('picking_id', 'in', [p['id'] for p in phys_picks]), ('state', '=', 'done')],
                    ['picking_id', 'quantity:sum'], ['picking_id'],
                ):
                    if g.get('picking_id'):
                        phys_qty_by_pick[g['picking_id'][0]] = g['quantity'] or 0.0
            phys_by_partner       = defaultdict(float)
            phys_month_by_partner = defaultdict(lambda: defaultdict(float))
            for p in phys_picks:
                so = phys_so_info.get(p['sale_id'][0])
                if not so:
                    continue
                _ppid = so['partner_id'][0]
                _pqty = phys_qty_by_pick.get(p['id'], 0.0)
                if _pqty <= 0:
                    continue
                phys_by_partner[_ppid] += _pqty
                phys_month_by_partner[_ppid][str(so['date_order'])[:7]] += _pqty

            # ── 6. Agrupar por partner ────────────────────────────────────────
            partner_sos = defaultdict(list)
            for s in so_data:
                partner_sos[s['partner_id'][0]].append(s)

            partner_info = {
                p['id']: p
                # sudo(): usuario no tiene acceso directo a res.partner; se lee sólo el agregado para el dashboard
                for p in self.env['res.partner'].sudo().browse(list(partner_sos.keys())).read(
                    ['id', 'name', 'display_name', 'x_customer_category', 'country_id', 'state_id', 'category_id']
                )
            }

            # Leer nombre y color de la primera etiqueta de cada partner
            all_tag_ids = {
                p.get('category_id', [None])[0]
                for p in partner_info.values()
                if p.get('category_id')
            }
            tag_data = {}
            if all_tag_ids:
                for t in self.env['res.partner.category'].sudo().browse(list(all_tag_ids)).read(['id', 'name', 'color']):
                    tag_data[t['id']] = {'name': t['name'], 'color': t.get('color') or 0}

            # ── 7. Construir filas ────────────────────────────────────────────
            ontime_method = cfg.get('ontime_method', 'commitment_date')
            sla_days      = cfg.get('sla_days', 5)
            risk_days     = cfg.get('risk_days', 90)
            rows = []

            for pid, sos in partner_sos.items():
                pinfo       = partner_info.get(pid, {})
                first_tag_id = (pinfo.get('category_id') or [None])[0]
                tag          = tag_data.get(first_tag_id, {})
                order_count = len(sos)
                dates       = sorted(self._to_date(s['date_order']) for s in sos)
                last_date   = dates[-1]
                days_since  = (today - last_date).days

                gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
                avg_days_between = round(sum(gaps) / len(gaps), 1) if gaps else None

                total_amount  = sum(s['amount_untaxed'] or 0.0 for s in sos)
                total_ordered = sum(sol_qty_by_order.get(s['id'], {}).get('ordered',   0.0) for s in sos)
                total_deliv   = sum(sol_qty_by_order.get(s['id'], {}).get('delivered', 0.0) for s in sos)
                delivery_pct  = round(total_deliv / total_ordered * 100, 1) if total_ordered > 0 else None
                # Tasa física: despachado dentro del período (de cualquier pedido)
                # ÷ pedido en el período. Puede superar 100% si se despachan pedidos viejos.
                phys_qty      = phys_by_partner.get(pid, 0.0)
                physical_pct  = round(phys_qty / total_ordered * 100, 1) if total_ordered > 0 else None

                ot_total = ot_ok = 0
                for s in sos:
                    for pk in pick_by_so.get(s['id'], []):
                        if not pk.get('date_done'):
                            continue
                        date_done = self._to_date(pk['date_done'])
                        if ontime_method == 'commitment_date':
                            raw = so_commitment.get(s['id'])
                            if not raw:
                                continue
                            deadline = self._to_date(raw)
                        elif ontime_method == 'scheduled_date':
                            raw = pk.get('scheduled_date')
                            if not raw:
                                continue
                            deadline = self._to_date(raw)
                        else:
                            deadline = self._to_date(so_date_order[s['id']]) + timedelta(days=sla_days)
                        ot_total += 1
                        if date_done <= deadline:
                            ot_ok += 1
                ontime_pct = round(ot_ok / ot_total * 100, 1) if ot_total > 0 else None

                prods      = partner_prod.get(pid, {})
                fams       = partner_fam.get(pid, {})
                prev_amt   = prev_amount.get(pid, 0.0)
                sp_counts  = defaultdict(int)
                for s in sos:
                    if s.get('user_id'):
                        sp_counts[s['user_id'][1]] += 1

                rows.append({
                    'partner_id':        pid,
                    'partner_name':      pinfo.get('display_name') or pinfo.get('name', ''),
                    'customer_category': pinfo.get('x_customer_category') or '',
                    'salesperson':       max(sp_counts, key=sp_counts.get) if sp_counts else '',
                    'country':           (pinfo.get('country_id')  or (0, ''))[1],
                    'province':          (pinfo.get('state_id')    or (0, ''))[1],
                    'order_count':       order_count,
                    'total_amount':      round(total_amount, 2),
                    'avg_ticket':        round(total_amount / order_count, 2) if order_count else 0.0,
                    'qty_ordered':       round(total_ordered, 1),
                    'qty_delivered':     round(total_deliv, 1),
                    'delivery_pct':      delivery_pct,
                    'qty_delivered_phys': round(phys_qty, 1),
                    'physical_pct':      physical_pct,
                    'phys_by_order_month': {k: round(v, 1) for k, v in sorted(phys_month_by_partner.get(pid, {}).items())},
                    'ontime_ok':         ot_ok,
                    'ontime_total':      ot_total,
                    'ontime_pct':        ontime_pct,
                    'avg_days_between':  avg_days_between,
                    'days_since_last':   days_since,
                    'last_order_date':   last_date.isoformat(),
                    'distinct_products': len(prods),
                    'top_product':       max(prods, key=prods.get) if prods else '',
                    'top_family':        max(fams,  key=fams.get)  if fams  else '',
                    'trend_pct':         round((total_amount - prev_amt) / prev_amt * 100, 1) if prev_amt > 0 else None,
                    'prev_amount':       round(prev_amt, 2),
                    'abc_segment':       '',  # se calcula abajo: ABC del período (Pareto sobre el importe del rango)
                    'frequency_segment': self._freq_segment(avg_days_between, days_since, risk_days),
                    'partner_tag':       tag.get('name', '') or '',
                    'partner_tag_color': tag.get('color', 0),
                })

            # ── ABC del período: clasificación al vuelo sobre el importe del rango ──
            # Independiente de la categoría permanente del contacto. Se ordena por
            # facturación del período y se acumula la participación con acumulado
            # EXCLUSIVO (se evalúa antes de sumar al propio cliente), de modo que el
            # cliente de mayor facturación siempre queda en A. Cortes: A ≤ a_pct%,
            # B ≤ (a_pct + b_pct)%, C = resto (configurables en Ajustes).
            abc_a_cut  = (cfg.get('abc_a_pct') or 20) / 100.0
            abc_b_cut  = abc_a_cut + (cfg.get('abc_b_pct') or 50) / 100.0
            _abc_total = sum(r['total_amount'] for r in rows)
            _abc_cum   = 0.0
            for r in sorted(rows, key=lambda x: x['total_amount'], reverse=True):
                if _abc_total <= 0 or r['total_amount'] <= 0:
                    r['abc_segment'] = 'C'
                    continue
                if _abc_cum < abc_a_cut:
                    r['abc_segment'] = 'A'
                elif _abc_cum < abc_b_cut:
                    r['abc_segment'] = 'B'
                else:
                    r['abc_segment'] = 'C'
                _abc_cum += r['total_amount'] / _abc_total

            total_customers   = len(rows)
            total_orders      = sum(r['order_count'] for r in rows)
            avg_ticket_global = round(sum(r['total_amount'] for r in rows) / total_orders, 2) if total_orders else 0.0
            delivery_vals     = [r['delivery_pct'] for r in rows if r['delivery_pct'] is not None]
            physical_vals     = [r['physical_pct'] for r in rows if r['physical_pct'] is not None]
            ontime_vals       = [r['ontime_pct']   for r in rows if r['ontime_pct']   is not None]
            freq_vals         = [r['avg_days_between'] for r in rows if r['avg_days_between'] is not None]

            total_amount_global = round(sum(r['total_amount'] for r in rows), 2)
            return {
                'rows': rows,
                'kpis': {
                    'total_customers':  total_customers,
                    'total_orders':     total_orders,
                    'total_amount':     total_amount_global,
                    'avg_ticket':       avg_ticket_global,
                    'avg_delivery_pct': round(sum(delivery_vals) / len(delivery_vals), 1) if delivery_vals else None,
                    'avg_physical_pct': round(sum(physical_vals) / len(physical_vals), 1) if physical_vals else None,
                    'avg_ontime_pct':   round(sum(ontime_vals)   / len(ontime_vals),   1) if ontime_vals   else None,
                    'avg_days_between': round(sum(freq_vals)     / len(freq_vals),     1) if freq_vals     else None,
                    'delivery_n':       len(delivery_vals),
                    'physical_n':       len(physical_vals),
                    'ontime_n':         len(ontime_vals),
                },
                'config': cfg,
            }

        except Exception as e:
            _logger.error('[CustomerAnalysis] error: %s', e, exc_info=True)
            return {'rows': [], 'kpis': empty_kpis, 'config': cfg, 'error': str(e)}

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
        allowed = self._get_wh_domains().allowed_ids
        if allowed is not None:
            allowed_set = set(allowed)
            warehouse_ids = [w for w in (warehouse_ids or []) if w in allowed_set] or allowed
        wh_domain = [('warehouse_id', 'in', warehouse_ids)] if warehouse_ids else []

        # sudo(): usuario no tiene acceso directo a sale.order; se lee sólo el agregado para el dashboard
        orders = self.env['sale.order'].sudo().search([
            ('partner_id', '=', partner_id),
            ('state', 'in', ['sale', 'done']),
            ('date_order', '>=', d_from_str),
            ('date_order', '<=', d_to_str),
        ] + wh_domain)

        partner = self.env['res.partner'].search([
            ('id', '=', partner_id),
            '|', ('company_id', '=', False), ('company_id', 'in', self.env.user.company_ids.ids)
        ], limit=1)
        if not partner:
            raise AccessError(_("Socio no encontrado o sin acceso"))

        if not orders:
            return {
                'partner_name': partner.display_name or partner.name,
                'monthly_data': [],
                'family_mix':   [],
                'orders':       [],
            }

        so_data   = orders.read(['id', 'name', 'date_order', 'amount_untaxed', 'state'])
        # sudo(): usuario no tiene acceso directo a sale.order.line; se lee sólo el agregado para el dashboard
        lines     = self.env['sale.order.line'].sudo().search([('order_id', 'in', orders.ids)])
        lines_data = lines.read(['order_id', 'product_id', 'product_uom_qty', 'qty_delivered', 'price_subtotal'])

        prod_ids  = list({l['product_id'][0] for l in lines_data if l.get('product_id')})
        # sudo(): usuario no tiene acceso directo a product.product; se lee sólo el agregado para el dashboard
        prods     = self.env['product.product'].sudo().browse(prod_ids).read(['id', 'categ_id', 'product_tmpl_id'])
        tmpl_by_prod  = {p['id']: (p.get('product_tmpl_id') or (0,))[0] for p in prods}

        # Leer nombre hoja de categoría (no complete_name con jerarquía)
        categ_ids = list({(p.get('categ_id') or [0])[0] for p in prods if p.get('categ_id')})
        categ_leaf_names = {}
        if categ_ids:
            for c in self.env['product.category'].sudo().browse(categ_ids).read(['id', 'name']):
                categ_leaf_names[c['id']] = c['name']
        categ_by_prod = {
            p['id']: categ_leaf_names.get((p.get('categ_id') or [0])[0], 'Sin familia')
            for p in prods
        }

        tmpl_ids = list({tid for tid in tmpl_by_prod.values() if tid})
        sale_cat_by_tmpl = {}
        if tmpl_ids:
            for t in self.env['product.template'].sudo().browse(tmpl_ids).read(['id', 'x_sale_category']):
                sale_cat_by_tmpl[t['id']] = t.get('x_sale_category') or ''

        sol_by_order = defaultdict(list)
        for l in lines_data:
            sol_by_order[l['order_id'][0]].append(l)

        # ── Entregas físicas del período (tasa física) ────────────────────────
        # Salidas completadas por fecha de efectivización dentro del período, de
        # cualquier pedido del cliente. Se guarda el mes de confirmación del pedido
        # de origen para el desglose de los tooltips.
        phys_pick_domain = [
            ('state', '=', 'done'),
            ('picking_type_code', '=', 'outgoing'),
            ('sale_id.partner_id', '=', partner_id),
            ('date_done', '>=', d_from_str),
            ('date_done', '<=', d_to_str),
        ]
        if warehouse_ids:
            phys_pick_domain.append(('picking_type_id.warehouse_id', 'in', warehouse_ids))
        # sudo(): usuario no tiene acceso directo a stock.picking; solo agregado para el dashboard
        phys_picks = self.env['stock.picking'].sudo().search_read(
            phys_pick_domain, ['id', 'sale_id', 'date_done'])
        phys_so_ids   = list({p['sale_id'][0] for p in phys_picks})
        phys_so_month = {
            s['id']: str(s['date_order'])[:7]
            for s in self.env['sale.order'].sudo().browse(phys_so_ids).read(['id', 'date_order'])
        } if phys_so_ids else {}
        phys_qty_by_pick = defaultdict(float)
        phys_qty_by_prod = defaultdict(float)
        if phys_picks:
            for g in self.env['stock.move.line'].sudo().read_group(
                [('picking_id', 'in', [p['id'] for p in phys_picks]),
                 ('state', '=', 'done'), ('product_id', '!=', False)],
                ['picking_id', 'product_id', 'quantity:sum'],
                ['picking_id', 'product_id'], lazy=False,
            ):
                _q = g.get('quantity') or 0.0
                phys_qty_by_pick[g['picking_id'][0]] += _q
                phys_qty_by_prod[g['product_id'][0]] += _q
        # Físico por mes de ENTREGA + desglose por mes de confirmación del pedido
        phys_by_del_month    = defaultdict(float)
        phys_break_del_month = defaultdict(lambda: defaultdict(float))
        phys_break_total     = defaultdict(float)
        phys_total           = 0.0
        for p in phys_picks:
            _q = phys_qty_by_pick.get(p['id'], 0.0)
            if _q <= 0:
                continue
            _dmk = str(p['date_done'])[:7]
            _omk = phys_so_month.get(p['sale_id'][0], '')
            phys_by_del_month[_dmk] += _q
            if _omk:
                phys_break_del_month[_dmk][_omk] += _q
                phys_break_total[_omk] += _q
            phys_total += _q

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
        # Unión de meses con pedidos y meses con entregas físicas (puede haber meses
        # con despachos pero sin pedidos confirmados).
        for mk in sorted(set(monthly.keys()) | set(phys_by_del_month.keys())):
            m  = monthly[mk]
            dp = round(m['qty_delivered'] / m['qty_ordered'] * 100, 1) if m['qty_ordered'] > 0 else None
            amt_del = round(m['amount'] * m['qty_delivered'] / m['qty_ordered'], 2) if m['qty_ordered'] > 0 else 0.0
            phys_m  = phys_by_del_month.get(mk, 0.0)
            monthly_data.append({
                'month':            mk,
                'amount':           round(m['amount'], 2),
                'amount_delivered': amt_del,
                'qty_ordered':      round(m['qty_ordered'], 1),
                'qty_delivered':    round(m['qty_delivered'], 1),
                'orders':           m['orders'],
                'delivery_pct':     dp,
                'qty_delivered_phys': round(phys_m, 1),
                'physical_pct':     round(phys_m / m['qty_ordered'] * 100, 1) if m['qty_ordered'] > 0 else None,
                'phys_by_order_month': {k: round(v, 1) for k, v in sorted(phys_break_del_month.get(mk, {}).items())},
            })

        # Mix de familias
        fam_amounts = defaultdict(float)
        fam_qty     = defaultdict(float)
        total_fam_qty = 0.0
        for l in lines_data:
            if not l.get('product_id'):
                continue
            categ = categ_by_prod.get(l['product_id'][0], 'Sin familia')
            amt   = l['price_subtotal'] or 0.0
            qty   = l['product_uom_qty'] or 0.0
            fam_amounts[categ] += amt
            fam_qty[categ]     += qty
            total_fam_qty      += qty

        total_fam_amount = sum(fam_amounts.values())
        family_mix = sorted([
            {
                'name':       k,
                'amount':     round(fam_amounts[k], 2),
                'qty':        round(v, 1),
                'pct':        round(v / total_fam_qty * 100, 1) if total_fam_qty else 0.0,
                'pct_amount': round(fam_amounts[k] / total_fam_amount * 100, 1) if total_fam_amount else 0.0,
            }
            for k, v in fam_qty.items()
        ], key=lambda x: x['qty'], reverse=True)[:10]

        total_qty_ordered = round(sum(l['product_uom_qty'] or 0.0 for l in lines_data), 1)

        # Top productos
        prod_totals = defaultdict(lambda: {'qty_ordered': 0.0, 'qty_delivered': 0.0, 'amount': 0.0, 'orders': set()})
        prod_names  = {}
        for l in lines_data:
            if not l.get('product_id'):
                continue
            pid = l['product_id'][0]
            prod_names[pid] = l['product_id'][1]
            prod_totals[pid]['qty_ordered']   += l['product_uom_qty'] or 0.0
            prod_totals[pid]['qty_delivered'] += l['qty_delivered']   or 0.0
            prod_totals[pid]['amount']        += l['price_subtotal']  or 0.0
            prod_totals[pid]['orders'].add(l['order_id'][0])

        top_products = sorted([
            {
                'product_id':    pid,
                'tmpl_id':       tmpl_by_prod.get(pid, 0),
                'name':          prod_names.get(pid, ''),
                'qty_ordered':   round(v['qty_ordered'],  1),
                'qty_delivered': round(v['qty_delivered'], 1),
                'amount':        round(v['amount'], 2),
                'order_count':   len(v['orders']),
                'delivery_pct':  round(v['qty_delivered'] / v['qty_ordered'] * 100, 1)
                                 if v['qty_ordered'] > 0 else None,
                'qty_delivered_phys': round(phys_qty_by_prod.get(pid, 0.0), 1),
                'physical_pct':  round(phys_qty_by_prod.get(pid, 0.0) / v['qty_ordered'] * 100, 1)
                                 if v['qty_ordered'] > 0 else None,
                'sale_category': sale_cat_by_tmpl.get(tmpl_by_prod.get(pid, 0), ''),
                'family':        categ_by_prod.get(pid, ''),
            }
            for pid, v in prod_totals.items()
        ], key=lambda x: x['amount'], reverse=True)

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

        # Mix por categoría de venta
        CAT_ORDER = ['A', 'B', 'C', 'D', 'E']
        sale_cat_totals = defaultdict(lambda: {'qty': 0.0, 'amount': 0.0, 'products': set()})
        for l in lines_data:
            if not l.get('product_id'):
                continue
            pid     = l['product_id'][0]
            tmpl_id = tmpl_by_prod.get(pid, 0)
            cat     = sale_cat_by_tmpl.get(tmpl_id, '') or ''
            sale_cat_totals[cat]['qty']      += l['product_uom_qty'] or 0.0
            sale_cat_totals[cat]['amount']   += l['price_subtotal']  or 0.0
            sale_cat_totals[cat]['products'].add(pid)
        total_sc_qty    = sum(v['qty']    for v in sale_cat_totals.values())
        total_sc_amount = sum(v['amount'] for v in sale_cat_totals.values())
        sale_category_mix = sorted([
            {
                'name':       k if k else 'Sin cat.',
                'qty':        round(v['qty'], 1),
                'amount':     round(v['amount'], 2),
                'pct':        round(v['qty']    / total_sc_qty    * 100, 1) if total_sc_qty    else 0.0,
                'pct_amount': round(v['amount'] / total_sc_amount * 100, 1) if total_sc_amount else 0.0,
                'sku_count':  len(v['products']),
            }
            for k, v in sale_cat_totals.items()
        ], key=lambda x: CAT_ORDER.index(x['name']) if x['name'] in CAT_ORDER else 99)

        return {
            'partner_name':       partner.display_name or partner.name,
            'monthly_data':       monthly_data,
            'family_mix':         family_mix,
            'sale_category_mix':  sale_category_mix,
            'orders':             order_list,
            'top_products':       top_products,
            'total_qty_ordered':  total_qty_ordered,
            # Agregado de tasa física del cliente en el período
            'total_qty_delivered_phys': round(phys_total, 1),
            'physical_pct':       round(phys_total / total_qty_ordered * 100, 1) if total_qty_ordered > 0 else None,
            'phys_by_order_month': {k: round(v, 1) for k, v in sorted(phys_break_total.items())},
        }
