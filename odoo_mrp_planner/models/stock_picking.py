"""
Módulo: stock_picking.py
Modelo: extensión de stock.picking

Intercepta escrituras en transferencias para mantener el sistema de alertas
de reprogramación MRP actualizado cuando cambia el estado o la fecha de una recepción.

Responsabilidades:
- Detectar cancelaciones, confirmaciones y cambios de fecha en recepciones entrantes.
- Resolver alertas de tipo 'receipt_delayed' cuando la situación se normaliza.
- Marcar las órdenes de fabricación (MOs) que consumen los productos afectados
  como necesitadas de reprogramación (x_reschedule_needed).

Relacionado con:
- mrp.reschedule.alert: gestiona las alertas de retraso que este módulo resuelve.
- mrp.production: las órdenes de fabricación que se marcan para reprogramar.
"""

import logging
from datetime import datetime, timedelta

import pytz

from odoo import models, fields

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def write(self, vals):
        """
        Extiende write para disparar la lógica de alertas MRP en recepciones.

        Al persistir cambios en transferencias, evalúa tres condiciones sobre los
        registros de tipo 'incoming' (recepciones de proveedor):

        1. Cancelación (state → 'cancel'): resuelve alertas 'receipt_delayed' activas
           y marca las MOs dependientes para reprogramación, porque el material ya
           no llegará por esta vía.
        2. Confirmación/recepción (state → 'done'): resuelve alertas 'receipt_delayed'
           porque el material ya ingresó al almacén.
        3. Cambio de fecha programada: si la nueva fecha es posterior a la anterior,
           la recepción se atrasó y las MOs dependientes deben reevaluarse; si la
           nueva fecha es futura respecto al momento actual, la alerta previa se resuelve.

        Los errores por recepción se loguean como warning sin interrumpir el write,
        para no bloquear operaciones de almacén por fallos en la lógica de planificación.

        :param vals: dict con los valores a escribir en los registros.
        :returns: resultado de super().write(vals) (bool True en Odoo ORM).
        """
        track_cancel = vals.get('state') == 'cancel'
        track_done   = vals.get('state') == 'done'
        track_date   = 'scheduled_date' in vals

        if track_date:
            old_dates = {p.id: p.scheduled_date for p in self}

        result = super().write(vals)

        alert_env = self.env['mrp.reschedule.alert']
        now = fields.Datetime.now()
        incoming = self.filtered(lambda p: p.picking_type_code == 'incoming')

        if incoming:
            for picking in incoming:
                try:
                    if track_cancel or track_done:
                        alert_env._resolve_for(('receipt_delayed',), picking_id=picking.id)
                        if track_cancel:
                            self._flag_mos_for_picking(picking)
                    elif track_date:
                        if picking.scheduled_date and picking.scheduled_date > now:
                            alert_env._resolve_for(('receipt_delayed',), picking_id=picking.id)
                        old_dt = old_dates.get(picking.id)
                        if old_dt and picking.scheduled_date and picking.scheduled_date > old_dt:
                            self._flag_mos_for_picking(picking)
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al procesar recepción %s: %s', picking.name, e
                    )

        return result

    def _flag_mos_for_picking(self, picking):
        """Marca x_reschedule_needed en MOs que consumen los productos de esta recepción."""
        product_ids = picking.move_ids.mapped('product_id').ids
        if not product_ids:
            return
        # limit=50 dejaba OFs sin marcar; aumentado a 200 para reducir pérdidas
        mos = self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', 'in', product_ids),
        ], limit=200)
        if mos:
            mos.write({'x_reschedule_needed': True})

    # ══ Cantidades para las listas de los drills de los paneles ══════════════

    x_qty_pieces = fields.Float(
        string='Cantidad (Pz)', compute='_compute_x_qty_pieces',
        digits='Product Unit of Measure',
        help='Suma de las cantidades de las líneas del remito: demandadas si el '
             'remito está pendiente, hechas si ya está validado. Columna '
             'informativa de las listas que abren los paneles del planificador.')

    def _planner_qty_move_date_dom(self):
        """Rango de fechas opcional del contexto (planner_date_from/_to, días
        locales del usuario) sobre la fecha programada de cada línea
        (stock.move.date): las columnas de cantidad de las listas de drills
        respetan así el mismo corte por línea que los paneles."""
        ctx = self.env.context
        d_from, d_to = ctx.get('planner_date_from'), ctx.get('planner_date_to')
        if not d_from and not d_to:
            return []
        try:
            tz = pytz.timezone(ctx.get('tz') or self.env.user.tz or 'UTC')
        except Exception:
            tz = pytz.utc
        to_utc = lambda d: tz.localize(datetime.combine(d, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        dom = []
        if d_from:
            dom.append(('date', '>=', to_utc(fields.Date.from_string(d_from))))
        if d_to:
            dom.append(('date', '<',
                        to_utc(fields.Date.from_string(d_to) + timedelta(days=1))))
        return dom

    def _compute_x_qty_pieces(self):
        # Suma por remito en dos pasadas batch (una por criterio de estado)
        Move = self.env['stock.move'].sudo()
        pending = self.filtered(lambda p: p.state not in ('done', 'cancel'))
        done = self.filtered(lambda p: p.state == 'done')
        date_dom = self._planner_qty_move_date_dom()
        totals = {}
        if pending:
            for picking, qty in Move._read_group(
                    [('picking_id', 'in', pending.ids),
                     ('state', 'not in', ('draft', 'done', 'cancel'))] + date_dom,
                    ['picking_id'], ['product_uom_qty:sum']):
                totals[picking.id] = qty
        if done:
            for picking, qty in Move._read_group(
                    [('picking_id', 'in', done.ids), ('state', '=', 'done')],
                    ['picking_id'], ['quantity:sum']):
                totals[picking.id] = qty
        for pick in self:
            pick.x_qty_pieces = totals.get(pick.id, 0.0)

    x_qty_available_chain = fields.Float(
        string='Con stock (Pz)', compute='_compute_x_qty_chain',
        digits='Product Unit of Measure',
        help='De la demanda pendiente del remito, cantidad con stock reservado '
             'en el eslabón donde está parada (siguiendo la cadena de '
             'abastecimiento) — mismo cálculo que la columna "Con stock" del '
             'Panel de Inventario. Remitos validados: 100 %.')
    x_qty_blocked_chain = fields.Float(
        string='Sin stock (Pz)', compute='_compute_x_qty_chain',
        digits='Product Unit of Measure',
        help='Demanda pendiente sin stock reservado: Demanda − Con stock.')

    def _compute_x_qty_chain(self):
        # Mismo criterio que los KPIs del Panel de Inventario: disponibilidad
        # evaluada por línea en el eslabón donde está parada la demanda.
        Move = self.env['stock.move'].sudo()
        Log = self.env['mrp.dispatch.stock.log']
        pending = self.filtered(lambda p: p.state in ('confirmed', 'waiting', 'assigned'))
        done = self.filtered(lambda p: p.state == 'done')
        avail, demand = {}, {}
        if pending:
            moves = Move.search([
                ('picking_id', 'in', pending.ids),
                ('state', 'not in', ('draft', 'done', 'cancel')),
            ] + self._planner_qty_move_date_dom())
            chain_avail = Log._chain_available_qty(moves)
            for r in moves.read(['picking_id', 'product_uom_qty']):
                pick = r['picking_id'][0] if r['picking_id'] else False
                if not pick:
                    continue
                q = r['product_uom_qty'] or 0.0
                demand[pick] = demand.get(pick, 0.0) + q
                avail[pick] = avail.get(pick, 0.0) + min(chain_avail.get(r['id'], 0.0), q)
        if done:
            for picking, qty in Move._read_group(
                    [('picking_id', 'in', done.ids), ('state', '=', 'done')],
                    ['picking_id'], ['quantity:sum']):
                demand[picking.id] = qty
                avail[picking.id] = qty
        for pick in self:
            a = avail.get(pick.id, 0.0)
            pick.x_qty_available_chain = a
            pick.x_qty_blocked_chain = max(0.0, demand.get(pick.id, 0.0) - a)
