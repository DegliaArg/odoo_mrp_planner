"""
Módulo: mrp_planner_dashboard_inventory.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.dashboard

Backend del Panel de Inventario: KPIs y gráficos de despacho (llamada 1) y
tabla operativa de salidas pendientes (llamada 2), cada uno detrás de su
propia barra de filtros en el widget.

Fuentes de datos:
- Estado actual de stock.picking / stock.move: pendiente, disponible, frenado.
- x_dispatch_state / x_dispatch_date: despachado del período.
- mrp.dispatch.stock.log: denominador de la "Tasa física s/ disponible" del
  mes en curso (y meses aún no consolidados).
- mrp.planner.kpi.monthly: meses cerrados (histórico congelado).

Todas las lecturas de stock/ventas usan sudo() con guard de grupo previo,
mismo criterio que el análisis de clientes.
"""
from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api, _

PENDING_PICKING_STATES = ('confirmed', 'waiting', 'assigned')


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Apertura del panel ────────────────────────────────────────────────────

    @api.model
    def action_open_inventory(self):
        """Abre el Panel de Inventario (vista form sin barra de control)."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel de Inventario'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner_dispatch.mrp_inventory_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_inventory(self):
        """Botón Actualizar del panel: reabre la vista con un registro nuevo."""
        return self.action_open_inventory()

    # ── Guard común ───────────────────────────────────────────────────────────

    def _inventory_ensure_group(self):
        self._ensure_planner_group('odoo_mrp_planner_dispatch.group_dispatch_validation')

    # ── Helpers de calendario / filtros ──────────────────────────────────────

    def _inventory_tz(self):
        try:
            return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        except Exception:
            return pytz.utc

    @api.model
    def _inventory_parse_range(self, period_from, period_to):
        """'YYYY-MM-DD' × 2 → (date_from, date_to, dt_from_utc, dt_to_utc_excl)."""
        tz = self._inventory_tz()
        d_from = fields.Date.from_string(period_from)
        d_to   = fields.Date.from_string(period_to)
        dt_from = tz.localize(datetime.combine(d_from, datetime.min.time()))
        dt_to   = tz.localize(datetime.combine(d_to + timedelta(days=1), datetime.min.time()))
        to_utc = lambda d: d.astimezone(pytz.utc).replace(tzinfo=None)
        return d_from, d_to, to_utc(dt_from), to_utc(dt_to)

    @api.model
    def _inventory_wh_domain(self, warehouse_ids, field='picking_type_id.warehouse_id'):
        return [(field, 'in', warehouse_ids)] if warehouse_ids else []

    # ── Llamada 1: KPIs + gráficos ────────────────────────────────────────────

    @api.model
    def get_inventory_dashboard_data(self, period_from, period_to, warehouse_ids=None):
        """
        Payload de la zona superior del panel (una sola llamada RPC):

        :returns: dict con:
            - 'enabled' (bool): registro de disponibilidad activo en Ajustes.
            - 'kpis' (dict): pendiente/disponible/frenado (estado actual),
              despachado del período, tasa física s/ disponible y lag promedio.
            - 'trend' (list[dict]): evolución mensual de la tasa en el rango,
              cada mes con su origen ('monthly' congelado o 'live').
            - 'pending_by_wh' (list[dict]): composición actual del pendiente
              (disponible vs. sin stock) por depósito.
        """
        self._inventory_ensure_group()
        warehouse_ids = warehouse_ids or []
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        log_enabled = bool(cfg and cfg.enable_dispatch_validation
                           and cfg.dispatch_stock_log_enabled)
        d_from, d_to, dt_from, dt_to = self._inventory_parse_range(period_from, period_to)

        # ── Estado actual del pendiente (no depende del período) ─────────────
        pending_moves = self.env['stock.move'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('picking_id.state', 'in', PENDING_PICKING_STATES),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + self._inventory_wh_domain(warehouse_ids, 'picking_id.picking_type_id.warehouse_id'))
        pending_total = pending_available = 0.0
        pending_pick_ids = set()
        by_wh = {}  # {wh_id: [available, blocked]}
        if pending_moves:
            rows = pending_moves.read(['picking_id', 'product_uom_qty', 'quantity'])
            pick_ids = list({r['picking_id'][0] for r in rows if r['picking_id']})
            pick_wh = {}
            for p in self.env['stock.picking'].sudo().browse(pick_ids).read(['picking_type_id']):
                pick_wh[p['id']] = p['picking_type_id'][0] if p['picking_type_id'] else False
            type_ids = list({t for t in pick_wh.values() if t})
            type_wh = {t['id']: (t['warehouse_id'][0] if t['warehouse_id'] else False,
                                 t['warehouse_id'][1] if t['warehouse_id'] else _('Sin depósito'))
                       for t in self.env['stock.picking.type'].sudo().browse(type_ids)
                                    .read(['warehouse_id'])}
            for r in rows:
                pick = r['picking_id'][0] if r['picking_id'] else False
                qty  = r['product_uom_qty'] or 0.0
                resv = min(r['quantity'] or 0.0, qty)
                pending_total     += qty
                pending_available += resv
                if pick:
                    pending_pick_ids.add(pick)
                wh_id, wh_name = type_wh.get(pick_wh.get(pick), (False, _('Sin depósito')))
                by_wh.setdefault((wh_id, wh_name), [0.0, 0.0])
                by_wh[(wh_id, wh_name)][0] += resv
                by_wh[(wh_id, wh_name)][1] += qty - resv

        # ── Despachado del período + lag validación→despacho ─────────────────
        dispatched_picks = self.env['stock.picking'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('x_dispatch_state', '=', 'dispatched'),
            ('x_dispatch_date', '>=', dt_from),
            ('x_dispatch_date', '<', dt_to),
        ] + self._inventory_wh_domain(warehouse_ids))
        dispatched_qty = 0.0
        lag_sum, lag_count = 0.0, 0
        if dispatched_picks:
            d_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', dispatched_picks.ids),
                ('state', '=', 'done'),
            ])
            dispatched_qty = sum(r['quantity'] or 0.0
                                 for r in d_moves.read(['quantity']))
            for p in dispatched_picks.read(['date_done', 'x_dispatch_date']):
                if p['date_done'] and p['x_dispatch_date']:
                    lag_sum += (p['x_dispatch_date'] - p['date_done']).total_seconds() / 86400.0
                    lag_count += 1

        # ── Evolución mensual de la tasa s/ disponible ────────────────────────
        trend = self._inventory_rate_trend(company, d_from, d_to, warehouse_ids) \
            if log_enabled else []
        rate_num = sum(m['num'] for m in trend)
        rate_den = rate_num + sum(m['den_extra'] for m in trend)
        rate_available = round(rate_num / rate_den * 100, 1) if rate_den > 0 else None

        return {
            'enabled': log_enabled,
            'kpis': {
                'pending_total':      round(pending_total, 2),
                'pending_available':  round(pending_available, 2),
                'pending_blocked':    round(pending_total - pending_available, 2),
                'pending_pickings':   len(pending_pick_ids),
                'dispatched_qty':     round(dispatched_qty, 2),
                'dispatched_pickings': len(dispatched_picks),
                'avg_dispatch_lag_days': round(lag_sum / lag_count, 1) if lag_count else None,
                'rate_available':     rate_available,
                'rate_available_num': round(rate_num, 2),
                'rate_available_den': round(rate_den, 2),
            },
            'trend': trend,
            'pending_by_wh': [
                {'warehouse_id': wh_id, 'warehouse': wh_name,
                 'available': round(vals[0], 2), 'blocked': round(vals[1], 2)}
                for (wh_id, wh_name), vals in sorted(by_wh.items(), key=lambda kv: kv[0][1])
            ],
        }

    @api.model
    def _inventory_rate_trend(self, company, d_from, d_to, warehouse_ids):
        """Tasa s/ disponible por mes del rango: consolidado si el mes está
        cerrado en mrp.planner.kpi.monthly, cálculo vivo desde los snapshots
        si no. Meses sin datos quedan con num/den 0 y rate None."""
        Log = self.env['mrp.dispatch.stock.log'].sudo()
        Monthly = self.env['mrp.planner.kpi.monthly'].sudo()
        months = []
        cur = d_from.replace(day=1)
        last = d_to.replace(day=1)
        while cur <= last:
            months.append(cur)
            cur = (cur.replace(day=28) + timedelta(days=6)).replace(day=1)

        trend = []
        for month_start in months:
            base_dom = [
                ('kpi', '=', 'dispatch_available'),
                ('company_id', '=', company.id),
                ('period', '=', month_start),
            ]
            has_marker = Monthly.search_count(
                base_dom + [('product_id', '=', False), ('warehouse_id', '=', False)])
            if has_marker:
                if warehouse_ids:
                    rows = Monthly.search(base_dom + [
                        ('warehouse_id', 'in', warehouse_ids),
                        ('product_id', '!=', False),
                    ]).read(['qty_num', 'qty_den_extra'])
                else:
                    rows = Monthly.search(base_dom + [
                        ('product_id', '=', False), ('warehouse_id', '=', False),
                    ]).read(['qty_num', 'qty_den_extra'])
                num = sum(r['qty_num'] for r in rows)
                den_extra = sum(r['qty_den_extra'] for r in rows)
                source = 'monthly'
            else:
                num, den_extra = self._inventory_rate_live_month(
                    company, month_start, warehouse_ids, Log)
                source = 'live'
            total = num + den_extra
            trend.append({
                'ym':        month_start.strftime('%Y-%m'),
                'num':       round(num, 2),
                'den_extra': round(den_extra, 2),
                'rate':      round(num / total * 100, 1) if total > 0 else None,
                'source':    source,
            })
        return trend

    @api.model
    def _inventory_rate_live_month(self, company, month_start, warehouse_ids, Log):
        """Numerador y denominador extra de un mes NO consolidado, desde los
        snapshots crudos (misma semántica que el cierre mensual)."""
        dt_from, dt_to = Log._month_utc_bounds(month_start.year, month_start.month, company)
        dispatched = self.env['stock.picking'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('x_dispatch_state', '=', 'dispatched'),
            ('x_dispatch_date', '>=', dt_from),
            ('x_dispatch_date', '<', dt_to),
        ] + self._inventory_wh_domain(warehouse_ids))
        num = 0.0
        if dispatched:
            num = sum(r['quantity'] or 0.0 for r in self.env['stock.move'].sudo().search([
                ('picking_id', 'in', dispatched.ids),
                ('state', '=', 'done'),
            ]).read(['quantity']))

        month_end = (month_start.replace(day=28) + timedelta(days=6)).replace(day=1)
        log_dom = [
            ('company_id', '=', company.id),
            ('snapshot_date', '>=', month_start),
            ('snapshot_date', '<', month_end),
            ('qty_reserved', '>', 0),
        ]
        if warehouse_ids:
            log_dom.append(('warehouse_id', 'in', warehouse_ids))
        log_rows = Log.search(log_dom).read(['picking_id', 'product_id', 'qty_reserved'])
        den_extra = 0.0
        if log_rows:
            pick_ids = list({r['picking_id'][0] for r in log_rows if r['picking_id']})
            dispatched_by_eom = set(self.env['stock.picking'].sudo().search([
                ('id', 'in', pick_ids),
                ('x_dispatch_state', '=', 'dispatched'),
                ('x_dispatch_date', '<', dt_to),
            ]).ids)
            best = {}
            for r in log_rows:
                pick = r['picking_id'][0] if r['picking_id'] else False
                prod = r['product_id'][0] if r['product_id'] else False
                if not pick or not prod or pick in dispatched_by_eom:
                    continue
                key = (pick, prod)
                best[key] = max(best.get(key, 0.0), r['qty_reserved'])
            den_extra = sum(best.values())
        return num, den_extra

    # ── Llamada 2: tabla operativa ────────────────────────────────────────────

    @api.model
    def get_inventory_pending_table(self, date_from=None, date_to=None,
                                    warehouse_ids=None, search=''):
        """
        Salidas pendientes (una fila por remito) para la tabla operativa.

        :param date_from/date_to: filtro opcional sobre la fecha programada.
        :param warehouse_ids: filtro opcional de depósitos.
        :param search: texto contra remito / cliente / origen.
        :returns: dict {'rows': list[dict], 'can_dispatch': bool}
        """
        self._inventory_ensure_group()
        warehouse_ids = warehouse_ids or []
        company = self.env.company
        dom = [
            ('company_id', '=', company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('state', 'in', PENDING_PICKING_STATES),
        ] + self._inventory_wh_domain(warehouse_ids)
        if date_from:
            dom.append(('scheduled_date', '>=', date_from))
        if date_to:
            dom.append(('scheduled_date', '<=', f'{date_to} 23:59:59'))
        if search:
            dom += ['|', '|',
                    ('name', 'ilike', search),
                    ('partner_id', 'ilike', search),
                    ('origin', 'ilike', search)]
        picks = self.env['stock.picking'].sudo().search(dom, order='scheduled_date asc')
        if not picks:
            return {'rows': [], 'can_dispatch': self._inventory_can_dispatch()}

        pick_rows = picks.read(['name', 'partner_id', 'origin', 'scheduled_date',
                                'state', 'picking_type_id'])
        type_ids = list({r['picking_type_id'][0] for r in pick_rows if r['picking_type_id']})
        type_wh = {t['id']: (t['warehouse_id'][1] if t['warehouse_id'] else '')
                   for t in self.env['stock.picking.type'].sudo().browse(type_ids)
                                .read(['warehouse_id'])}

        # Cantidades por remito (pendiente / reservado / artículos)
        moves = self.env['stock.move'].sudo().search([
            ('picking_id', 'in', picks.ids),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ])
        qty = {}    # {pick_id: [pending, reserved, set(product_ids)]}
        for r in moves.read(['picking_id', 'product_id', 'product_uom_qty', 'quantity']):
            pick = r['picking_id'][0] if r['picking_id'] else False
            if not pick:
                continue
            qty.setdefault(pick, [0.0, 0.0, set()])
            q = r['product_uom_qty'] or 0.0
            qty[pick][0] += q
            qty[pick][1] += min(r['quantity'] or 0.0, q)
            if r['product_id']:
                qty[pick][2].add(r['product_id'][1])

        # Días disponible: primer snapshot del remito con reserva (evidencia real)
        today = fields.Date.context_today(self)
        self.env.cr.execute("""
            SELECT picking_id, MIN(snapshot_date)
              FROM mrp_dispatch_stock_log
             WHERE picking_id = ANY(%s) AND qty_reserved > 0
             GROUP BY picking_id
        """, (picks.ids,))
        first_avail = dict(self.env.cr.fetchall())

        tz = self._inventory_tz()
        rows = []
        for r in pick_rows:
            pid = r['id']
            pending, reserved, prods = qty.get(pid, [0.0, 0.0, set()])
            sched = r['scheduled_date']
            if sched:
                sched_local = pytz.utc.localize(sched).astimezone(tz)
                sched_str = sched_local.strftime('%d/%m/%Y')
                overdue = (today - sched_local.date()).days
            else:
                sched_str, overdue = '', 0
            avail_since = first_avail.get(pid)
            rows.append({
                'picking_id':    pid,
                'name':          r['name'],
                'partner':       r['partner_id'][1] if r['partner_id'] else '',
                'origin':        r['origin'] or '',
                'warehouse':     type_wh.get(r['picking_type_id'][0]
                                             if r['picking_type_id'] else 0, ''),
                'scheduled':     sched_str,
                'overdue_days':  max(0, overdue),
                'state':         r['state'],
                'qty_pending':   round(pending, 2),
                'qty_available': round(reserved, 2),
                'products':      len(prods),
                'product_names': ', '.join(sorted(prods)[:3]) + ('…' if len(prods) > 3 else ''),
                'days_available': (today - avail_since).days if avail_since else None,
            })
        return {'rows': rows, 'can_dispatch': self._inventory_can_dispatch()}

    @api.model
    def _inventory_can_dispatch(self):
        u = self.env.user
        return (u.has_group('odoo_mrp_planner_dispatch.group_dispatch_validation')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system'))

    # ── Drills (Ver → de los KPIs) ────────────────────────────────────────────

    @api.model
    def action_inventory_pending(self, mode='all', warehouse_ids=None):
        """Lista nativa de salidas pendientes: todas / con stock / sin stock."""
        self._inventory_ensure_group()
        dom = [
            ('company_id', '=', self.env.company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('state', 'in', list(PENDING_PICKING_STATES)),
        ] + self._inventory_wh_domain(warehouse_ids or [])
        name = _('Salidas pendientes')
        if mode == 'available':
            dom.append(('state', '=', 'assigned'))
            name = _('Salidas pendientes con stock')
        elif mode == 'blocked':
            dom.append(('state', 'in', ('confirmed', 'waiting')))
            name = _('Salidas pendientes sin stock')
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': dom,
            'context': {'create': False},
            'target': 'current',
        }

    @api.model
    def action_inventory_dispatched(self, period_from, period_to, warehouse_ids=None):
        """Lista nativa de salidas despachadas en el período."""
        self._inventory_ensure_group()
        _d_from, _d_to, dt_from, dt_to = self._inventory_parse_range(period_from, period_to)
        dom = [
            ('company_id', '=', self.env.company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('x_dispatch_state', '=', 'dispatched'),
            ('x_dispatch_date', '>=', dt_from),
            ('x_dispatch_date', '<', dt_to),
        ] + self._inventory_wh_domain(warehouse_ids or [])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salidas despachadas del período'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': dom,
            'context': {'create': False},
            'target': 'current',
        }
