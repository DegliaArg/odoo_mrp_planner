"""
Módulo: mrp_planner_dashboard_inventory.py (odoo_mrp_planner)
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
  El universo se define por los tipos de operación de la cadena de entrega
  de cada depósito; la disponibilidad se evalúa en el primer eslabón de la
  cadena de cada movimiento (mrp.dispatch.stock.log._chain_available_qty), y
  las salidas más viejas que el corte de antigüedad configurado quedan fuera
  de todo el panel.
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
            'view_id': self.env.ref('odoo_mrp_planner.mrp_inventory_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_inventory(self):
        """Botón Actualizar del panel: reabre la vista con un registro nuevo."""
        return self.action_open_inventory()

    # ── Guard común ───────────────────────────────────────────────────────────

    def _inventory_ensure_group(self):
        # El panel es de los grupos Inventario (el guard del módulo base deja
        # pasar además a admin del planificador y system, como en todos los
        # paneles: es control de datos; la visibilidad la maneja el menú).
        self._ensure_planner_group(
            'odoo_mrp_planner.group_inventory_read',
            'odoo_mrp_planner.group_inventory_admin')

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
        """Redondeo de las cantidades en piezas de los paneles de Inventario
        y Movimientos: a entero (round) si en Ajustes → Inventario está activo
        "Forzar cantidades enteras", a 2 decimales si no. Las tasas y
        porcentajes conservan su decimal. Toggle propio de Inventario,
        independiente del de la comparativa del forecast."""
        if cfg and cfg.inventory_force_integer:
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
    def get_inventory_picking_types(self, warehouse_ids=None):
        """Tipos de operación de la cadena de entrega para el filtro de los
        gráficos (recolección/embalaje/salida de los depósitos visibles).

        :returns: list[dict] — {'id', 'name', 'stage'} ordenados por nombre.
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        chain_type_ids, _info = self.env['mrp.dispatch.stock.log'] \
            ._dispatch_chain_types(self.env.company, warehouse_ids or None)
        if not chain_type_ids:
            return []
        types = self.env['stock.picking.type'].sudo().browse(chain_type_ids) \
            .read(['display_name'])
        return sorted(({'id': t['id'], 'name': t['display_name']} for t in types),
                      key=lambda d: d['name'])

    @api.model
    def get_inventory_dashboard_data(self, period_from, period_to, warehouse_ids=None,
                                     picking_type_ids=None):
        """
        Payload de la zona superior del panel (una sola llamada RPC):

        :returns: dict con:
            - 'enabled' (bool): registro de disponibilidad activo en Ajustes.
            - 'trend' (list[dict]): evolución mensual de la tasa en el rango,
              cada mes con su origen ('monthly' congelado o 'live').
            - 'pending_by_wh' (list[dict]): composición actual del pendiente
              (disponible vs. sin stock) por depósito.

        Las cards KPI del panel NO salen de acá: viven en la zona tabla
        (get_inventory_pending_table). El disponible del pendiente se evalúa
        en el primer eslabón de la cadena de cada movimiento
        (_chain_available_qty). Las líneas más viejas que el corte de
        antigüedad configurado quedan fuera, y las cantidades en piezas
        respetan "Forzar cantidades enteras" de Ajustes.

        :param picking_type_ids: filtro opcional de tipos de operación de la
            cadena. Con filtro activo, los meses de la tasa se calculan en
            vivo desde los snapshots crudos (el consolidado mensual no guarda
            el tipo de operación).
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        log_enabled = bool(cfg and cfg.dispatch_stock_log_enabled)
        d_from, d_to, dt_from, dt_to = self._inventory_parse_range(period_from, period_to)

        # ── Estado actual del pendiente (no depende del período) ─────────────
        # Universo = demanda parada en cualquier eslabón de la cadena de
        # entrega (recolección/embalaje/salida, según los pasos del depósito).
        # En el flujo lazy de Odoo 17+ los eslabones se crean al validar el
        # anterior, así que son disjuntos.
        Log = self.env['mrp.dispatch.stock.log']
        chain_type_ids, type_info = Log._dispatch_chain_types(
            company, warehouse_ids or None)
        if picking_type_ids:
            type_info = {t: info for t, info in type_info.items()
                         if t in picking_type_ids}
            chain_type_ids = list(type_info)
        # Corte de antigüedad por línea (fecha programada del movimiento)
        cutoff_dom = cfg._dispatch_pending_cutoff_domain('date')
        pending_moves = self.env['stock.move'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_id.picking_type_id', 'in', chain_type_ids),
            ('picking_id.state', 'in', PENDING_PICKING_STATES),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + cutoff_dom) if chain_type_ids else self.env['stock.move'].sudo()
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
                info = type_info.get(pick_type.get(pick))
                wh_key = (info[0], info[1]) if info else (False, _('Sin depósito'))
                by_wh.setdefault(wh_key, [0.0, 0.0])
                by_wh[wh_key][0] += avail
                by_wh[wh_key][1] += qty - avail

        # ── Evolución mensual de la tasa s/ disponible ────────────────────────
        trend = self._inventory_rate_trend(company, d_from, d_to, warehouse_ids, cfg,
                                           picking_type_ids=picking_type_ids) \
            if log_enabled else []

        # Cantidades en piezas con el redondeo configurado (las tasas no).
        # Las cards KPI viven en la zona tabla (get_inventory_pending_table /
        # _inventory_period_kpis): esta llamada alimenta solo los gráficos.
        qround = lambda v: self._inventory_qround(cfg, v)
        return {
            'enabled': log_enabled,
            'trend': trend,
            'pending_by_wh': [
                {'warehouse_id': wh_id, 'warehouse': wh_name,
                 'available': qround(vals[0]), 'blocked': qround(vals[1])}
                for (wh_id, wh_name), vals in sorted(by_wh.items(), key=lambda kv: kv[0][1])
            ],
        }

    @api.model
    def _inventory_rate_trend(self, company, d_from, d_to, warehouse_ids, cfg=None,
                              picking_type_ids=None):
        """Tasa s/ disponible por mes del rango: consolidado si el mes está
        cerrado en mrp.planner.kpi.monthly, cálculo vivo desde los snapshots
        si no. Con filtro de tipos de operación, TODOS los meses se calculan
        en vivo (el consolidado no guarda el tipo): los meses cuyos snapshots
        ya se purgaron quedan sin datos. Meses sin datos quedan con num/den 0
        y rate None. Las cantidades num/den_extra respetan el redondeo
        configurado; la tasa no."""
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
            has_marker = not picking_type_ids and Monthly.search_count(
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
                    company, month_start, warehouse_ids, Log,
                    picking_type_ids=picking_type_ids)
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
    def _inventory_rate_live_month(self, company, month_start, warehouse_ids, Log,
                                   picking_type_ids=None):
        """Numerador y denominador extra de un mes NO consolidado, desde los
        snapshots crudos. Delegado al mismo helper que usa el cierre mensual
        (_dispatch_month_figures: deduplicación por cadena, exclusión de lo
        entregado hasta fin de mes) para que en vivo y congelado den igual."""
        num, den = Log._dispatch_month_figures(
            company, month_start, warehouse_ids=warehouse_ids or None,
            picking_type_ids=picking_type_ids or None)
        return sum(num.values()), sum(den.values())

    # ── Llamada 2: tabla operativa ────────────────────────────────────────────

    @api.model
    def get_inventory_pending_table(self, date_from=None, date_to=None,
                                    warehouse_ids=None, search='',
                                    picking_type_ids=None):
        """
        Demanda pendiente de entrega (una fila por remito) para la tabla
        operativa. El universo cubre todos los eslabones de la cadena de
        entrega de cada depósito — recolección, embalaje y salida, según sus
        pasos. Con el circuito de despacho activo se suman además las salidas
        validadas sin despachar (etapa 'ready', la única que puede marcarse
        como despachada); es una capa operativa que no participa de los KPIs.

        La columna de disponible se evalúa en el eslabón donde está parada la
        demanda (_chain_available_qty; las 'ready' están 100 % disponibles) y
        las líneas más viejas que el corte de antigüedad quedan fuera.

        :param date_from/date_to: filtro opcional sobre la fecha programada de
            CADA LÍNEA (stock.move.date, días locales del usuario): un remito
            con líneas en fechas distintas entra solo con las líneas del rango
            y sus cantidades. Las validadas sin despachar (líneas ya hechas,
            sin fecha programada vigente) se filtran por la cabecera.
        :param warehouse_ids: filtro opcional de depósitos.
        :param search: texto contra remito / origen.
        :param picking_type_ids: filtro opcional de tipos de operación de la
            cadena; también acota los KPIs del período.
        :returns: dict {'rows': list[dict], 'can_dispatch': bool,
                        'dispatch_enabled': bool, 'period_kpis': dict}
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        dispatch_enabled = self._inventory_dispatch_enabled()
        Log = self.env['mrp.dispatch.stock.log']

        # Fechas del filtro interpretadas como días locales del usuario
        # (las fechas se guardan en UTC)
        tz = self._inventory_tz()
        to_utc = lambda d: tz.localize(datetime.combine(d, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        dt_from = to_utc(fields.Date.from_string(date_from)) if date_from else None
        dt_to = to_utc(fields.Date.from_string(date_to) + timedelta(days=1)) \
            if date_to else None

        # KPIs del período con los MISMOS filtros de la tabla: el rango se
        # aplica a la fecha de validación (date_done) y los depósitos son los
        # de esta barra — así las cards cierran con sus listas.
        period = self._inventory_period_kpis(company, cfg, warehouse_ids,
                                             date_from, date_to, dt_from, dt_to,
                                             picking_type_ids=picking_type_ids)

        chain_type_ids, type_info = Log._dispatch_chain_types(
            company, warehouse_ids or None)
        if picking_type_ids:
            type_info = {t: info for t, info in type_info.items()
                         if t in picking_type_ids}
            chain_type_ids = list(type_info)
        empty = {'rows': [], 'can_dispatch': self._inventory_can_dispatch(),
                 'dispatch_enabled': dispatch_enabled, 'period_kpis': period}
        if not chain_type_ids:
            return empty

        # ── Líneas pendientes de la cadena, filtradas por SU fecha programada ──
        move_dom = [
            ('company_id', '=', company.id),
            ('picking_id.picking_type_id', 'in', chain_type_ids),
            ('picking_id.state', 'in', list(PENDING_PICKING_STATES)),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + cfg._dispatch_pending_cutoff_domain('date')
        if dt_from:
            move_dom.append(('date', '>=', dt_from))
        if dt_to:
            move_dom.append(('date', '<', dt_to))
        if search:
            move_dom += ['|',
                         ('picking_id.name', 'ilike', search),
                         ('picking_id.origin', 'ilike', search)]
        moves = self.env['stock.move'].sudo().search(move_dom)

        # ── Cola operativa del despacho (remitos validados): sus líneas ya
        #    tienen fecha efectiva, así que el filtro va por la cabecera ──
        ready_leaf = self._inventory_ready_leaf()
        ready_picks = self.env['stock.picking'].sudo()
        if ready_leaf:
            pick_dom = [
                ('company_id', '=', company.id),
                ('picking_type_id', 'in', chain_type_ids),
            ] + cfg._dispatch_pending_cutoff_domain('scheduled_date') + ready_leaf
            if dt_from:
                pick_dom.append(('scheduled_date', '>=', dt_from))
            if dt_to:
                pick_dom.append(('scheduled_date', '<', dt_to))
            if search:
                pick_dom += ['|',
                             ('name', 'ilike', search),
                             ('origin', 'ilike', search)]
            ready_picks = self.env['stock.picking'].sudo().search(pick_dom)

        # Cantidades por remito (pendiente / disponible / artículos / fecha
        # mínima de las líneas consideradas)
        qty = {}    # {pick_id: [pending, available, {product_id: name}, min_date]}
        if moves:
            # Disponible evaluado en el eslabón donde está parada la demanda
            chain_avail = Log._chain_available_qty(moves)
            for r in moves.read(['picking_id', 'product_id', 'product_uom_qty', 'date']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                entry = qty.setdefault(pick, [0.0, 0.0, {}, None])
                q = r['product_uom_qty'] or 0.0
                entry[0] += q
                entry[1] += min(chain_avail.get(r['id'], 0.0), q)
                if r['product_id']:
                    entry[2][r['product_id'][0]] = r['product_id'][1]
                if r['date'] and (entry[3] is None or r['date'] < entry[3]):
                    entry[3] = r['date']
        ready_ids = set(ready_picks.ids)
        if ready_ids:
            done_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', list(ready_ids)),
                ('state', '=', 'done'),
            ])
            for r in done_moves.read(['picking_id', 'product_id', 'quantity']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                entry = qty.setdefault(pick, [0.0, 0.0, {}, None])
                q = r['quantity'] or 0.0
                entry[0] += q
                entry[1] += q     # validado: 100 % disponible para despachar
                if r['product_id']:
                    entry[2][r['product_id'][0]] = r['product_id'][1]

        pending_ids = sorted(set(qty) - ready_ids)
        picks = self.env['stock.picking'].sudo().browse(
            pending_ids + sorted(ready_ids))
        if not picks:
            return empty

        # sale_id (vía grupo de abastecimiento, sale_stock) resuelve el origen a
        # la venta en cualquier eslabón de la cadena; si no está el módulo o el
        # remito no viene de una venta, la columna Origen queda como texto plano.
        has_sale = 'sale_id' in picks._fields
        pick_rows = picks.read(['name', 'partner_id', 'origin', 'scheduled_date',
                                'state', 'picking_type_id']
                               + (['sale_id'] if has_sale else []))

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
            'ship':  _('Entrega'),
            'ready': _('Validado s/ despachar'),
        }
        # Etiquetas NATIVAS (traducidas) del estado del remito: la tabla
        # muestra exactamente lo mismo que el remito abierto
        state_sel = dict(self.env['stock.picking']
                         .fields_get(['state'])['state']['selection'])
        rows = []
        for r in pick_rows:
            pid = r['id']
            _type = r['picking_type_id'][0] if r['picking_type_id'] else False
            info = type_info.get(_type)
            stage = 'ready' if pid in ready_ids else (info[2] if info else 'ship')
            pending, available, prods, min_date = qty.get(pid, [0.0, 0.0, {}, None])
            # Lista completa de artículos ordenada por nombre (links del widget);
            # los nombres ya vienen del read de los movimientos: sin queries extra.
            detail = sorted(({'id': p_id, 'name': p_name} for p_id, p_name in prods.items()),
                            key=lambda d: d['name'])
            names = [d['name'] for d in detail]
            # Fecha programada más próxima de las líneas consideradas; para las
            # validadas (sin fecha programada vigente) la de la cabecera
            sched = min_date or r['scheduled_date']
            if sched:
                sched_local = pytz.utc.localize(sched).astimezone(tz)
                sched_str = sched_local.strftime('%d/%m/%Y')
                # Días vencidos por fecha calendario: 0 = vence HOY (cuenta
                # como vencida), negativo = a futuro, None = sin fecha
                overdue = (today - sched_local.date()).days
            else:
                sched_str, overdue = '', None
            avail_since = first_avail.get(pid)
            rows.append({
                'picking_id':    pid,
                'name':          r['name'],
                'partner':       r['partner_id'][1] if r['partner_id'] else '',
                'origin':        r['origin'] or '',
                'origin_id':     r['sale_id'][0] if has_sale and r.get('sale_id') else False,
                'warehouse':     info[1] if info else '',
                'scheduled':     sched_str,
                'overdue_days':  overdue,
                'state':         r['state'],
                'state_label':   state_sel.get(r['state'], r['state']),
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
                'dispatch_enabled': dispatch_enabled, 'period_kpis': period}

    @api.model
    def _inventory_period_kpis(self, company, cfg, warehouse_ids, date_from, date_to,
                               dt_from, dt_to, picking_type_ids=None):
        """Entregado / tasa del rango de la tabla.

        Mismos filtros que la tabla: el rango de fechas se aplica a la fecha
        de validación (date_done) y los depósitos son los de su barra. Sin
        rango, el entregado abarca todo el histórico visible; la tasa
        requiere rango completo (sus meses salen del consolidado/snapshots)
        y sin él queda sin calcular.

        Con tipos de operación seleccionados, el "validado del período" cuenta
        los remitos validados de ESOS tipos (sea recolección, embalaje o
        salida); sin selección cuenta solo las salidas — el eslabón final —
        para que la misma mercadería no se duplique por cada eslabón que
        atraviesa. La tasa conserva siempre su semántica de salidas.

        :returns: dict — delivered_qty/_pickings, rate_available(_num/_den).
        """
        dom = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
        ] + ([('picking_type_id', 'in', picking_type_ids)] if picking_type_ids
             else [('picking_type_code', '=', 'outgoing')]) \
          + self._inventory_wh_domain(warehouse_ids)
        if dt_from:
            dom.append(('date_done', '>=', dt_from))
        if dt_to:
            dom.append(('date_done', '<', dt_to))
        delivered_picks = self.env['stock.picking'].sudo().search(dom)
        delivered_qty = 0.0
        if delivered_picks:
            d_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', delivered_picks.ids),
                ('state', '=', 'done'),
            ])
            delivered_qty = sum(r['quantity'] or 0.0
                                for r in d_moves.read(['quantity']))
        rate = rate_num = rate_den = None
        if cfg and cfg.dispatch_stock_log_enabled and date_from and date_to:
            trend = self._inventory_rate_trend(
                company, fields.Date.from_string(date_from),
                fields.Date.from_string(date_to), warehouse_ids, cfg,
                picking_type_ids=picking_type_ids)
            rate_num = sum(m['num'] for m in trend)
            rate_den = rate_num + sum(m['den_extra'] for m in trend)
            rate = round(rate_num / rate_den * 100, 1) if rate_den > 0 else None
        qround = lambda v: self._inventory_qround(cfg, v)
        return {
            'delivered_qty':      qround(delivered_qty),
            'delivered_pickings': len(delivered_picks),
            'rate_available':     rate,
            'rate_available_num': qround(rate_num) if rate_num is not None else None,
            'rate_available_den': qround(rate_den) if rate_den is not None else None,
        }

    # ── Hooks del circuito de despacho ────────────────────────────────────────
    # El circuito es una extensión opcional (odoo_mrp_planner_dispatch) que
    # redefine estos hooks; sin él, la tabla es de solo lectura y lista
    # únicamente los eslabones pendientes.

    @api.model
    def _inventory_dispatch_enabled(self):
        """True si el circuito de despacho está activo para la empresa."""
        return False

    @api.model
    def _inventory_ready_leaf(self):
        """Hoja de dominio de la cola operativa "Validado s/ despachar"
        (None = sin circuito: la tabla no lista salidas validadas)."""
        return None

    @api.model
    def _inventory_can_dispatch(self):
        """True si el usuario puede despachar desde la tabla del panel."""
        return False

    # ── Drills (Ver → de los KPIs) ────────────────────────────────────────────

    # Nota: los drills de los KPIs de pendiente se arman en el cliente con los
    # ids exactos de las filas visibles (openPending del widget) — un dominio
    # servidor no puede replicar búsqueda, filtros, pestaña y selección.

    @api.model
    def action_inventory_delivered(self, period_from=None, period_to=None,
                                   warehouse_ids=None, picking_type_ids=None):
        """Lista nativa de remitos validados del período: mismos filtros que
        la card — rango de la tabla sobre la fecha de validación (date_done),
        sus depósitos y sus tipos (sin tipos seleccionados: solo salidas).
        Fechas opcionales."""
        self._inventory_ensure_group()
        tz = self._inventory_tz()
        to_utc = lambda d: tz.localize(datetime.combine(d, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        dom = [
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'done'),
        ] + ([('picking_type_id', 'in', picking_type_ids)] if picking_type_ids
             else [('picking_type_code', '=', 'outgoing')]) \
          + self._inventory_wh_domain(self._inventory_effective_whs(warehouse_ids))
        if period_from:
            dom.append(('date_done', '>=', to_utc(fields.Date.from_string(period_from))))
        if period_to:
            dom.append(('date_done', '<',
                        to_utc(fields.Date.from_string(period_to) + timedelta(days=1))))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Validados del período'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'views': [[False, 'list'], [False, 'form']],
            'domain': dom,
            # Lista propia de los drills: remito + cantidad por línea con total
            'context': {'create': False,
                        'list_view_ref': 'odoo_mrp_planner.view_picking_list_planner_drill'},
            'target': 'current',
        }
