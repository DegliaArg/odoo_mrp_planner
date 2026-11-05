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
  El universo se define por los tipos de operación (entradas, internas y
  cadena de entrega) de cada depósito; "Con stock" = la cantidad reservada de
  cada movimiento cuyo ESTADO cuenta como con stock en Ajustes → Inventario
  (_inventory_state_stock_map), y las líneas más viejas que el corte de
  antigüedad configurado quedan fuera de todo el panel.
- state='done' / date_done: entregado del período y atraso de entrega.
- mrp.dispatch.stock.log: disponible pendiente que forma el denominador de la
  "Tasa de entrega". La tasa se calcula EN VIVO desde los snapshots (no hay
  consolidado congelado): meses más viejos que la retención no tienen tasa.

Todas las lecturas de stock/ventas usan sudo() con guard de grupo previo,
mismo criterio que el análisis de clientes.
"""
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api, _


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
    def _inventory_universe_types(self, company, warehouse_ids=None):
        """Tipos de operación del universo del panel: entradas, internas y
        salidas de los depósitos visibles. Los eslabones de la cadena de
        entrega conservan su etapa (pick/pack/ship); el resto se etiqueta
        'in' (recepción) o 'int' (transferencia interna).

        :returns: (type_ids, info) — info = {type_id: (wh_id, wh_name, stage,
                  display_name)}.
        """
        _ids, chain_info = self.env['mrp.dispatch.stock.log'] \
            ._dispatch_chain_types(company, warehouse_ids)
        dom = [('company_id', '=', company.id),
               ('code', 'in', ('incoming', 'internal', 'outgoing'))]
        if warehouse_ids:
            dom.append(('warehouse_id', 'in', warehouse_ids))
        info = {}
        # active_test=False: los tipos ARCHIVADOS también entran — sus remitos
        # históricos los siguen referenciando y sin ellos el panel excluiría
        # operaciones reales (y no cerraría contra los análisis nativos).
        Type = self.env['stock.picking.type'].sudo().with_context(active_test=False)
        for t in Type.search(dom).read(['display_name', 'code', 'warehouse_id']):
            chain = chain_info.get(t['id'])
            if chain:
                stage = chain[2]
            elif t['code'] == 'incoming':
                stage = 'in'
            elif t['code'] == 'internal':
                stage = 'int'
            else:
                stage = 'ship'
            info[t['id']] = (t['warehouse_id'][0] if t['warehouse_id'] else False,
                             t['warehouse_id'][1] if t['warehouse_id'] else '',
                             stage, t['display_name'])
        return list(info), info

    @api.model
    def get_inventory_picking_types(self, warehouse_ids=None):
        """Tipos de operación para los filtros del panel: los del universo
        (entradas, internas y salidas de los depósitos visibles) que sigan
        ACTIVOS. El universo incluye tipos archivados para no perder remitos
        históricos en el cálculo (ver _inventory_universe_types), pero el
        selector no debe ofrecer tipos ya archivados como opción de filtro.

        :returns: list[dict] — {'id', 'name'} ordenados por nombre.
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        _ids, info = self._inventory_universe_types(
            self.env.company, warehouse_ids or None)
        # active_test=True por defecto: deja fuera los tipos archivados.
        active_ids = set(self.env['stock.picking.type'].sudo()
                         .search([('id', 'in', list(info))]).ids)
        return sorted(({'id': t, 'name': i[3]}
                       for t, i in info.items() if t in active_ids),
                      key=lambda d: d['name'])

    @api.model
    def _inventory_chain_types(self, company, warehouse_ids, picking_type_ids):
        """Tipos de operación de la CADENA de entrega (recolección/embalaje/
        salida) de los depósitos visibles, acotados al filtro de tipo de
        operación si se pasa. La Tasa de entrega se calcula sobre estos
        eslabones: a diferencia de antes, SÍ respeta el filtro (recolección,
        embalaje o entrega dan cada uno su propia tasa)."""
        chain_ids, _info = self.env['mrp.dispatch.stock.log'].sudo() \
            ._dispatch_chain_types(company, warehouse_ids or None)
        if picking_type_ids:
            chain_ids = [t for t in chain_ids if t in picking_type_ids]
        return chain_ids

    @api.model
    def _inventory_delivery_figures(self, company, d_from, d_to, dt_from, dt_to,
                                    warehouse_ids, type_ids, method):
        """Numerador y parte pendiente del denominador de la Tasa de entrega,
        por eslabón, en el rango exacto [d_from, d_to].

        - num (validado del período): operaciones VALIDADAS de los tipos
          ``type_ids`` con date_done en el rango — el MISMO número que la card
          "Validados del período" para esos tipos. Es "cuánto hice" del eslabón.
        - den_pending (lo que tuve stock y no hice): disponible pendiente
          (qty_reserved) de esos tipos, de los snapshots del rango, agregado
          según ``method`` (closing/peak/average) y excluyendo lo que terminó
          validado en el rango (ya cuenta en num). Es ``None`` si el rango NO
          tiene ningún snapshot (registro recién activado, o empresa sin
          registro): el denominador es desconocido y la tasa no se puede calcular.

        :returns: (num, den_pending) — den_pending float, o None si no hay
            snapshots en el rango.
        """
        if not type_ids:
            return 0.0, 0.0
        Picking = self.env['stock.picking'].sudo()
        Move = self.env['stock.move'].sudo()

        # ── Numerador: validado del período (cantidad hecha de los tipos) ──
        done_dom = [
            ('company_id', '=', company.id),
            ('picking_type_id', 'in', type_ids),
            ('state', '=', 'done'),
            ('date_done', '>=', dt_from), ('date_done', '<', dt_to),
        ]
        if warehouse_ids:
            done_dom.append(('picking_type_id.warehouse_id', 'in', warehouse_ids))
        done_picks = Picking.search(done_dom)
        num = 0.0
        if done_picks:
            d_moves = Move.search([('picking_id', 'in', done_picks.ids),
                                   ('state', '=', 'done')])
            num = sum(r['quantity'] or 0.0 for r in d_moves.read(['quantity']))

        # ── Denominador pendiente: disponible no hecho de esos tipos ──
        den_pending = self._inventory_pending_available(
            company, d_from, d_to, warehouse_ids, type_ids, method,
            exclude_pick_ids=set(done_picks.ids))
        return num, den_pending

    @api.model
    def _inventory_pending_available(self, company, d_from, d_to, warehouse_ids,
                                     type_ids, method, exclude_pick_ids=None):
        """Parte pendiente del denominador de la Tasa de entrega: disponible
        (qty_reserved) de las operaciones pendientes de ``type_ids`` en los
        snapshots del rango, que NO terminó validado, agregado según ``method``:

        - closing (default): disponible del ÚLTIMO snapshot del rango (foto al
          cierre) — lo que al final seguía pendiente con stock para hacer.
        - peak: máximo por (remito, producto) visto en el rango.
        - average: promedio diario del disponible pendiente.

        El snapshot no guarda el tipo de operación: se resuelve vía el remito.

        :returns: float con el disponible pendiente, o ``None`` si el rango no
            tiene NINGÚN snapshot (denominador desconocido). Un rango CON
            snapshots pero sin pendiente-con-stock de ese eslabón devuelve 0.0.
        """
        Log = self.env['mrp.dispatch.stock.log'].sudo()
        scope_dom = [
            ('company_id', '=', company.id),
            ('snapshot_date', '>=', d_from), ('snapshot_date', '<=', d_to),
        ]
        if warehouse_ids:
            scope_dom.append(('warehouse_id', 'in', warehouse_ids))
        # Sin NINGÚN snapshot en el rango: el denominador es desconocido (no es 0).
        if not Log.search_count(scope_dom):
            return None
        logs = Log.search(scope_dom + [('qty_reserved', '>', 0)])
        if not logs:
            return 0.0
        rows = logs.read(['snapshot_date', 'picking_id', 'product_id', 'qty_reserved'])
        pick_ids = {r['picking_id'][0] for r in rows if r['picking_id']}
        ptype = {p['id']: (p['picking_type_id'][0] if p['picking_type_id'] else False)
                 for p in self.env['stock.picking'].sudo()
                              .browse(list(pick_ids)).read(['picking_type_id'])}
        type_set = set(type_ids)
        excl = exclude_pick_ids or set()
        rows = [r for r in rows
                if r['picking_id'] and ptype.get(r['picking_id'][0]) in type_set
                and r['picking_id'][0] not in excl]
        if not rows:
            return 0.0
        if method == 'peak':
            best = {}
            for r in rows:
                k = (r['picking_id'][0], r['product_id'][0] if r['product_id'] else 0)
                if r['qty_reserved'] > best.get(k, 0.0):
                    best[k] = r['qty_reserved']
            return sum(best.values())
        if method == 'average':
            by_date = defaultdict(float)
            for r in rows:
                by_date[r['snapshot_date']] += r['qty_reserved']
            return sum(by_date.values()) / len(by_date) if by_date else 0.0
        # closing (default): disponible del último snapshot del rango.
        last_date = max(r['snapshot_date'] for r in rows)
        return sum(r['qty_reserved'] for r in rows if r['snapshot_date'] == last_date)

    # ── Llamada 2: tabla operativa ────────────────────────────────────────────

    @api.model
    def get_inventory_pending_table(self, date_from=None, date_to=None,
                                    warehouse_ids=None, search='',
                                    picking_type_ids=None):
        """
        Análisis de entregas del rango (una fila por remito), en TODOS los
        estados. El universo cubre todos los eslabones de la cadena de
        entrega de cada depósito — recolección, embalaje y salida:

        - PENDIENTES: por fecha programada de CADA LÍNEA (stock.move.date);
          un remito con líneas en fechas distintas entra solo con las líneas
          del rango y sus cantidades. Corte de antigüedad por línea.
        - HECHOS: por fecha de validación (date_done) dentro del rango. Con
          el circuito de despacho activo, los que esperan despacho llevan
          etapa 'ready' (los únicos marcables como despachados).
        - CANCELADOS: por fecha programada de cabecera dentro del rango;
          muestran su demanda original y no suman a ninguna card.

        El rango de fechas es obligatorio en el widget (default mes en
        curso); sin rango, defensivamente solo se listan pendientes.

        :returns: dict {'rows': list[dict], 'can_dispatch': bool,
                        'dispatch_enabled': bool, 'period_kpis': dict}
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        dispatch_enabled = self._inventory_dispatch_enabled()

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
        chain_type_ids, type_info = self._inventory_universe_types(
            company, warehouse_ids or None)

        # La tasa (única métrica que necesita snapshots) viaja como period_kpis;
        # los validados son filas de la tabla y sus KPIs se calculan en el
        # cliente. La tasa ahora es POR ESLABÓN: respeta el filtro de tipo de
        # operación (su numerador = los validados de esos tipos) y el depósito.
        period = self._inventory_period_kpis(company, cfg, warehouse_ids,
                                             date_from, date_to, picking_type_ids)

        if picking_type_ids:
            type_info = {t: info for t, info in type_info.items()
                         if t in picking_type_ids}
            chain_type_ids = list(type_info)
        empty = {'rows': [], 'can_dispatch': self._inventory_can_dispatch(),
                 'dispatch_enabled': dispatch_enabled, 'period_kpis': period}
        if not chain_type_ids:
            return empty

        # Clasificación Con/Sin stock por estado del movimiento (Ajustes); sus
        # claves son además los estados pendientes que considera el panel.
        smap = cfg._inventory_state_stock_map()

        # ── Líneas pendientes, filtradas por ESTADO DEL MOVIMIENTO (como el
        #    análisis de movimientos nativo) y por su fecha programada ──
        move_dom = [
            ('company_id', '=', company.id),
            ('picking_id.picking_type_id', 'in', chain_type_ids),
            ('state', 'in', list(smap)),
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

        # ── Hechos del rango (por fecha de validación) y cancelados (por
        #    fecha programada de cabecera). El rango es obligatorio en el
        #    widget: sin él, defensivamente no se cargan estos universos. ──
        Picking = self.env['stock.picking'].sudo()
        search_dom = ['|', ('name', 'ilike', search),
                      ('origin', 'ilike', search)] if search else []
        done_picks = Picking
        cancel_picks = Picking
        if dt_from or dt_to:
            done_dom = [
                ('company_id', '=', company.id),
                ('picking_type_id', 'in', chain_type_ids),
                ('state', '=', 'done'),
            ] + search_dom
            if dt_from:
                done_dom.append(('date_done', '>=', dt_from))
            if dt_to:
                done_dom.append(('date_done', '<', dt_to))
            done_picks = Picking.search(done_dom)
            cancel_dom = [
                ('company_id', '=', company.id),
                ('picking_type_id', 'in', chain_type_ids),
                ('state', '=', 'cancel'),
            ] + search_dom
            if dt_from:
                cancel_dom.append(('scheduled_date', '>=', dt_from))
            if dt_to:
                cancel_dom.append(('scheduled_date', '<', dt_to))
            cancel_picks = Picking.search(cancel_dom)

        # Cantidades por remito: [pendiente, disponible, {producto}, fecha
        # mínima de línea, hecha]
        qty = {}    # {pick_id: [pending, available, {product_id: name}, min_date, done]}
        if moves:
            for r in moves.read(['picking_id', 'product_id', 'product_uom_qty',
                                 'date', 'state', 'quantity']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                entry = qty.setdefault(pick, [0.0, 0.0, {}, None, 0.0])
                q = r['product_uom_qty'] or 0.0
                # Con stock = cantidad reservada del movimiento si su estado
                # cuenta como con stock en Ajustes; el resto es sin stock.
                avail = min(r['quantity'] or 0.0, q) if smap.get(r['state']) == 'con' else 0.0
                entry[0] += q
                entry[1] += avail
                if r['product_id']:
                    entry[2][r['product_id'][0]] = r['product_id'][1]
                if r['date'] and (entry[3] is None or r['date'] < entry[3]):
                    entry[3] = r['date']
        done_ids = set(done_picks.ids)
        if done_ids:
            done_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', list(done_ids)),
                ('state', '=', 'done'),
            ])
            for r in done_moves.read(['picking_id', 'product_id', 'quantity']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                entry = qty.setdefault(pick, [0.0, 0.0, {}, None, 0.0])
                q = r['quantity'] or 0.0
                entry[4] += q
                if r['product_id']:
                    entry[2][r['product_id'][0]] = r['product_id'][1]
        cancel_ids = set(cancel_picks.ids)
        if cancel_ids:
            # Canceladas: demanda original de las líneas (informativa)
            cancel_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', list(cancel_ids)),
                ('state', '=', 'cancel'),
            ])
            for r in cancel_moves.read(['picking_id', 'product_id', 'product_uom_qty']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                entry = qty.setdefault(pick, [0.0, 0.0, {}, None, 0.0])
                entry[0] += r['product_uom_qty'] or 0.0
                if r['product_id']:
                    entry[2][r['product_id'][0]] = r['product_id'][1]

        pending_ids = sorted(set(qty) - done_ids - cancel_ids)
        picks = self.env['stock.picking'].sudo().browse(
            pending_ids + sorted(done_ids) + sorted(cancel_ids))
        if not picks:
            return empty

        # Cola de despacho entre los hechos (hook del módulo de despacho)
        dispatch_queue = self._inventory_dispatch_queue_ids(list(done_ids))

        # sale_id (vía grupo de abastecimiento, sale_stock) resuelve el origen a
        # la venta en cualquier eslabón de la cadena; si no está el módulo o el
        # remito no viene de una venta, la columna Origen queda como texto plano.
        has_sale = 'sale_id' in picks._fields
        has_purchase = 'purchase_id' in picks._fields
        pick_rows = picks.read(['name', 'partner_id', 'origin', 'scheduled_date',
                                'state', 'picking_type_id', 'location_id',
                                'location_dest_id']
                               + (['sale_id'] if has_sale else [])
                               + (['purchase_id'] if has_purchase else []))

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
            'in':    _('Recepción'),
            'int':   _('Transferencia'),
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
            is_done = pid in done_ids
            is_cancel = pid in cancel_ids
            stage = 'ready' if pid in dispatch_queue else (info[2] if info else 'ship')
            pending, available, prods, min_date, done_qty = qty.get(
                pid, [0.0, 0.0, {}, None, 0.0])
            # Con/Sin stock ya vienen del criterio por estado del movimiento
            # (Ajustes → Inventario), recepciones incluidas.
            # Lista completa de artículos ordenada por nombre (links del widget);
            # los nombres ya vienen del read de los movimientos: sin queries extra.
            detail = sorted(({'id': p_id, 'name': p_name} for p_id, p_name in prods.items()),
                            key=lambda d: d['name'])
            names = [d['name'] for d in detail]
            # Fecha programada más próxima de las líneas consideradas; para
            # hechas/canceladas (sin fecha programada vigente) la de cabecera
            sched = min_date or r['scheduled_date']
            if sched:
                sched_local = pytz.utc.localize(sched).astimezone(tz)
                sched_str = sched_local.strftime('%d/%m/%Y')
                # Días vencidos por fecha calendario: 0 = vence HOY (cuenta
                # como vencida). Solo aplica a filas pendientes.
                overdue = ((today - sched_local.date()).days
                           if not (is_done or is_cancel) else None)
            else:
                sched_str, overdue = '', None
            avail_since = first_avail.get(pid) if not (is_done or is_cancel) else None
            rows.append({
                'picking_id':    pid,
                'name':          r['name'],
                'partner':       r['partner_id'][1] if r['partner_id'] else '',
                'origin':        r['origin'] or '',
                'origin_model':  ('purchase.order' if has_purchase and r.get('purchase_id')
                                  else 'sale.order' if has_sale and r.get('sale_id')
                                  else False),
                'origin_id':     (r['purchase_id'][0] if has_purchase and r.get('purchase_id')
                                  else r['sale_id'][0] if has_sale and r.get('sale_id')
                                  else False),
                'warehouse':     info[1] if info else '',
                'type_name':     info[3] if info else '',
                'loc_from':      r['location_id'][1] if r['location_id'] else '',
                'loc_to':        r['location_dest_id'][1] if r['location_dest_id'] else '',
                'scheduled':     sched_str,
                'overdue_days':  max(0, overdue) if overdue is not None else None,
                'state':         r['state'],
                'state_label':   state_sel.get(r['state'], r['state']),
                'stage':         stage,
                'stage_label':   stage_labels[stage],
                'qty_pending':   self._inventory_qround(cfg, pending),
                'qty_available': self._inventory_qround(cfg, available),
                'qty_done':      self._inventory_qround(cfg, done_qty),
                'products':      len(detail),
                'product_names': ', '.join(names[:3]) + ('…' if len(names) > 3 else ''),
                'products_detail': detail,
                'days_available': (today - avail_since).days if avail_since else None,
            })
        return {'rows': rows, 'can_dispatch': self._inventory_can_dispatch(),
                'dispatch_enabled': dispatch_enabled, 'period_kpis': period}

    @api.model
    def _inventory_period_kpis(self, company, cfg, warehouse_ids, date_from, date_to,
                               picking_type_ids=None):
        """Tasa de entrega del rango de la tabla, por eslabón (respeta el filtro
        de tipo de operación). num = validado del período de esos tipos — el
        MISMO número que la card "Validados del período"; den = num + disponible
        pendiente no hecho (método configurable en Ajustes). Requiere rango
        completo.

        Si el rango no tiene ningún snapshot (``den_pending`` None), la tasa es
        None y se marca ``rate_no_snapshots`` para que el panel lo diga explícito.

        :returns: dict — rate_available(_num/_den) + rate_no_snapshots.
        """
        rate = rate_num = rate_den = pending_avail = method = None
        no_snapshots = False
        if cfg and cfg.dispatch_stock_log_enabled and date_from and date_to:
            type_ids = self._inventory_chain_types(company, warehouse_ids, picking_type_ids)
            d_from, d_to, dt_from, dt_to = self._inventory_parse_range(date_from, date_to)
            method = cfg._inventory_denominator_method()
            num, den_pending = self._inventory_delivery_figures(
                company, d_from, d_to, dt_from, dt_to, warehouse_ids, type_ids, method)
            if den_pending is None:
                # Sin snapshots en el rango: el denominador es desconocido; se
                # muestra "—" en vez de un 100% engañoso.
                no_snapshots = bool(type_ids)
                rate_num = num
            else:
                rate_num = num
                pending_avail = den_pending
                rate_den = num + den_pending
                rate = round(rate_num / rate_den * 100, 1) if rate_den > 0 else None
        qround = lambda v: self._inventory_qround(cfg, v)
        return {
            'rate_available':         rate,
            'rate_available_num':     qround(rate_num) if rate_num is not None else None,
            'rate_available_den':     qround(rate_den) if rate_den is not None else None,
            # Parte pendiente del denominador (disponible no hecho del período,
            # según el método configurado) — su propia card.
            'rate_pending_available': qround(pending_avail) if pending_avail is not None else None,
            'rate_method':            method,
            'rate_no_snapshots':      no_snapshots,
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
    def _inventory_dispatch_queue_ids(self, picking_ids):
        """De los remitos hechos listados, cuáles esperan despacho (etapa
        'ready', los únicos marcables). Sin el módulo de despacho: ninguno."""
        return set()

    @api.model
    def _inventory_can_dispatch(self):
        """True si el usuario puede despachar desde la tabla del panel."""
        return False

    # ── Drills (Ver → de los KPIs) ────────────────────────────────────────────

    # Nota: los drills de los KPIs de pendiente se arman en el cliente con los
    # ids exactos de las filas visibles (openPending del widget) — un dominio
    # servidor no puede replicar búsqueda, filtros, pestaña y selección.

