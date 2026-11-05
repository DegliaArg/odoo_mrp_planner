"""
Módulo: mrp_dispatch_stock_log.py (odoo_mrp_planner)
Modelos: mrp.dispatch.stock.log y mrp.planner.kpi.monthly (legacy)

Snapshots diarios de disponibilidad de stock de las salidas pendientes.
Alimentan la "Tasa de entrega" del Panel de Inventario, que se calcula EN
VIVO desde estos snapshots (ya no hay consolidado mensual): meses más viejos
que la retención configurada no tienen tasa.

El panel usa solo datos estándar de Odoo: pendiente = demanda en los
eslabones de la cadena de entrega sin validar (por tipos de operación),
disponible = cantidad reservada siguiendo la cadena de abastecimiento. No
depende del circuito de despacho (x_dispatch_state), extensión opcional.

Ciclo del cron diario (_cron_dispatch_snapshot):
1. Snapshot: una fila por remito-producto pendiente con su cantidad
   pendiente y disponible (idempotente: la corrida del día reemplaza).
   La disponibilidad se evalúa siguiendo la cadena de abastecimiento de
   cada movimiento (_chain_available_qty), y las salidas más viejas que
   el corte de antigüedad configurado quedan fuera.
2. Retención: purga snapshots crudos más viejos que la retención
   configurada (por antigüedad; ya no depende de ningún consolidado).

mrp.planner.kpi.monthly queda como modelo LEGACY (sin escrituras ni lecturas):
sus filas del KPI 'dispatch_available' se borran en la migración 18.0.13.10.0.

Relacionado con:
- mrp.reschedule.config: dispatch_stock_log_enabled / dispatch_snapshot_hour /
  dispatch_log_retention_months / dispatch_available_denominator_method.
- mrp.planner.run.log: cada corrida del cron queda en el historial.
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

    # ── Cadena de entrega: tipos de operación y claves ────────────────────────

    @api.model
    def _dispatch_chain_types(self, company, warehouse_ids=None):
        """Tipos de operación de la cadena de entrega de cada depósito.

        El flujo lazy de Odoo 17+ crea cada paso al validar el anterior, así
        que la demanda pendiente vive repartida entre recolección, embalaje y
        salida según delivery_steps del depósito. Se identifican los eslabones
        por los tipos de operación de la ruta de entrega (pick/pack/out) para
        no confundir transferencias internas ajenas con demanda de clientes.

        :returns: (type_ids, info) — info = {type_id: (wh_id, wh_name, stage)}
                  con stage en ('pick', 'pack', 'ship').
        """
        dom = [('company_id', '=', company.id)]
        if warehouse_ids:
            dom.append(('id', 'in', warehouse_ids))
        info = {}
        for w in self.env['stock.warehouse'].sudo().search(dom).read(
                ['name', 'delivery_steps', 'pick_type_id', 'pack_type_id', 'out_type_id']):
            if w['out_type_id']:
                info[w['out_type_id'][0]] = (w['id'], w['name'], 'ship')
            if w['delivery_steps'] in ('pick_ship', 'pick_pack_ship') and w['pick_type_id']:
                info[w['pick_type_id'][0]] = (w['id'], w['name'], 'pick')
            if w['delivery_steps'] == 'pick_pack_ship' and w['pack_type_id']:
                info[w['pack_type_id'][0]] = (w['id'], w['name'], 'pack')
        return list(info), info

    # ── Cron ──────────────────────────────────────────────────────────────────

    @api.model
    def _cron_dispatch_snapshot(self):
        """Corrida diaria: snapshot + cierre mensual + retención, por empresa."""
        Config = self.env['mrp.reschedule.config'].sudo()
        for company in self.env['res.company'].sudo().search([]):
            cfg = Config.with_company(company).get_config()
            if not (cfg and cfg.dispatch_stock_log_enabled):
                continue
            started = fields.Datetime.now()
            try:
                count = self._dispatch_take_snapshot(company, cfg)
                purged = self._dispatch_apply_retention(company, cfg)
                duration = (fields.Datetime.now() - started).total_seconds()
                parts = [f'{count} líneas registradas']
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

        chain_type_ids, type_info = self._dispatch_chain_types(company)
        if not chain_type_ids:
            return 0
        # Corte de antigüedad por línea (fecha programada del movimiento)
        cutoff_dom = cfg._dispatch_pending_cutoff_domain('date')

        # ── Demanda pendiente en cualquier eslabón (recolección/embalaje/salida).
        # sudo(): mismo criterio que las demás lecturas de stock del planificador.
        moves = self.env['stock.move'].sudo().search([
            ('company_id', '=', company.id),
            ('picking_id.picking_type_id', 'in', chain_type_ids),
            ('picking_id.state', 'in', PENDING_PICKING_STATES),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ] + cutoff_dom)
        move_rows = moves.read(['picking_id', 'product_id', 'product_uom_qty']) if moves else []
        # Disponibilidad evaluada en el eslabón donde está parada la demanda
        chain_avail = self._chain_available_qty(moves) if moves else {}

        # Depósito por picking vía el mapa de tipos de la cadena
        all_pick_ids = {r['picking_id'][0] for r in move_rows if r['picking_id']}
        pick_type = {p['id']: p['picking_type_id'][0] if p['picking_type_id'] else False
                     for p in self.env['stock.picking'].sudo()
                                  .browse(list(all_pick_ids)).read(['picking_type_id'])}

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
            wh_info = type_info.get(pick_type.get(pick))
            vals_list.append({
                'snapshot_date': today,
                'company_id':    company.id,
                'warehouse_id':  wh_info[0] if wh_info else False,
                'picking_id':    pick,
                'product_id':    prod,
                'qty_pending':   round(pending, 2),
                # Topeada a la pendiente: el excedente disponible no suma
                'qty_reserved':  round(min(available, pending), 2),
            })
        if vals_list:
            self.sudo().create(vals_list)
        return len(vals_list)

    # ── Paso 2: retención ─────────────────────────────────────────────────────

    @api.model
    def _dispatch_apply_retention(self, company, cfg):
        """Purga snapshots más viejos que la retención, por antigüedad.

        La Tasa de entrega se calcula en vivo desde los snapshots (ya no hay
        consolidado mensual), así que la purga depende SOLO de la antigüedad:
        se borra todo lo anterior al primer día del mes N meses atrás.

        :returns: int — filas eliminadas.
        """
        months_keep = max(1, int(cfg.dispatch_log_retention_months or 12))
        tz = self._company_tz(company)
        today_local = datetime.now(pytz.utc).astimezone(tz).date()
        # Primer día del mes N meses atrás: todo lo anterior es purgable
        year = today_local.year + (today_local.month - 1 - months_keep) // 12
        month = (today_local.month - 1 - months_keep) % 12 + 1
        cutoff = today_local.replace(year=year, month=month, day=1)

        stale = self.sudo().search([
            ('company_id', '=', company.id),
            ('snapshot_date', '<', cutoff),
        ])
        purged = len(stale)
        stale.unlink()
        return purged


class MrpPlannerKpiMonthly(models.Model):
    # LEGACY: ya no se escribe ni se lee. Guardaba el consolidado mensual de la
    # vieja "Tasa de entrega s/ disponible"; la tasa nueva se calcula en vivo
    # desde los snapshots. Las filas se borran en la migración 18.0.13.10.0. El
    # modelo se conserva para no arrastrar una baja de modelo con sus ACLs.
    _name = 'mrp.planner.kpi.monthly'
    _description = 'KPIs mensuales consolidados del planificador (legacy)'
    _order = 'period desc, id'

    kpi = fields.Selection([
        ('dispatch_available', 'Tasa de entrega'),
    ], string='KPI', required=True, index=True)
    period = fields.Date(string='Mes', required=True, index=True,
                         help='Primer día del mes consolidado.')
    company_id = fields.Many2one('res.company', string='Empresa', required=True, index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Depósito',
                                   help='Vacío en la fila resumen global del mes.')
    product_id = fields.Many2one('product.product', string='Artículo', ondelete='cascade',
                                 help='Vacío en la fila resumen global del mes.')
    qty_num = fields.Float(string='Numerador', digits='Product Unit of Measure',
                           help='Legacy: numerador del consolidado viejo de la Tasa de entrega.')
    qty_den_extra = fields.Float(string='Denominador extra', digits='Product Unit of Measure',
                                 help='Legacy: denominador extra del consolidado viejo de la Tasa de entrega.')
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
