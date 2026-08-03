"""
Módulo: mrp_dispatch_stock_log.py (odoo_mrp_planner_dispatch)
Modelos: mrp.dispatch.stock.log y mrp.planner.kpi.monthly

Snapshots diarios de disponibilidad de stock de las salidas pendientes y
consolidado mensual de KPIs. Alimentan la "Tasa física s/ disponible" del
Panel de Inventario: el mes en curso se calcula desde los snapshots crudos;
los meses cerrados se leen del consolidado, que nunca se purga.

Ciclo del cron diario (_cron_dispatch_snapshot):
1. Snapshot: una fila por remito-producto pendiente con su cantidad
   pendiente y disponible (idempotente: la corrida del día reemplaza).
   La disponibilidad se evalúa siguiendo la cadena de abastecimiento de
   cada movimiento (_chain_available_qty), y las salidas más viejas que
   el corte de antigüedad configurado quedan fuera.
2. Cierre mensual: consolida en mrp.planner.kpi.monthly los meses
   anteriores que aún no tengan su fila resumen.
3. Retención: purga snapshots crudos más viejos que la retención
   configurada, SOLO si su mes ya está consolidado.

Relacionado con:
- mrp.reschedule.config: dispatch_stock_log_enabled / dispatch_snapshot_hour /
  dispatch_log_retention_months (agregados por este módulo).
- mrp.planner.run.log: cada corrida del cron queda en el historial.
- stock.picking (x_dispatch_state / x_dispatch_date): definen el numerador.
"""
import logging
from datetime import datetime, time as dt_time, timedelta

import pytz

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

PENDING_PICKING_STATES = ('confirmed', 'waiting', 'assigned')


