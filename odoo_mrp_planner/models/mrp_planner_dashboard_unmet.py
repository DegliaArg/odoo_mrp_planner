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
from datetime import datetime

from odoo import models, api, _

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
            order_partner = {o['id']: (o['partner_id'] or (0, ''))
                             for o in orders.read(['partner_id'])}

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
                    ['id', 'display_name', 'categ_id', 'lst_price'])
            }

            # ── 3. Agregación por la dimensión elegida ───────────────────────
            def _new(key, name):
                return {'key': key, 'name': name,
                        'qty_ordered': 0.0, 'qty_delivered': 0.0,
                        'unmet_qty': 0.0, 'unmet_amount': 0.0,
                        '_orders': set(), '_cross': set()}
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
                    key, name, cross = partner[0], partner[1], pid
                elif dimension == 'product':
                    partner = order_partner.get(oid) or (0, '')
                    key, name, cross = pid, pi.get('display_name', ''), partner[0]
                else:  # family
                    categ = pi.get('categ_id') or (0, '')
                    key, name, cross = categ[0], (categ[1] or 'Sin familia'), pid

                d = agg.get(key)
                if d is None:
                    d = _new(key, name)
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

            # ── 4. Filas (solo entidades con pendiente) ──────────────────────
            rows = []
            for d in agg.values():
                if d['unmet_qty'] <= 0:
                    continue
                ordered = d['qty_ordered']
                rows.append({
                    'key':             d['key'],
                    'name':            d['name'] or '(sin nombre)',
                    'qty_ordered':     round(ordered, 1),
                    'qty_delivered':   round(d['qty_delivered'], 1),
                    'unmet_qty':       round(d['unmet_qty'], 1),
                    'unmet_amount':    round(d['unmet_amount'], 2),
                    'fulfillment_pct': round(d['qty_delivered'] / ordered * 100, 1) if ordered > 0 else None,
                    'unmet_pct':       round(d['unmet_qty'] / ordered * 100, 1) if ordered > 0 else None,
                    'affected_orders': len(d['_orders']),
                    'cross_count':     len(d['_cross']),
                })

            rows.sort(key=lambda r: r['unmet_amount'], reverse=True)

            # ── 5. KPIs globales (punto de partida; el front recalcula sobre
            #       las filas filtradas, salvo affected_orders que es distinto). ─
            tot_unmet_qty = sum(r['unmet_qty']     for r in rows)
            tot_unmet_amt = sum(r['unmet_amount']  for r in rows)
            tot_ordered   = sum(r['qty_ordered']   for r in rows)
            tot_delivered = sum(r['qty_delivered'] for r in rows)
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
