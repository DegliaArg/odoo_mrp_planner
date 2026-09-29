# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_accounting.py (odoo_mrp_planner)
Modelo: extensión de mrp.planner.dashboard

Backend del Panel de Contabilidad: KPIs generales de FACTURACIÓN real (lo
emitido en account.move), distinto del panel de ventas que mira pedidos y
entregas. Lo que al cliente le importa: facturación mensual desglosada por
familia (categoría de producto) y por categoría de venta (ABC A–E), más top
el embudo Pedido→Entregado→Facturado del período y la evolución de los
últimos 12 meses.

El ranking de clientes NO se repite acá: ya vive en "Análisis de clientes".
La diferencia de fuente es deliberada: los demás paneles miden pedido/vendido
(sale.order) o entregado (stock); este mide FACTURADO real (account.move).

Criterios de cálculo (mismos que se acordaron con el negocio):
- Base: facturas de cliente POSTEADAS (move_type in out_invoice/out_refund).
- Importe = NETO sin impuestos, en MONEDA DE LA COMPAÑÍA. Se toma de
  account.move.line.balance (con signo) sobre las líneas de producto: en una
  factura la línea de ingreso va al haber (balance < 0) y en una nota de
  crédito al debe (balance > 0), de modo que -balance da el ingreso neto y las
  NC RESTAN automáticamente.
- MULTIEMPRESA: respeta el selector nativo de compañías de Odoo
  (self.env.companies), no solo la compañía principal.

Nota multimoneda: los balances están en moneda de cada compañía; si conviven
compañías con monedas distintas la suma es referencial (no hace conversión FX),
mismo criterio pragmático que el resto de los paneles.

Fuentes de datos:
- account.move / account.move.line: facturas y sus líneas de producto.
- product.product / product.category: familia (categ_id) de cada línea.
- mrp.product.company.category: categoría de venta ABC por empresa.