class MrpDispatchStockLog(models.Model):
    _name = 'mrp.dispatch.stock.log'
    _description = 'Snapshot diario de disponibilidad para despacho'
    _order = 'snapshot_date desc, id desc'

    snapshot_date = fields.Date(string='Fecha del snapshot', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Empresa', required=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Depósito', index=True)
    picking_id = fields.Many2one('stock.picking', string='Remito', required=True,
                                 index=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Artículo', required=True,
                                 index=True, ondelete='cascade')
    qty_pending = fields.Float(string='Cantidad pendiente', digits='Product Unit of Measure',
                               help='Cantidad demandada por el remito para el artículo al momento del snapshot.')
    qty_reserved = fields.Float(string='Cantidad reservada', digits='Product Unit of Measure',
                                help='Cantidad disponible para despachar al momento del snapshot, topeada '
                                     'a la pendiente. Se evalúa siguiendo la cadena de abastecimiento del '
                                     'movimiento hacia atrás (move_orig_ids): en entregas de 2/3 pasos '
                                     'cuenta lo reservado en el eslabón pendiente más temprano de la '
                                     'cadena, más lo que ya avanzó.')

    # ── Helpers de calendario ─────────────────────────────────────────────────

    @api.model
    def _company_tz(self, company):
        """Zona horaria de la empresa (fallback usuario / UTC) para atribuir meses."""
        tz_name = company.partner_id.tz or self.env.user.tz or 'UTC'
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.utc

    @api.model
    def _month_utc_bounds(self, year, month, company):
        """Límites del mes local de la empresa como Datetimes naive en UTC."""
        tz = self._company_tz(company)
        start_local = tz.localize(datetime(year, month, 1))
        if month == 12:
            end_local = tz.localize(datetime(year + 1, 1, 1))
        else:
            end_local = tz.localize(datetime(year, month + 1, 1))
        to_utc = lambda d: d.astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(start_local), to_utc(end_local)

    # ── Disponibilidad de cadena ──────────────────────────────────────────────

    @api.model
    def _chain_available_qty(self, moves):
        """Disponibilidad de movimientos de salida evaluada en el primer eslabón.

        Regla de negocio: en depósitos con entregas en 2/3 pasos, el movimiento
        de la salida es el último eslabón y recién reserva stock cuando la
        recolección terminó; mirar solo su `quantity` marca "sin stock"
        mercadería que ya está reservada al inicio de la cadena. Por eso la
        disponibilidad de cada movimiento se evalúa hacia atrás por
        `move_orig_ids`:

            disponible(m) = min(demanda(m), reservado(m) + Σ disponible(o))
            para cada origen o pendiente (state not in done/cancel).

        Los orígenes hechos/cancelados no suman: su salida ya está reflejada
        en el reservado de m. Para movimientos sin cadena (depósitos de 1 paso)
        el resultado es min(demanda, reservado), igual que la lectura directa.

        Implementación batch: BFS por niveles con sudo().read() (una consulta
        por nivel, profundidad máxima 6 eslabones hacia atrás) y evaluación
        memoizada con protección contra ciclos (un eslabón que reaparece en el
        camino aporta 0). No hay browse individual por registro.

        :param moves: recordset de stock.move (movimientos de salida).
        :returns: dict {move_id: cantidad disponible}.
        """
        move_ids = list(moves.ids)
        if not move_ids:
            return {}
        Move = self.env['stock.move'].sudo()

        # BFS por niveles: nivel 0 = los movimientos pedidos, hasta 6 niveles
        # de orígenes. Lo que quede más profundo se trata como aporte 0.
        info = {}  # {move_id: {'qty', 'demand', 'state', 'origs'}}
        frontier = move_ids
        for _depth in range(7):
            unread = [m for m in frontier if m not in info]
            if not unread:
                break
            frontier = []
            for r in Move.browse(unread).read(
                    ['move_orig_ids', 'quantity', 'product_uom_qty', 'state']):
                info[r['id']] = {
                    'qty':    r['quantity'] or 0.0,
                    'demand': r['product_uom_qty'] or 0.0,
                    'state':  r['state'],
                    'origs':  r['move_orig_ids'],
                }
                # Los orígenes done/cancel no se evalúan: no hace falta expandirlos.
                if r['state'] not in ('done', 'cancel'):
                    frontier.extend(r['move_orig_ids'])

        # Evaluación iterativa en post-orden con memo compartida entre raíces.
        memo = {}
        for root in move_ids:
            if root in memo or root not in info:
                continue
            onpath = set()  # camino actual: protege contra ciclos
            stack = [(root, False)]
            while stack:
                mid, processed = stack.pop()
                if processed:
                    onpath.discard(mid)
                    node = info[mid]
                    total = node['qty']
                    for o in node['origs']:
                        onode = info.get(o)
                        if onode and onode['state'] not in ('done', 'cancel'):
                            total += memo.get(o, 0.0)
                    memo[mid] = min(node['demand'], total)
                    continue
                if mid in memo or mid in onpath or mid not in info:
                    continue
                onpath.add(mid)
                stack.append((mid, True))
                for o in info[mid]['origs']:
                    onode = info.get(o)
                    if (onode and onode['state'] not in ('done', 'cancel')
                            and o not in memo and o not in onpath):
                        stack.append((o, False))
        return {m: memo.get(m, 0.0) for m in move_ids}

    # ── Cron ──────────────────────────────────────────────────────────────────

    @api.model
    def _cron_dispatch_snapshot(self):
        """Corrida diaria: snapshot + cierre mensual + retención, por empresa."""
        Config = self.env['mrp.reschedule.config'].sudo()
        for company in self.env['res.company'].sudo().search([]):
            cfg = Config.with_company(company).get_config()
            if not (cfg and cfg.enable_dispatch_validation and cfg.dispatch_stock_log_enabled):
                continue
            started = fields.Datetime.now()
            try:
                count = self._dispatch_take_snapshot(company, cfg)
                months = self._dispatch_consolidate_months(company)
                purged = self._dispatch_apply_retention(company, cfg)
                duration = (fields.Datetime.now() - started).total_seconds()
                parts = [f'{count} líneas registradas']
                if months:
                    parts.append(f'{months} mes(es) consolidado(s)')
                if purged:
                    parts.append(f'{purged} snapshots purgados')
                self.env['mrp.planner.run.log'].log_run(
                    'dispatch_snapshot', trigger='cron', status='ok',
                    updated=count, duration=duration,
                    message=', '.join(parts) + '.', company=company)
            except Exception as e:
                _logger.exception('Despacho: falló el snapshot de disponibilidad de %s',
                                  company.name)
                duration = (fields.Datetime.now() - started).total_seconds()
                self.env['mrp.planner.run.log'].log_run(
                    'dispatch_snapshot', trigger='cron', status='error',
                    duration=duration, message=str(e), company=company)

    # ── Paso 1: snapshot del día ──────────────────────────────────────────────

    @api.model
    def _dispatch_take_snapshot(self, company, cfg=None):
        """Registra pendiente vs. disponible por remito-producto de las salidas pendientes.

        La disponibilidad se evalúa en el primer eslabón de la cadena de cada
        movimiento (_chain_available_qty), topeada a la pendiente. Las salidas
        con fecha programada más vieja que el corte de antigüedad configurado
        no se registran.

        Idempotente por día: si el cron (o una corrida manual) vuelve a pasar,
        el snapshot del día se reemplaza con el estado más reciente.

        :param cfg: registro de mrp.reschedule.config de la empresa (se
                    resuelve al vuelo si no viene).
        :returns: int — filas creadas.
        """
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].sudo().with_company(company).get_config()
        today = fields.Date.context_today(self.with_context(tz=str(self._company_tz(company))))
        stale = self.sudo().search([
            ('snapshot_date', '=', today),
            ('company_id', '=', company.id),
        ])
        if stale:
            stale.unlink()

        # sudo(): mismo criterio que las demás lecturas de stock del planificador.
        moves = self.env['stock.move'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('picking_id.state', 'in', PENDING_PICKING_STATES),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + cfg._dispatch_pending_cutoff_domain('picking_id.scheduled_date'))
        if not moves:
            return 0
        move_rows = moves.read(['picking_id', 'product_id', 'product_uom_qty'])
        # Disponibilidad evaluada en el primer eslabón de la cadena de cada movimiento
        chain_avail = self._chain_available_qty(moves)

        # Depósito por picking en dos SELECT (picking → tipo → depósito)
        pick_ids = list({r['picking_id'][0] for r in move_rows if r['picking_id']})
        pick_type = {p['id']: p['picking_type_id'][0] if p['picking_type_id'] else False
                     for p in self.env['stock.picking'].sudo().browse(pick_ids).read(['picking_type_id'])}
        type_ids = list({t for t in pick_type.values() if t})
        type_wh = {t['id']: t['warehouse_id'][0] if t['warehouse_id'] else False
                   for t in self.env['stock.picking.type'].sudo().browse(type_ids).read(['warehouse_id'])}

        # Agregar por remito-producto (un remito puede tener varias líneas del mismo artículo)
        agg = {}  # {(picking_id, product_id): [pending, available]}
        for r in move_rows:
            pick = r['picking_id'][0] if r['picking_id'] else False
            prod = r['product_id'][0] if r['product_id'] else False
            if not pick or not prod:
                continue
            key = (pick, prod)
            agg.setdefault(key, [0.0, 0.0])
            agg[key][0] += r['product_uom_qty'] or 0.0
            agg[key][1] += chain_avail.get(r['id'], 0.0)

        vals_list = []
        for (pick, prod), (pending, available) in agg.items():
            vals_list.append({
                'snapshot_date': today,
                'company_id':    company.id,
                'warehouse_id':  type_wh.get(pick_type.get(pick)) or False,
                'picking_id':    pick,
                'product_id':    prod,
                'qty_pending':   round(pending, 2),
                # Topeada a la pendiente: el excedente disponible no suma
                'qty_reserved':  round(min(available, pending), 2),
            })
        if vals_list:
            self.sudo().create(vals_list)
        return len(vals_list)

    # ── Paso 2: cierre mensual ────────────────────────────────────────────────

    @api.model
    def _dispatch_consolidate_months(self, company):
        """Consolida en mrp.planner.kpi.monthly los meses anteriores con snapshots
        que aún no tengan su fila resumen (la fila sin producto ni depósito actúa
        como marcador de mes cerrado y como agregado global de lectura rápida).

        :returns: int — meses consolidados en esta pasada.
        """
        Monthly = self.env['mrp.planner.kpi.monthly'].sudo()
        tz = self._company_tz(company)
        today_local = datetime.now(pytz.utc).astimezone(tz).date()
        current_month_start = today_local.replace(day=1)

        self.env.cr.execute("""
            SELECT DISTINCT date_trunc('month', snapshot_date)::date
              FROM mrp_dispatch_stock_log
             WHERE company_id = %s AND snapshot_date < %s
        """, (company.id, current_month_start))
        months = [r[0] for r in self.env.cr.fetchall()]

        done = 0
        for month_start in sorted(months):
            marker = Monthly.search_count([
                ('kpi', '=', 'dispatch_available'),
                ('company_id', '=', company.id),
                ('period', '=', month_start),
                ('product_id', '=', False),
                ('warehouse_id', '=', False),
            ])
            if marker:
                continue
            self._dispatch_consolidate_one_month(company, month_start)
            done += 1
        return done

    @api.model
    def _dispatch_consolidate_one_month(self, company, month_start):
        """Congela un mes: numerador (despachado en el mes) y denominador extra
        (disponible en algún snapshot del mes y no despachado hasta fin de mes),
        por depósito y producto, más la fila resumen global."""
        Monthly = self.env['mrp.planner.kpi.monthly'].sudo()
        dt_from, dt_to = self._month_utc_bounds(month_start.year, month_start.month, company)

        # ── Numerador: despachado en el mes (por fecha de despacho) ──────────
        dispatched_picks = self.env['stock.picking'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_type_code', '=', 'outgoing'),
            ('x_dispatch_state', '=', 'dispatched'),
            ('x_dispatch_date', '>=', dt_from),
            ('x_dispatch_date', '<', dt_to),
        ])
        num = {}  # {(warehouse_id, product_id): qty}
        if dispatched_picks:
            wh_by_pick = {p.id: p.picking_type_id.warehouse_id.id or False
                          for p in dispatched_picks}
            d_moves = self.env['stock.move'].sudo().search([
                ('picking_id', 'in', dispatched_picks.ids),
                ('state', '=', 'done'),
            ])
            for r in d_moves.read(['picking_id', 'product_id', 'quantity']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                prod = r['product_id'][0] if r['product_id'] else False
                if not pick or not prod:
                    continue
                key = (wh_by_pick.get(pick) or False, prod)
                num[key] = num.get(key, 0.0) + (r['quantity'] or 0.0)

        # ── Denominador extra: máxima reserva vista en el mes por remito-línea,
        #    excluyendo lo despachado hasta fin de mes (ya es numerador de algún mes) ──
        month_end = (month_start.replace(day=28) + timedelta(days=6)).replace(day=1)
        logs = self.sudo().search([
            ('company_id', '=', company.id),
            ('snapshot_date', '>=', month_start),
            ('snapshot_date', '<', month_end),
            ('qty_reserved', '>', 0),
        ])
        den = {}  # {(warehouse_id, product_id): qty}
        if logs:
            log_rows = logs.read(['picking_id', 'product_id', 'warehouse_id', 'qty_reserved'])
            log_pick_ids = list({r['picking_id'][0] for r in log_rows if r['picking_id']})
            dispatched_by_eom = set()
            if log_pick_ids:
                dispatched_by_eom = set(self.env['stock.picking'].sudo().search([
                    ('id', 'in', log_pick_ids),
                    ('x_dispatch_state', '=', 'dispatched'),
                    ('x_dispatch_date', '<', dt_to),
                ]).ids)
            best = {}  # {(picking, product): (warehouse, max_reserved)}
            for r in log_rows:
                pick = r['picking_id'][0] if r['picking_id'] else False
                prod = r['product_id'][0] if r['product_id'] else False
                if not pick or not prod or pick in dispatched_by_eom:
                    continue
                wh = r['warehouse_id'][0] if r['warehouse_id'] else False
                key = (pick, prod)
                if key not in best or r['qty_reserved'] > best[key][1]:
                    best[key] = (wh, r['qty_reserved'])
            for (_pick, prod), (wh, qty) in best.items():
                den[(wh, prod)] = den.get((wh, prod), 0.0) + qty

        # ── Filas por depósito-producto + fila resumen (marcador) ────────────
        vals_list = []
        for key in set(num) | set(den):
            wh, prod = key
            vals_list.append({
                'kpi':           'dispatch_available',
                'period':        month_start,
                'company_id':    company.id,
                'warehouse_id':  wh,
                'product_id':    prod,
                'qty_num':       round(num.get(key, 0.0), 2),
                'qty_den_extra': round(den.get(key, 0.0), 2),
            })
        vals_list.append({
            'kpi':           'dispatch_available',
            'period':        month_start,
            'company_id':    company.id,
            'warehouse_id':  False,
            'product_id':    False,
            'qty_num':       round(sum(num.values()), 2),
            'qty_den_extra': round(sum(den.values()), 2),
        })
        Monthly.create(vals_list)
        _logger.info('Despacho: mes %s consolidado para %s (%s filas).',
                     month_start.strftime('%Y-%m'), company.name, len(vals_list))

    # ── Paso 3: retención ─────────────────────────────────────────────────────

    @api.model
    def _dispatch_apply_retention(self, company, cfg):
        """Purga snapshots más viejos que la retención, solo de meses ya consolidados.

        :returns: int — filas eliminadas.
        """
        months_keep = max(1, int(cfg.dispatch_log_retention_months or 12))
        tz = self._company_tz(company)
        today_local = datetime.now(pytz.utc).astimezone(tz).date()
        # Primer día del mes N meses atrás: todo lo anterior es purgable
        year = today_local.year + (today_local.month - 1 - months_keep) // 12
        month = (today_local.month - 1 - months_keep) % 12 + 1
        cutoff = today_local.replace(year=year, month=month, day=1)

        self.env.cr.execute("""
            SELECT DISTINCT date_trunc('month', snapshot_date)::date
              FROM mrp_dispatch_stock_log
             WHERE company_id = %s AND snapshot_date < %s
        """, (company.id, cutoff))
        purged = 0
        Monthly = self.env['mrp.planner.kpi.monthly'].sudo()
        for (month_start,) in self.env.cr.fetchall():
            consolidated = Monthly.search_count([
                ('kpi', '=', 'dispatch_available'),
                ('company_id', '=', company.id),
                ('period', '=', month_start),
                ('product_id', '=', False),
                ('warehouse_id', '=', False),
            ])
            if not consolidated:
                continue
            month_end = (month_start.replace(day=28) + timedelta(days=6)).replace(day=1)
            stale = self.sudo().search([
                ('company_id', '=', company.id),
                ('snapshot_date', '>=', month_start),
                ('snapshot_date', '<', month_end),
            ])
            purged += len(stale)
            stale.unlink()
        return purged


class MrpPlannerKpiMonthly(models.Model):
    _name = 'mrp.planner.kpi.monthly'
    _description = 'KPIs mensuales consolidados del planificador'
    _order = 'period desc, id'

    kpi = fields.Selection([
        ('dispatch_available', 'Tasa física s/ disponible'),
    ], string='KPI', required=True, index=True)
    period = fields.Date(string='Mes', required=True, index=True,
                         help='Primer día del mes consolidado.')
    company_id = fields.Many2one('res.company', string='Empresa', required=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Depósito',
                                   help='Vacío en la fila resumen global del mes.')
    product_id = fields.Many2one('product.product', string='Artículo', ondelete='cascade',
                                 help='Vacío en la fila resumen global del mes.')
    qty_num = fields.Float(string='Numerador', digits='Product Unit of Measure',
                           help='Tasa física s/ disponible: cantidad despachada en el mes.')
    qty_den_extra = fields.Float(string='Denominador extra', digits='Product Unit of Measure',
                                 help='Tasa física s/ disponible: cantidad que estuvo disponible '
                                      'en algún snapshot del mes y no se despachó.')
    rate = fields.Float(string='Tasa (%)', compute='_compute_rate', digits=(12, 1))

    _sql_constraints = [
        ('kpi_period_uniq',
         'unique(kpi, period, company_id, warehouse_id, product_id)',
         'Ya existe una fila consolidada para ese KPI, mes, empresa, depósito y artículo.'),
    ]

    @api.depends('qty_num', 'qty_den_extra')
    def _compute_rate(self):
        for rec in self:
            total = rec.qty_num + rec.qty_den_extra
            rec.rate = round(rec.qty_num / total * 100, 1) if total > 0 else 0.0
