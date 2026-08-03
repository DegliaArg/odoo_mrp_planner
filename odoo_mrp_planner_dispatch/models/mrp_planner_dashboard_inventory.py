"""
Módulo: mrp_planner_dashboard_inventory.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.dashboard

Backend del Panel de Inventario: KPIs y gráficos de despacho (llamada 1) y
tabla operativa de salidas pendientes (llamada 2), cada uno detrás de su
propia barra de filtros en el widget.

Los números usan solo datos estándar de Odoo (estados nativos, date_done,
scheduled_date), esté o no activo el circuito de despacho. El circuito, si
está activo, agrega únicamente una capa operativa en la tabla: la cola
"Validado s/ despachar" y el botón masivo "Marcar despachado".

Fuentes de datos:
- Estado actual de stock.picking / stock.move: pendiente, disponible, frenado.
  La disponibilidad se evalúa en el primer eslabón de la cadena de cada
  movimiento (mrp.dispatch.stock.log._chain_available_qty), y las salidas más
  viejas que el corte de antigüedad configurado quedan fuera de todo el panel.
  Las salidas cuentan solo con destino cliente (excluye transferencias entre
  depósitos que usan un tipo de salida).
- state='done' / date_done: entregado del período y atraso de entrega.
- mrp.dispatch.stock.log: denominador de la "Tasa de entrega s/ disponible"
  del mes en curso (y meses aún no consolidados).
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
        self._ensure_planner_group(
            'odoo_mrp_planner_dispatch.group_inventory_read',
            'odoo_mrp_planner_dispatch.group_inventory_admin',
            'odoo_mrp_planner_dispatch.group_dispatch_validation')

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

    @api.model
    def _inventory_qround(self, cfg, value):
        """Redondeo de las cantidades en piezas del panel: a entero (round)
        si en Ajustes está activo "Forzar cantidades enteras", a 2 decimales
        si no. Las tasas y porcentajes conservan su decimal."""
        if cfg and cfg.comparison_force_integer:
            return round(value)
        return round(value, 2)

    @api.model
    def _inventory_effective_whs(self, warehouse_ids):
        """Combina la selección del widget con los depósitos permitidos del
        usuario (Ajustes → permisos por usuario), mismo criterio server-side
        que el resto de los paneles.

        :returns: list[int] — depósitos a filtrar; [] = sin restricción;
                  [0] = usuario sin acceso a ningún depósito (dominio vacío).
        """
        allowed = self._get_allowed_wh_ids()  # None = ve todos
        selected = warehouse_ids or []
        if allowed is None:
            return selected
        if not selected:
            return allowed or [0]
        effective = [w for w in selected if w in allowed]
        return effective or [0]

    # ── Llamada 1: KPIs + gráficos ────────────────────────────────────────────

    @api.model
    def get_inventory_dashboard_data(self, period_from, period_to, warehouse_ids=None):
        """
        Payload de la zona superior del panel (una sola llamada RPC):

        :returns: dict con:
            - 'enabled' (bool): registro de disponibilidad activo en Ajustes.
            - 'kpis' (dict): pendiente/disponible/frenado (estado actual),
              entregado del período, tasa de entrega s/ disponible y atraso
              promedio de entrega.
            - 'trend' (list[dict]): evolución mensual de la tasa en el rango,
              cada mes con su origen ('monthly' congelado o 'live').
            - 'pending_by_wh' (list[dict]): composición actual del pendiente
              (disponible vs. sin stock) por depósito.

        El disponible del pendiente se evalúa en el primer eslabón de la cadena
        de cada movimiento (_chain_available_qty). Las salidas más viejas que
        el corte de antigüedad configurado quedan fuera, y las cantidades en
        piezas respetan "Forzar cantidades enteras" de Ajustes.
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        log_enabled = bool(cfg and cfg.dispatch_stock_log_enabled)
        d_from, d_to, dt_from, dt_to = self._inventory_parse_range(period_from, period_to)

        # ── Estado actual del pendiente (no depende del período) ─────────────
        # Universo = demanda parada en cualquier eslabón de la cadena de
        # entrega (recolección/embalaje/salida, según los pasos del depósito),
        # con las salidas solo a destino cliente. En el flujo lazy de Odoo 17+
        # los eslabones se crean al validar el anterior, así que son disjuntos.
        Log = self.env['mrp.dispatch.stock.log']
        chain_type_ids, type_info = Log._dispatch_chain_types(
            company, warehouse_ids or None)
        cutoff_dom = cfg._dispatch_pending_cutoff_domain('picking_id.scheduled_date')
        pending_moves = self.env['stock.move'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_id.state', 'in', PENDING_PICKING_STATES),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + Log._dispatch_chain_domain(type_info, 'picking_id.') + cutoff_dom) \
            if chain_type_ids else self.env['stock.move'].sudo()
        pending_total = pending_available = 0.0
        pending_pick_ids = set()
        by_wh = {}  # {(wh_id, wh_name): [available, blocked]}
        if pending_moves:
            rows = pending_moves.read(['picking_id', 'product_uom_qty'])
            # Disponible evaluado en el eslabón donde está parada la demanda
            chain_avail = Log._chain_available_qty(pending_moves)
            all_pick_ids = {r['picking_id'][0] for r in rows if r['picking_id']}
            pick_type = {p['id']: p['picking_type_id'][0] if p['picking_type_id'] else False
                         for p in self.env['stock.picking'].sudo()
                                      .browse(list(all_pick_ids)).read(['picking_type_id'])}
            for r in rows:
                qty = r['product_uom_qty'] or 0.0
                avail = min(chain_avail.get(r['id'], 0.0), qty)
                pick = r['picking_id'][0] if r['picking_id'] else False
                pending_total     += qty
                pending_available += avail
                if pick:
                    pending_pick_ids.add(pick)
                info = type_info.get(pick_type.get(pick))
                wh_key = (info[0], info[1]) if info else (False, _('Sin depósito'))
                by_wh.setdefault(wh_key, [0.0, 0.0])
                by_wh[wh_key][0] += avail
                by_wh[wh_key][1] += qty - avail

        # ── Entregado del período + atraso promedio de entrega ───────────────
        # Estándar: salidas a cliente validadas, por fecha de validación.
        delivered_picks = self.env['stock.picking'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('location_dest_id.usage', '=', 'customer'),
            ('state', '=', 'done'),
            ('date_done', '>=', dt_from),
            ('date_done', '<', dt_to),
        ] + self._inventory_wh_domain(warehouse_ids))
        delivered_qty = 0.0
        delay_sum, delay_count = 0.0, 0
        if delivered_picks:
            d_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', delivered_picks.ids),
                ('state', '=', 'done'),
            ])
            delivered_qty = sum(r['quantity'] or 0.0
                                for r in d_moves.read(['quantity']))
            for p in delivered_picks.read(['scheduled_date', 'date_done']):
                if p['scheduled_date'] and p['date_done']:
                    delay_sum += (p['date_done'] - p['scheduled_date']).total_seconds() / 86400.0
                    delay_count += 1

        # ── Evolución mensual de la tasa s/ disponible ────────────────────────
        trend = self._inventory_rate_trend(company, d_from, d_to, warehouse_ids, cfg) \
            if log_enabled else []
        rate_num = sum(m['num'] for m in trend)
        rate_den = rate_num + sum(m['den_extra'] for m in trend)
        rate_available = round(rate_num / rate_den * 100, 1) if rate_den > 0 else None

        # Cantidades en piezas con el redondeo configurado (las tasas no)
        qround = lambda v: self._inventory_qround(cfg, v)
        return {
            'enabled': log_enabled,
            'kpis': {
                'pending_total':      qround(pending_total),
                'pending_available':  qround(pending_available),
                'pending_blocked':    qround(pending_total - pending_available),
                'pending_pickings':   len(pending_pick_ids),
                'delivered_qty':      qround(delivered_qty),
                'delivered_pickings': len(delivered_picks),
                'avg_delivery_delay_days': round(delay_sum / delay_count, 1) if delay_count else None,
                'rate_available':     rate_available,
                'rate_available_num': qround(rate_num),
                'rate_available_den': qround(rate_den),
            },
            'trend': trend,
            'pending_by_wh': [
                {'warehouse_id': wh_id, 'warehouse': wh_name,
                 'available': qround(vals[0]), 'blocked': qround(vals[1])}
                for (wh_id, wh_name), vals in sorted(by_wh.items(), key=lambda kv: kv[0][1])
            ],
        }

    @api.model
    def _inventory_rate_trend(self, company, d_from, d_to, warehouse_ids, cfg=None):
        """Tasa s/ disponible por mes del rango: consolidado si el mes está
        cerrado en mrp.planner.kpi.monthly, cálculo vivo desde los snapshots
        si no. Meses sin datos quedan con num/den 0 y rate None. Las cantidades
        num/den_extra respetan el redondeo configurado; la tasa no."""
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
                'num':       self._inventory_qround(cfg, num),
                'den_extra': self._inventory_qround(cfg, den_extra),
                'rate':      round(num / total * 100, 1) if total > 0 else None,
                'source':    source,
            })
        return trend

    @api.model
    def _inventory_rate_live_month(self, company, month_start, warehouse_ids, Log):
        """Numerador y denominador extra de un mes NO consolidado, desde los
        snapshots crudos. Delegado al mismo helper que usa el cierre mensual
        (_dispatch_month_figures: deduplicación por cadena, exclusión de lo
        despachado hasta fin de mes) para que en vivo y congelado den igual."""
        num, den = Log._dispatch_month_figures(
            company, month_start, warehouse_ids=warehouse_ids or None)
        return sum(num.values()), sum(den.values())

    # ── Llamada 2: tabla operativa ────────────────────────────────────────────

    @api.model
    def get_inventory_pending_table(self, date_from=None, date_to=None,
                                    warehouse_ids=None, search=''):
        """
        Demanda pendiente de entrega (una fila por remito) para la tabla
        operativa. El universo cubre todos los eslabones de la cadena de
        entrega de cada depósito — recolección, embalaje y salida (esta última
        solo a destino cliente), según sus pasos. Con el circuito de despacho
        activo se suman además las salidas validadas sin despachar (etapa
        'ready', la única que puede marcarse como despachada); es una capa
        operativa que no participa de los KPIs.

        La columna de disponible se evalúa en el eslabón donde está parada la
        demanda (_chain_available_qty; las 'ready' están 100 % disponibles) y
        los remitos más viejos que el corte de antigüedad quedan fuera.

        :param date_from/date_to: filtro opcional sobre la fecha programada
                                  (días locales del usuario).
        :param warehouse_ids: filtro opcional de depósitos.
        :param search: texto contra remito / origen.
        :returns: dict {'rows': list[dict], 'can_dispatch': bool,
                        'dispatch_enabled': bool}
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        dispatch_enabled = bool(cfg and cfg.enable_dispatch_validation)
        Log = self.env['mrp.dispatch.stock.log']
        chain_type_ids, type_info = Log._dispatch_chain_types(
            company, warehouse_ids or None)
        empty = {'rows': [], 'can_dispatch': self._inventory_can_dispatch(),
                 'dispatch_enabled': dispatch_enabled}
        if not chain_type_ids:
            return empty
        dom = [
            ('company_id', '=', company.id),
        ] + Log._dispatch_chain_domain(type_info) \
          + cfg._dispatch_pending_cutoff_domain('scheduled_date')
        # Fechas del filtro interpretadas como días locales del usuario
        # (scheduled_date se guarda en UTC)
        tz = self._inventory_tz()
        to_utc = lambda d: tz.localize(datetime.combine(d, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        if date_from:
            dom.append(('scheduled_date', '>=',
                        to_utc(fields.Date.from_string(date_from))))
        if date_to:
            dom.append(('scheduled_date', '<',
                        to_utc(fields.Date.from_string(date_to) + timedelta(days=1))))
        if search:
            dom += ['|',
                    ('name', 'ilike', search),
                    ('origin', 'ilike', search)]
        # Eslabones pendientes; con el circuito activo, también las salidas
        # validadas sin despachar (cola operativa)
        if dispatch_enabled:
            dom += ['|', ('state', 'in', list(PENDING_PICKING_STATES)),
                    '&', ('state', '=', 'done'), ('x_dispatch_state', '=', 'to_dispatch')]
        else:
            dom.append(('state', 'in', list(PENDING_PICKING_STATES)))
        picks = self.env['stock.picking'].sudo().search(dom, order='scheduled_date asc')
        if not picks:
            return empty

        # sale_id (vía grupo de abastecimiento, sale_stock) resuelve el origen a
        # la venta en cualquier eslabón de la cadena; si no está el módulo o el
        # remito no viene de una venta, la columna Origen queda como texto plano.
        has_sale = 'sale_id' in picks._fields
        pick_rows = picks.read(['name', 'partner_id', 'origin', 'scheduled_date',
                                'state', 'picking_type_id']
                               + (['sale_id'] if has_sale else []))
        ready_ids   = {r['id'] for r in pick_rows if r['state'] == 'done'}
        pending_ids = [r['id'] for r in pick_rows if r['state'] != 'done']

        # Cantidades por remito (pendiente / disponible / artículos)
        qty = {}    # {pick_id: [pending, available, {product_id: display_name}]}
        if pending_ids:
            moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', pending_ids),
                ('state', 'not in', ('draft', 'done', 'cancel')),
            ])
            # Disponible evaluado en el eslabón donde está parada la demanda
            chain_avail = Log._chain_available_qty(moves)
            for r in moves.read(['picking_id', 'product_id', 'product_uom_qty']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                qty.setdefault(pick, [0.0, 0.0, {}])
                q = r['product_uom_qty'] or 0.0
                qty[pick][0] += q
                qty[pick][1] += min(chain_avail.get(r['id'], 0.0), q)
                if r['product_id']:
                    qty[pick][2][r['product_id'][0]] = r['product_id'][1]
        if ready_ids:
            done_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', list(ready_ids)),
                ('state', '=', 'done'),
            ])
            for r in done_moves.read(['picking_id', 'product_id', 'quantity']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                qty.setdefault(pick, [0.0, 0.0, {}])
                q = r['quantity'] or 0.0
                qty[pick][0] += q
                qty[pick][1] += q     # validado: 100 % disponible para despachar
                if r['product_id']:
                    qty[pick][2][r['product_id'][0]] = r['product_id'][1]

        # Días disponible: primer snapshot del remito con reserva (evidencia real)
        today = fields.Date.context_today(self)
        self.env.cr.execute("""
            SELECT picking_id, MIN(snapshot_date)
              FROM mrp_dispatch_stock_log
             WHERE picking_id = ANY(%s) AND qty_reserved > 0
             GROUP BY picking_id
        """, (picks.ids,))
        first_avail = dict(self.env.cr.fetchall())

        stage_labels = {
            'pick':  _('Recolección'),
            'pack':  _('Embalaje'),
            'ship':  _('Salida'),
            'ready': _('Validado s/ despachar'),
        }
        tz = self._inventory_tz()
        rows = []
        for r in pick_rows:
            pid = r['id']
            _type = r['picking_type_id'][0] if r['picking_type_id'] else False
            info = type_info.get(_type)
            stage = 'ready' if pid in ready_ids else (info[2] if info else 'ship')
            pending, available, prods = qty.get(pid, [0.0, 0.0, {}])
            # Lista completa de artículos ordenada por nombre (links del widget);
            # los nombres ya vienen del read de los movimientos: sin queries extra.
            detail = sorted(({'id': p_id, 'name': p_name} for p_id, p_name in prods.items()),
                            key=lambda d: d['name'])
            names = [d['name'] for d in detail]
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
                'origin_id':     r['sale_id'][0] if has_sale and r.get('sale_id') else False,
                'warehouse':     info[1] if info else '',
                'scheduled':     sched_str,
                'overdue_days':  max(0, overdue),
                'state':         r['state'],
                'stage':         stage,
                'stage_label':   stage_labels[stage],
                'qty_pending':   self._inventory_qround(cfg, pending),
                'qty_available': self._inventory_qround(cfg, available),
                'products':      len(detail),
                'product_names': ', '.join(names[:3]) + ('…' if len(names) > 3 else ''),
                'products_detail': detail,
                'days_available': (today - avail_since).days if avail_since else None,
            })
        return {'rows': rows, 'can_dispatch': self._inventory_can_dispatch(),
                'dispatch_enabled': dispatch_enabled}

    @api.model
    def _inventory_can_dispatch(self):
        """Despacho masivo desde la tabla: requiere el circuito activo en la
        empresa además del grupo (sin circuito la tabla es de solo lectura)."""
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        if not (cfg and cfg.enable_dispatch_validation):
            return False
        u = self.env.user
        return (u.has_group('odoo_mrp_planner_dispatch.group_dispatch_validation')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system'))

    # ── Drills (Ver → de los KPIs) ────────────────────────────────────────────

    @api.model
    def action_inventory_pending(self, mode='all', warehouse_ids=None):
        """Lista nativa de la demanda pendiente de entrega en cualquier
        eslabón de la cadena: todas / con stock / sin stock. Respeta el corte
        de antigüedad y el destino cliente en las salidas, igual que los KPIs.

        Aproximación del modo 'available': remitos "Preparado" (reserva
        completa en su eslabón) — la disponibilidad parcial por cadena no es
        expresable en un dominio."""
        self._inventory_ensure_group()
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        Log = self.env['mrp.dispatch.stock.log']
        chain_type_ids, type_info = Log._dispatch_chain_types(
            self.env.company, self._inventory_effective_whs(warehouse_ids) or None)
        dom = [
            ('company_id', '=', self.env.company.id),
        ] + Log._dispatch_chain_domain(type_info) \
          + cfg._dispatch_pending_cutoff_domain('scheduled_date')
        name = _('Demanda pendiente de entrega')
        if mode == 'available':
            dom.append(('state', '=', 'assigned'))
            name = _('Demanda pendiente con stock')
        elif mode == 'blocked':
            dom.append(('state', 'in', ('confirmed', 'waiting')))
            name = _('Demanda pendiente sin stock')
        else:
            dom.append(('state', 'in', list(PENDING_PICKING_STATES)))
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            # doAction del lado cliente exige 'views' en acciones armadas a mano
            'views': [[False, 'list'], [False, 'form']],
            'domain': dom,
            'context': {'create': False},
            'target': 'current',
        }

    @api.model
    def action_inventory_delivered(self, period_from, period_to, warehouse_ids=None):
        """Lista nativa de salidas a cliente entregadas (validadas) en el período."""
        self._inventory_ensure_group()
        _d_from, _d_to, dt_from, dt_to = self._inventory_parse_range(period_from, period_to)
        dom = [
            ('company_id', '=', self.env.company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('location_dest_id.usage', '=', 'customer'),
            ('state', '=', 'done'),
            ('date_done', '>=', dt_from),
            ('date_done', '<', dt_to),
        ] + self._inventory_wh_domain(self._inventory_effective_whs(warehouse_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salidas entregadas del período'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'views': [[False, 'list'], [False, 'form']],
            'domain': dom,
            'context': {'create': False},
            'target': 'current',
        }