Todas las lecturas usan sudo() con guard de grupo previo, mismo criterio que
el análisis de clientes y el panel de inventario.
"""
import calendar
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Meses hacia atrás (incluido el actual) del gráfico de evolución.
_EVO_MONTHS = 12


def _acc_parse_date(s):
    """'YYYY-MM-DD' → date. Devuelve None si no se puede parsear."""
    if not s:
        return None
    parts = s.split('-')
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


class MrpPlannerDashboardAccounting(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Apertura del panel ────────────────────────────────────────────────────

    @api.model
    def action_open_contabilidad(self):
        """Abre el Panel de Contabilidad (vista form sin barra de control)."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel de Contabilidad'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_contabilidad_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_contabilidad(self):
        """Botón Actualizar del panel: reabre la vista con un registro nuevo."""
        return self.action_open_contabilidad()

    # ── Guard + multiempresa ──────────────────────────────────────────────────

    def _accounting_ensure_group(self):
        """El panel es de los grupos Contabilidad (admin y system también pasan,
        como en todos los paneles: es control de datos; la visibilidad la
        maneja el menú)."""
        self._ensure_planner_group(
            'odoo_mrp_planner.group_accounting_read',
            'odoo_mrp_planner.group_accounting_admin')

    def _accounting_company_ids(self):
        """Compañías activas del selector nativo multiempresa de Odoo."""
        return self.env.companies.ids or [self.env.company.id]

    # ── Filtros del panel ─────────────────────────────────────────────────────

    @api.model
    def get_accounting_filter_options(self):
        """Opciones para los filtros del panel: familias (categorías de producto)
        que aparecen en facturas de cliente de las compañías activas.

        :returns: dict — {'families': [{'id', 'name'}], 'sale_categories': [str]}.
        """
        self._accounting_ensure_group()
        company_ids = self._accounting_company_ids()
        # Categorías de producto con al menos una línea de factura de cliente.
        groups = self.env['account.move.line'].sudo().read_group(
            [('company_id', 'in', company_ids),
             ('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
             ('display_type', '=', 'product'),
             ('product_id', '!=', False)],
            ['product_id'], ['product_id'],
        )
        prod_ids = [g['product_id'][0] for g in groups if g.get('product_id')]
        categ_ids = set()
        if prod_ids:
            for p in self.env['product.product'].sudo().browse(prod_ids).read(['categ_id']):
                if p['categ_id']:
                    categ_ids.add(p['categ_id'][0])
        cats = self.env['product.category'].sudo().browse(list(categ_ids))
        families = sorted(
            [{'id': c.id, 'name': c.display_name} for c in cats],
            key=lambda d: d['name'],
        )
        return {
            'families': families,
            # ABC de venta: mismo orden que el resto de los paneles.
            'sale_categories': ['A', 'B', 'C', 'D', 'E'],
        }

    # ── Payload principal ──────────────────────────────────────────────────────

    @api.model
    def get_accounting_dashboard_data(self, date_from, date_to,
                                      family_id=None, sale_category=None):
        """
        Payload completo del Panel de Contabilidad en una sola llamada RPC.

        Todo se calcula sobre las líneas de producto de facturas de cliente
        posteadas de las compañías activas (selector multiempresa), con importe
        NETO sin impuestos en moneda de la compañía (-balance, las NC restan).

        :param date_from: str 'YYYY-MM-DD' — inicio del período principal.
        :param date_to: str 'YYYY-MM-DD' — fin del período principal.
        :param family_id: int|str|None — categoría de producto (familia) a
            filtrar; None = todas.
        :param sale_category: str|None — categoría de venta ABC ('A'..'E') o
            '__none__' (sin categoría); None/'' = todas.
        :returns: dict con 'kpis', 'by_family', 'by_sale_category', 'funnel'
            (embudo Pedido→Entregado→Facturado del período) y 'evolution'.
        """
        self._accounting_ensure_group()
        company_ids = self._accounting_company_ids()

        d_from = _acc_parse_date(date_from)
        d_to = _acc_parse_date(date_to)
        empty = self._accounting_empty_payload()
        if not d_from or not d_to or d_from > d_to:
            return empty

        # Ventanas de cálculo (todas terminan en d_to):
        #  - período principal [d_from, d_to]
        #  - período anterior de igual longitud (para el Δ%)
        #  - YTD: desde el 1-ene del año de d_to
        #  - evolución: 12 meses hacia atrás desde el mes de d_to
        span = (d_to - d_from).days
        prev_from = d_from - relativedelta(days=span + 1)
        prev_to = d_from - relativedelta(days=1)
        ytd_from = date(d_to.year, 1, 1)
        evo_from = (d_to.replace(day=1) - relativedelta(months=_EVO_MONTHS - 1))

        window_start = min(prev_from, ytd_from, evo_from)

        # ── Una sola lectura de líneas de producto en la ventana amplia ──────
        line_dom = [
            ('company_id', 'in', company_ids),
            ('parent_state', '=', 'posted'),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('display_type', '=', 'product'),
            ('move_id.invoice_date', '>=', window_start.strftime('%Y-%m-%d')),
            ('move_id.invoice_date', '<=', d_to.strftime('%Y-%m-%d')),
        ]
        if family_id:
            line_dom.append(('product_id.categ_id', '=', int(family_id)))
        lines = self.env['account.move.line'].sudo().search_read(
            line_dom, ['balance', 'quantity', 'product_id', 'move_id'])
        if not lines:
            return empty

        # ── Mapas auxiliares (batch, sin N+1) ────────────────────────────────
        move_ids = list({l['move_id'][0] for l in lines if l['move_id']})
        moves = {m['id']: m for m in self.env['account.move'].sudo().browse(move_ids)
                 .read(['invoice_date', 'move_type', 'company_id'])}

        prod_ids = list({l['product_id'][0] for l in lines if l['product_id']})
        prod_info = {}          # prod_id → (tmpl_id, categ_id, categ_name)
        tmpl_ids = set()
        if prod_ids:
            for p in self.env['product.product'].sudo().browse(prod_ids).read(
                    ['product_tmpl_id', 'categ_id']):
                tid = p['product_tmpl_id'][0] if p['product_tmpl_id'] else False
                cid = p['categ_id'][0] if p['categ_id'] else False
                cname = p['categ_id'][1] if p['categ_id'] else _('Sin familia')
                prod_info[p['id']] = (tid, cid, cname)
                if tid:
                    tmpl_ids.add(tid)

        # Categoría de venta ABC por (plantilla, empresa) — vive por empresa.
        salecat_map = {}
        if tmpl_ids:
            for r in self.env['mrp.product.company.category'].sudo().search_read(
                    [('product_tmpl_id', 'in', list(tmpl_ids)),
                     ('company_id', 'in', company_ids)],
                    ['product_tmpl_id', 'company_id', 'sale_category']):
                salecat_map[(r['product_tmpl_id'][0], r['company_id'][0])] = \
                    r['sale_category'] or ''

        # ── Enriquecer cada línea y filtrar por categoría de venta ───────────
        enriched = []
        for l in lines:
            move = moves.get(l['move_id'][0]) if l['move_id'] else None
            if not move or not move['invoice_date']:
                continue
            # .read() puede devolver la fecha como str o date según el contexto;
            # normalizar para poder comparar y formatear sin sorpresas.
            inv_date = fields.Date.to_date(move['invoice_date'])
            if not inv_date:
                continue
            amount = -(l['balance'] or 0.0)  # neto, NC resta
            # Cantidad facturada neta: la NC resta unidades igual que el importe.
            qty = l['quantity'] or 0.0
            if move['move_type'] == 'out_refund':
                qty = -qty
            pid = l['product_id'][0] if l['product_id'] else False
            tid, _cid, cname = prod_info.get(pid, (False, False, _('Sin familia')))
            comp_id = move['company_id'][0] if move['company_id'] else False
            scat = salecat_map.get((tid, comp_id), '')
            if sale_category:
                if sale_category == '__none__' and scat:
                    continue
                if sale_category != '__none__' and scat != sale_category:
                    continue
            enriched.append({
                'amount': amount,
                'qty': qty,
                'date': inv_date,
                'month': inv_date.strftime('%Y-%m'),
                'family': cname,
                'family_id': _cid,
                'salecat': scat,
                'move_id': l['move_id'][0],
                'move_type': move['move_type'],
            })

        in_period = [e for e in enriched if d_from <= e['date'] <= d_to]

        kpis = self._accounting_kpis(enriched, d_from, d_to, prev_from, prev_to, ytd_from)
        return {
            'kpis': kpis,
            'by_family': self._accounting_group_sum(in_period, 'family', 'family_id', top=8),
            'by_sale_category': self._accounting_salecat_breakdown(in_period),
            'funnel': self._accounting_funnel(company_ids, d_from, d_to, family_id),
            'evolution': self._accounting_evolution(enriched, evo_from, d_to),
        }

    # ── Helpers de agregación ──────────────────────────────────────────────────

    def _accounting_empty_payload(self):
        return {
            'kpis': {
                'revenue': 0.0, 'revenue_prev': 0.0, 'delta_pct': None,
                'invoices': 0, 'avg_ticket': 0.0, 'refunds': 0.0, 'ytd': 0.0,
            },
            'by_family': [], 'by_sale_category': [],
            'funnel': {'ordered': 0.0, 'delivered': 0.0, 'invoiced': 0.0,
                       'deliver_pct': None, 'bill_pct': None, 'bill_vs_order_pct': None},
            'evolution': [],
        }

    def _accounting_kpis(self, enriched, d_from, d_to, prev_from, prev_to, ytd_from):
        """Cards de cabecera: facturación neta del período (+Δ vs período
        anterior de igual longitud), nº de facturas y ticket promedio, notas de
        crédito y facturación YTD."""
        rev = rev_prev = ytd = refunds = 0.0
        inv_amount = 0.0
        invoice_ids = set()
        for e in enriched:
            dt = e['date']
            if d_from <= dt <= d_to:
                rev += e['amount']
                if e['move_type'] == 'out_refund':
                    refunds += e['amount']       # negativo
                else:
                    inv_amount += e['amount']
                    invoice_ids.add(e['move_id'])
            if prev_from <= dt <= prev_to:
                rev_prev += e['amount']
            if ytd_from <= dt <= d_to:
                ytd += e['amount']
        delta = None
        if rev_prev:
            delta = round((rev - rev_prev) / abs(rev_prev) * 100, 1)
        n_inv = len(invoice_ids)
        return {
            'revenue': round(rev, 2),
            'revenue_prev': round(rev_prev, 2),
            'delta_pct': delta,
            'invoices': n_inv,
            'avg_ticket': round(inv_amount / n_inv, 2) if n_inv else 0.0,
            'refunds': round(-refunds, 2),   # magnitud positiva de las NC
            'ytd': round(ytd, 2),
        }

    def _accounting_group_sum(self, rows, name_key, id_key, top=None):
        """Suma neta por dimensión (importe y cantidad), ordenada de mayor a
        menor por importe, con % del total en ambas métricas.

        :param top: int|None — recorta a los N primeros (el resto se agrupa en
            'Otros' con su id en False). None = sin recorte.
        """
        agg = {}
        for r in rows:
            k = r[id_key]
            if k not in agg:
                agg[k] = {'id': k, 'name': r[name_key], 'amount': 0.0, 'qty': 0.0}
            agg[k]['amount'] += r['amount']
            agg[k]['qty'] += r.get('qty', 0.0)
        items = sorted(agg.values(), key=lambda d: d['amount'], reverse=True)
        if top and len(items) > top:
            head = items[:top]
            rest = items[top:]
            head.append({'id': False, 'name': _('Otros'),
                         'amount': sum(i['amount'] for i in rest),
                         'qty': sum(i['qty'] for i in rest)})
            items = head
        total_a = sum(i['amount'] for i in items) or 0.0
        total_q = sum(i['qty'] for i in items) or 0.0
        for i in items:
            i['amount'] = round(i['amount'], 2)
            i['qty'] = round(i['qty'], 2)
            i['pct'] = round(i['amount'] / total_a * 100, 1) if total_a else 0.0
            i['pct_qty'] = round(i['qty'] / total_q * 100, 1) if total_q else 0.0
        return items

    def _accounting_salecat_breakdown(self, rows):
        """Facturación neta por categoría de venta ABC (A–E + Sin cat.),
        siempre en el orden A→E→sin, con importe, cantidad y % de cada uno."""
        ORDER = ['A', 'B', 'C', 'D', 'E', '']
        NAMES = {'A': 'Cat. A', 'B': 'Cat. B', 'C': 'Cat. C',
                 'D': 'Cat. D', 'E': 'Cat. E', '': _('Sin cat.')}
        agg = {c: {'amount': 0.0, 'qty': 0.0} for c in ORDER}
        for r in rows:
            c = r['salecat'] if r['salecat'] in agg else ''
            agg[c]['amount'] += r['amount']
            agg[c]['qty'] += r.get('qty', 0.0)
        total_a = sum(v['amount'] for v in agg.values()) or 0.0
        total_q = sum(v['qty'] for v in agg.values()) or 0.0
        out = []
        for c in ORDER:
            if not agg[c]['amount'] and not agg[c]['qty']:
                continue
            out.append({
                'code': c or '__none__',
                'name': NAMES[c],
                'amount': round(agg[c]['amount'], 2),
                'qty': round(agg[c]['qty'], 2),
                'pct': round(agg[c]['amount'] / total_a * 100, 1) if total_a else 0.0,
                'pct_qty': round(agg[c]['qty'] / total_q * 100, 1) if total_q else 0.0,
            })
        return out

    def _accounting_evolution(self, enriched, evo_from, d_to):
        """Facturación neta mensual de los últimos meses (evo_from..d_to),
        incluyendo meses sin facturación en cero para que la línea no tenga
        huecos."""
        months = []
        cur = evo_from.replace(day=1)
        last = d_to.replace(day=1)
        while cur <= last:
            months.append(cur.strftime('%Y-%m'))
            cur = cur + relativedelta(months=1)
        agg = {m: 0.0 for m in months}
        for e in enriched:
            if e['month'] in agg:
                agg[e['month']] += e['amount']
        return [{'ym': m, 'amount': round(agg[m], 2)} for m in months]

    # ── Embudo Pedido → Entregado → Facturado ──────────────────────────────────

    def _accounting_funnel(self, company_ids, d_from, d_to, family_id=None):
        """Embudo del período en UNIDADES: pedido (SO confirmadas), entregado
        (salidas validadas) y facturado (facturas de cliente, neto de NC).

        Complementa lo que ya tienen otros paneles (Ventas/Forecast miran
        pedido y entregas; nadie cruza contra la facturación real) sin
        duplicarlo: acá el foco es cuánto de lo movido del período llegó a
        FACTURARSE.

        Semántica: FLUJO del período — cada etapa cuenta lo ocurrido en el
        rango según su propia fecha (pedido: date_order; entregado: fecha del
        movimiento; facturado: invoice_date). No es una cohorte pedido→factura,
        así que las conversiones son indicadores agregados de salud, no un
        seguimiento línea a línea. Multiempresa: respeta las compañías activas.
        Las unidades combinan UdM distintas (total referencial), igual que el
        panel de inventario.

        :returns: dict — ordered/delivered/invoiced (unidades) y las
            conversiones deliver_pct, bill_pct y bill_vs_order_pct.
        """
        d_from_s = d_from.strftime('%Y-%m-%d')
        d_to_s = d_to.strftime('%Y-%m-%d')
        categ_dom = [('product_id.categ_id', '=', int(family_id))] if family_id else []

        def _sum(model, dom, qty_field):
            g = self.env[model].sudo().read_group(dom, [f'{qty_field}:sum'], [])
            return (g[0][qty_field] or 0.0) if g and g[0].get(qty_field) else 0.0

        # Pedido: líneas de venta confirmadas con date_order en el período.
        ordered = _sum('sale.order.line', [
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', d_from_s + ' 00:00:00'),
            ('order_id.date_order', '<=', d_to_s + ' 23:59:59'),
            ('product_id.sale_ok', '=', True),
            ('company_id', 'in', company_ids),
        ] + categ_dom, 'product_uom_qty')

        # Entregado: movimientos de salida validados en el período.
        delivered = _sum('stock.move.line', [
            ('state', '=', 'done'),
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('date', '>=', d_from_s + ' 00:00:00'),
            ('date', '<=', d_to_s + ' 23:59:59'),
            ('product_id.sale_ok', '=', True),
            ('company_id', 'in', company_ids),
        ] + categ_dom, 'quantity')

        # Facturado: líneas de producto de facturas de cliente (neto de NC).
        inv_base = [
            ('parent_state', '=', 'posted'),
            ('display_type', '=', 'product'),
            ('product_id.sale_ok', '=', True),
            ('company_id', 'in', company_ids),
            ('move_id.invoice_date', '>=', d_from_s),
            ('move_id.invoice_date', '<=', d_to_s),
        ] + categ_dom
        inv_pos = _sum('account.move.line',
                       inv_base + [('move_id.move_type', '=', 'out_invoice')], 'quantity')
        inv_neg = _sum('account.move.line',
                       inv_base + [('move_id.move_type', '=', 'out_refund')], 'quantity')
        invoiced = inv_pos - inv_neg

        pct = lambda num, den: round(num / den * 100, 1) if den else None
        return {
            'ordered': round(ordered, 2),
            'delivered': round(delivered, 2),
            'invoiced': round(invoiced, 2),
            'deliver_pct': pct(delivered, ordered),      # entregado / pedido
            'bill_pct': pct(invoiced, delivered),        # facturado / entregado
            'bill_vs_order_pct': pct(invoiced, ordered),  # facturado / pedido
        }
