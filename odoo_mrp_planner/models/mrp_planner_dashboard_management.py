# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_management.py
Modelo: extensión de mrp.planner.dashboard

Backend del panel de Gerencia (Resumen diario): consolida en una sola
consulta los indicadores que el CEO recibe a diario por mail, calculados en
vivo para el mes seleccionado (por defecto, el mes en curso):

- Demanda del mes por categoría de producto (líneas de venta confirmadas).
- Facturado del mes: piezas y monto, total y por categoría (facturas de cliente).
- Despachos del mes: piezas de transferencias validadas (estado Hecho).
- Embalajes / Picking: piezas pendientes AHORA (foto del estado Listo/Asignado).
- Producido del mes por categoría de producto (OFs terminadas).

Variación diaria: en los 4 indicadores acumulables (demanda, facturado,
despachos, producido) se devuelve además lo aportado hoy y ayer para mostrar
"Hoy: +X" con flecha ▲▼. Es reconstruible en vivo (misma consulta acotada al
día), no requiere guardar snapshots. Solo tiene sentido si el mes seleccionado
es el mes en curso.

Los tipos de operación de despachos/embalajes/picking son configurables
(mrp_reschedule_config_management) porque son IDs propios de cada base.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende vía _inherit.
- mrp_reschedule_config_management: campos management_*_picking_type_ids.
- sale.order.line / account.move.line / stock.picking / mrp.production: fuentes.
"""
import logging
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import models, api, fields, _
from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import no_subcontract_domain

_logger = logging.getLogger(__name__)

# Grupos aceptados por el guard de los métodos RPC de Gerencia.
_GRP_READ = 'odoo_mrp_planner.group_management_read'
_GRP_ADMIN = 'odoo_mrp_planner.group_management'


class MrpPlannerDashboardManagement(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Apertura / refresco ──────────────────────────────────────────────────

    @api.model
    def action_open_gerencia(self):
        """Abre el panel de Gerencia (Resumen diario)."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Resumen diario'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_gerencia_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_gerencia(self):
        """Reabre el panel de Gerencia (el cálculo es en vivo: recargar equivale
        a recalcular todo con datos actuales)."""
        self._ensure_planner_group(_GRP_READ, _GRP_ADMIN)
        return self.env['mrp.planner.dashboard'].action_open_gerencia()

    # ── Helpers de fecha ─────────────────────────────────────────────────────

    @staticmethod
    def _mgmt_month_range(month):
        """(first_date, last_date) del mes 'YYYY-MM' como objetos date."""
        y, m = int(month[:4]), int(month[5:7])
        first = fields.Date.to_date('%04d-%02d-01' % (y, m))
        last = first + relativedelta(months=1) - relativedelta(days=1)
        return first, last

    @staticmethod
    def _mgmt_day_bounds(d):
        """('YYYY-MM-DD 00:00:00', 'YYYY-MM-DD 23:59:59') de un date."""
        s = fields.Date.to_string(d)
        return s + ' 00:00:00', s + ' 23:59:59'

    # ── Agregación por categoría ─────────────────────────────────────────────

    def _mgmt_agg_by_categ(self, qty_pairs, amt_pairs=None):
        """Agrega (product_id, valor) por categoría de producto.

        :param qty_pairs: list[(product_id, qty)]
        :param amt_pairs: list[(product_id, amount)] opcional (facturado).
        :returns: dict con 'rows' (ordenadas desc por monto o cantidad),
                  'total_qty' y, si hay amt_pairs, 'total_amount'.
        """
        prod_ids = {pid for pid, _v in qty_pairs}
        if amt_pairs:
            prod_ids |= {pid for pid, _v in amt_pairs}
        prods = self.env['product.product'].sudo().browse(list(prod_ids))
        categ_of = {}
        for p in prods:
            categ_of[p.id] = (p.categ_id.id or 0,
                              p.categ_id.display_name or _('Sin familia'))

        qty = defaultdict(float)
        amt = defaultdict(float)
        names = {}
        for pid, v in qty_pairs:
            cid, cname = categ_of.get(pid, (0, _('Sin familia')))
            qty[cid] += v
            names[cid] = cname
        for pid, v in (amt_pairs or []):
            cid, cname = categ_of.get(pid, (0, _('Sin familia')))
            amt[cid] += v
            names[cid] = cname

        rows = []
        for cid in names:
            row = {'categ_id': cid, 'name': names[cid], 'qty': round(qty[cid], 2)}
            if amt_pairs is not None:
                row['amount'] = round(amt[cid], 2)
            rows.append(row)
        rows.sort(key=lambda r: r.get('amount', r['qty']), reverse=True)
        res = {'rows': rows, 'total_qty': round(sum(qty.values()), 2)}
        if amt_pairs is not None:
            res['total_amount'] = round(sum(amt.values()), 2)
        return res

    # ── Demanda (ventas confirmadas) ─────────────────────────────────────────

    def _mgmt_demand_qty(self, dt_from, dt_to, company, allowed_ids):
        """Σ cantidad ordenada (líneas de venta confirmadas) en el rango."""
        dom = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.date_order', '>=', dt_from),
            ('order_id.date_order', '<=', dt_to),
            ('product_id', '!=', False),
            ('company_id', 'in', company.ids),
        ]
        if allowed_ids is not None:
            dom.append(('order_id.warehouse_id', 'in', allowed_ids))
        res = self.env['sale.order.line'].sudo().read_group(dom, ['product_uom_qty:sum'], [])
        return (res[0]['product_uom_qty'] or 0.0) if res else 0.0

    def _mgmt_demand(self, dt_from, dt_to, company, allowed_ids):
        """Demanda del mes por categoría."""
        dom = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.date_order', '>=', dt_from),
            ('order_id.date_order', '<=', dt_to),
            ('product_id', '!=', False),
            ('company_id', 'in', company.ids),
        ]
        if allowed_ids is not None:
            dom.append(('order_id.warehouse_id', 'in', allowed_ids))
        groups = self.env['sale.order.line'].sudo().read_group(
            dom, ['product_id', 'product_uom_qty:sum'], ['product_id'])
        pairs = [(g['product_id'][0], g['product_uom_qty'] or 0.0)
                 for g in groups if g['product_id']]
        return self._mgmt_agg_by_categ(pairs)

    # ── Facturado (facturas de cliente) ──────────────────────────────────────

    def _mgmt_invoiced_day(self, d_from, d_to, company):
        """(piezas, monto) facturado en el rango de fechas de factura."""
        AML = self.env['account.move.line'].sudo()
        base = [
            ('parent_state', '=', 'posted'),
            # En Odoo 18 las líneas de producto de factura tienen display_type
            # 'product'; filtrarlo aísla las ventas (excluye impuestos, COGS,
            # secciones y notas, que si no inflarían piezas/monto).
            ('display_type', '=', 'product'),
            ('product_id', '!=', False),
            ('move_id.invoice_date', '>=', d_from),
            ('move_id.invoice_date', '<=', d_to),
            ('company_id', 'in', company.ids),
        ]
        qty = amt = 0.0
        for mtype, sign in (('out_invoice', 1.0), ('out_refund', -1.0)):
            res = AML.read_group(base + [('move_id.move_type', '=', mtype)],
                                 ['quantity:sum', 'price_subtotal:sum'], [])
            if res and res[0]:
                qty += (res[0]['quantity'] or 0.0) * sign
                amt += (res[0]['price_subtotal'] or 0.0) * sign
        return qty, amt

    def _mgmt_invoiced(self, d_from, d_to, company):
        """Facturado del mes: total (piezas + monto) y desglose por categoría.

        No se filtra por depósito: las facturas no tienen depósito.
        Refunds (notas de crédito) restan.
        """
        AML = self.env['account.move.line'].sudo()
        base = [
            ('parent_state', '=', 'posted'),
            # En Odoo 18 las líneas de producto de factura tienen display_type
            # 'product'; filtrarlo aísla las ventas (excluye impuestos, COGS,
            # secciones y notas, que si no inflarían piezas/monto).
            ('display_type', '=', 'product'),
            ('product_id', '!=', False),
            ('move_id.invoice_date', '>=', d_from),
            ('move_id.invoice_date', '<=', d_to),
            ('company_id', 'in', company.ids),
        ]
        qty_pairs = defaultdict(float)
        amt_pairs = defaultdict(float)
        for mtype, sign in (('out_invoice', 1.0), ('out_refund', -1.0)):
            groups = AML.read_group(base + [('move_id.move_type', '=', mtype)],
                                    ['product_id', 'quantity:sum', 'price_subtotal:sum'],
                                    ['product_id'])
            for g in groups:
                if not g['product_id']:
                    continue
                pid = g['product_id'][0]
                qty_pairs[pid] += (g['quantity'] or 0.0) * sign
                amt_pairs[pid] += (g['price_subtotal'] or 0.0) * sign
        return self._mgmt_agg_by_categ(list(qty_pairs.items()), list(amt_pairs.items()))

    # ── Producido (OFs terminadas) ───────────────────────────────────────────

    def _mgmt_produced_domain(self, dt_from, dt_to, company, allowed_ids, prod_wh_ids):
        """Dominio común de OFs terminadas del rango para el indicador de
        producido, con el filtro de depósito del usuario y el configurable."""
        dom = ([('state', '=', 'done'),
                ('date_finished', '>=', dt_from),
                ('date_finished', '<=', dt_to),
                ('company_id', 'in', company.ids)]
               + no_subcontract_domain(self.env))
        if allowed_ids is not None:
            dom.append(('picking_type_id.warehouse_id', 'in', allowed_ids))
        if prod_wh_ids:
            dom.append(('picking_type_id.warehouse_id', 'in', prod_wh_ids))
        return dom

    def _mgmt_produced_qty(self, dt_from, dt_to, company, allowed_ids, prod_wh_ids=None):
        """Σ cantidad producida (OFs terminadas) en el rango."""
        dom = self._mgmt_produced_domain(dt_from, dt_to, company, allowed_ids, prod_wh_ids)
        mos = self.env['mrp.production'].sudo().search(dom)
        return sum(mos.mapped('qty_produced'))

    def _mgmt_produced(self, dt_from, dt_to, company, allowed_ids, prod_wh_ids=None):
        """Producido del mes por familia (categoría de producto)."""
        dom = self._mgmt_produced_domain(dt_from, dt_to, company, allowed_ids, prod_wh_ids)
        mos = self.env['mrp.production'].sudo().search(dom)
        pairs = [(mo.product_id.id, mo.qty_produced or 0.0)
                 for mo in mos if mo.product_id]
        return self._mgmt_agg_by_categ(pairs)

    # ── Movimientos (despachos / embalajes / picking) ────────────────────────

    def _mgmt_agg_by_sale_category(self, pairs):
        """Agrega (product_id, piezas) por categoría de venta (x_sale_category A–E).

        :param pairs: list[(product_id, qty)].
        :returns: list[dict] con key, name y qty, ordenada A, B, C, D, E y
            finalmente los sin categoría de venta.
        """
        prod_ids = {pid for pid, _v in pairs}
        prods = self.env['product.product'].sudo().browse(list(prod_ids))
        cat_of = {p.id: (p.product_tmpl_id.x_sale_category or '') for p in prods}
        names = {'A': 'Cat. A', 'B': 'Cat. B', 'C': 'Cat. C',
                 'D': 'Cat. D', 'E': 'Cat. E', '': 'Sin cat. venta'}
        agg = defaultdict(float)
        for pid, v in pairs:
            agg[cat_of.get(pid, '')] += v
        order = ['A', 'B', 'C', 'D', 'E', '']
        return [{'key': k or 'none', 'name': names.get(k, k), 'qty': round(agg[k], 2)}
                for k in order if k in agg]

    def _mgmt_move_pieces(self, picking_type_ids, state, company, allowed_ids,
                          dt_from=None, dt_to=None, with_breakdown=False):
        """Piezas movidas en las transferencias de los tipos dados, en un estado.

        :param dt_from/dt_to: si se pasan, filtra por fecha de validación
            (date_done) — usado por Despachos (acumulado del mes/día). Sin
            fechas es una foto del estado actual (Embalajes/Picking en Asignado).
        :param with_breakdown: si True, incluye el desglose por categoría de
            venta en 'rows' (se omite en los cálculos diarios para no recargar).
        :returns: dict {'configured', 'qty', 'pickings', 'rows'}.
        """
        if not picking_type_ids:
            return {'configured': False, 'qty': 0.0, 'pickings': 0, 'rows': []}
        Picking = self.env['stock.picking'].sudo()
        dom = [
            ('picking_type_id', 'in', picking_type_ids),
            ('state', '=', state),
            ('company_id', 'in', company.ids),
        ]
        if allowed_ids is not None:
            dom.append(('picking_type_id.warehouse_id', 'in', allowed_ids))
        if dt_from and dt_to:
            dom += [('date_done', '>=', dt_from), ('date_done', '<=', dt_to)]
        pickings = Picking.search(dom)
        moves = pickings.mapped('move_ids')
        qty = sum(moves.mapped('quantity'))
        rows = []
        if with_breakdown:
            by_prod = defaultdict(float)
            for m in moves:
                if m.product_id:
                    by_prod[m.product_id.id] += (m.quantity or 0.0)
            rows = self._mgmt_agg_by_sale_category(list(by_prod.items()))
        return {'configured': True, 'qty': round(qty, 2),
                'pickings': len(pickings), 'rows': rows}

    # ── Punto de entrada del panel ───────────────────────────────────────────

    @api.model
    def get_management_overview(self, month=None):
        """Consolida todos los indicadores del Resumen diario para un mes.

        :param month: str 'YYYY-MM'. None ⇒ mes en curso.
        :returns: dict con demand/invoiced/produced (rows por categoría + total)
            y dispatch/packing/picking (piezas), más los aportes de hoy/ayer
            (solo si el mes es el actual) para la variación diaria.
        """
        self._ensure_planner_group(_GRP_READ, _GRP_ADMIN)
        # Respeta el selector multiempresa nativo: todos los indicadores filtran
        # por las compañías tildadas (self.env.companies), no solo la activa.
        # La empresa activa se usa solo para moneda y config de tipos de operación.
        active = self.env.company
        company = self.env.companies
        today = fields.Date.context_today(self)
        if not month:
            month = '%04d-%02d' % (today.year, today.month)
        first, last = self._mgmt_month_range(month)

        d_from = fields.Date.to_string(first)
        d_to = fields.Date.to_string(last)
        dt_from = d_from + ' 00:00:00'
        dt_to = d_to + ' 23:59:59'

        allowed_ids = self._get_wh_domains().allowed_ids
        no_access = allowed_ids is not None and not allowed_ids

        cfg = self.env['mrp.reschedule.config'].get_config()
        disp_types = cfg.management_dispatch_picking_type_ids.ids
        pack_types = cfg.management_packing_picking_type_ids.ids
        pick_types = cfg.management_picking_picking_type_ids.ids
        prod_wh_ids = cfg.management_production_warehouse_ids.ids

        is_current = (first.year == today.year and first.month == today.month)

        if no_access:
            empty = {'rows': [], 'total_qty': 0.0}
            empty_inv = {'rows': [], 'total_qty': 0.0, 'total_amount': 0.0}
            zero = {'configured': True, 'qty': 0.0, 'pickings': 0, 'rows': []}
            return {
                'month': month, 'is_current': is_current,
                'currency': active.currency_id.symbol or '$',
                'demand': empty, 'invoiced': empty_inv, 'produced': dict(empty),
                'dispatch': zero, 'packing': zero, 'picking': zero,
                'daily': {},
            }

        demand = self._mgmt_demand(dt_from, dt_to, company, allowed_ids)
        invoiced = self._mgmt_invoiced(d_from, d_to, company)
        produced = self._mgmt_produced(dt_from, dt_to, company, allowed_ids, prod_wh_ids)
        dispatch = self._mgmt_move_pieces(disp_types, 'done', company, allowed_ids,
                                          dt_from, dt_to, with_breakdown=True)
        packing = self._mgmt_move_pieces(pack_types, 'assigned', company, allowed_ids,
                                         with_breakdown=True)
        picking = self._mgmt_move_pieces(pick_types, 'assigned', company, allowed_ids,
                                         with_breakdown=True)

        # ── Variación diaria (solo mes en curso; snapshots quedan sin delta) ──
        daily = {}
        if is_current:
            yesterday = today - relativedelta(days=1)
            td_f, td_t = self._mgmt_day_bounds(today)
            yd_f, yd_t = self._mgmt_day_bounds(yesterday)
            td_s, yd_s = fields.Date.to_string(today), fields.Date.to_string(yesterday)

            inv_today = self._mgmt_invoiced_day(td_s, td_s, company)
            inv_yest = self._mgmt_invoiced_day(yd_s, yd_s, company)
            daily = {
                'demand': {
                    'today': round(self._mgmt_demand_qty(td_f, td_t, company, allowed_ids), 2),
                    'yesterday': round(self._mgmt_demand_qty(yd_f, yd_t, company, allowed_ids), 2),
                },
                'invoiced_qty': {
                    'today': round(inv_today[0], 2), 'yesterday': round(inv_yest[0], 2),
                },
                'invoiced_amount': {
                    'today': round(inv_today[1], 2), 'yesterday': round(inv_yest[1], 2),
                },
                'dispatch': {
                    'today': self._mgmt_move_pieces(disp_types, 'done', company,
                                                    allowed_ids, td_f, td_t)['qty'],
                    'yesterday': self._mgmt_move_pieces(disp_types, 'done', company,
                                                        allowed_ids, yd_f, yd_t)['qty'],
                },
                'produced': {
                    'today': round(self._mgmt_produced_qty(td_f, td_t, company, allowed_ids, prod_wh_ids), 2),
                    'yesterday': round(self._mgmt_produced_qty(yd_f, yd_t, company, allowed_ids, prod_wh_ids), 2),
                },
            }

        return {
            'month': month,
            'is_current': is_current,
            'currency': active.currency_id.symbol or '$',
            'company_name': active.name,
            'demand': demand,
            'invoiced': invoiced,
            'produced': produced,
            'dispatch': dispatch,
            'packing': packing,
            'picking': picking,
            'daily': daily,
        }
