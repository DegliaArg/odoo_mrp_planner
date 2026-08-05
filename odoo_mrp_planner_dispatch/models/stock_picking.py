"""
Módulo: stock_picking.py (odoo_mrp_planner_dispatch)
Modelo: extensión de stock.picking

Agrega a las órdenes de entrega (salidas) el circuito de despacho:
estado Sin despachar / Despachado, botón de despacho con doble control
(remito validado + grupo de seguridad, verificado también en servidor),
reversa para administradores y auditoría de fecha/usuario/chatter.

Relacionado con:
- mrp.reschedule.config: enable_dispatch_validation activa la función por
  empresa (agregado por este módulo).
- res.groups (group_dispatch_validation): habilita el botón de despacho.
"""
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_dispatch_state = fields.Selection([
        ('to_dispatch', 'Sin despachar'),
        ('dispatched',  'Despachado'),
    ], string='Despacho', copy=False, index=True,
       help='Circuito de despacho de las salidas: el remito nace "Sin despachar" y '
            'pasa a "Despachado" cuando un usuario del grupo Inventario: validación '
            'de despacho lo confirma (solo posible con el remito ya validado). '
            'Las operaciones que no son salidas, o cuyo tipo quedó fuera de los '
            '"Tipos de operación con despacho" de Ajustes, no llevan este estado.')
    x_dispatch_date = fields.Datetime(
        string='Despachado el', readonly=True, copy=False,
        help='Fecha y hora en que se marcó el despacho.')
    x_dispatch_user_id = fields.Many2one(
        'res.users', string='Despachado por', readonly=True, copy=False,
        help='Usuario que confirmó el despacho.')
    x_dispatch_enabled = fields.Boolean(
        compute='_compute_x_dispatch_enabled',
        help='Indicador calculado: True si la función de despacho está habilitada '
             'en los Ajustes del planificador de la empresa del remito y la operación '
             'es una salida. Controla la visibilidad del estado y los botones.')
    x_qty_pieces = fields.Float(
        string='Cantidad (Pz)', compute='_compute_x_qty_pieces',
        digits='Product Unit of Measure',
        help='Suma de las cantidades de las líneas del remito: demandadas si el '
             'remito está pendiente, hechas si ya está validado. Columna '
             'informativa de las listas que abren los paneles del planificador.')

    def _compute_x_qty_pieces(self):
        # Suma por remito en dos pasadas batch (una por criterio de estado)
        Move = self.env['stock.move'].sudo()
        pending = self.filtered(lambda p: p.state not in ('done', 'cancel'))
        done = self.filtered(lambda p: p.state == 'done')
        totals = {}
        if pending:
            for picking, qty in Move._read_group(
                    [('picking_id', 'in', pending.ids),
                     ('state', 'not in', ('draft', 'done', 'cancel'))],
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
            ])
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

    def _dispatch_type_cache(self):
        """Cache por empresa para decidir si un remito entra al circuito:
        {company_id: (función activa, set de tipos con despacho)}. Un set
        vacío significa lista sin configurar = todas las salidas."""
        Config = self.env['mrp.reschedule.config'].sudo()
        cache = {}

        def lookup(pick):
            cid = pick.company_id.id
            if cid not in cache:
                cfg = Config.with_company(pick.company_id).get_config() if cid else False
                cache[cid] = (bool(cfg and cfg.enable_dispatch_validation),
                              set(cfg.dispatch_picking_type_ids.ids) if cfg else set())
            return cache[cid]

        def allowed(pick):
            type_ids = lookup(pick)[1]
            return (pick.picking_type_code == 'outgoing'
                    and (not type_ids or pick.picking_type_id.id in type_ids))

        return lookup, allowed

    @api.depends('company_id', 'picking_type_code', 'picking_type_id')
    def _compute_x_dispatch_enabled(self):
        # sudo() en la cache: la config del planificador puede no ser accesible
        # para usuarios de depósito.
        lookup, allowed = self._dispatch_type_cache()
        for pick in self:
            pick.x_dispatch_enabled = lookup(pick)[0] and allowed(pick)

    @api.model_create_multi
    def create(self, vals_list):
        """Las salidas de los tipos con despacho nacen "Sin despachar" (aunque
        la función esté apagada: el estado queda oculto y disponible si se
        activa después). Los tipos excluidos en Ajustes no entran al circuito."""
        pickings = super().create(vals_list)
        _lookup, allowed = self._dispatch_type_cache()
        outgoing = pickings.filtered(
            lambda p: not p.x_dispatch_state and allowed(p))
        if outgoing:
            # sudo(): el estado es técnico; el creador del remito puede no tener
            # permisos de escritura ampliados según sus reglas.
            outgoing.sudo().write({'x_dispatch_state': 'to_dispatch'})
        return pickings

    # ── Guards ───────────────────────────────────────────────────────────────

    def _dispatch_check_rights(self):
        """El botón oculto no es seguridad: verifica grupo y función activa en servidor.

        :raises AccessError: si el usuario no pertenece al grupo de despacho.
        :raises UserError: si la función está desactivada para alguna empresa.
        """
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner_dispatch.group_dispatch_validation')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system')):
            raise AccessError(_('Solo los usuarios del grupo "Inventario: validación '
                                'de despacho" pueden despachar entregas.'))
        Config = self.env['mrp.reschedule.config'].sudo()
        for company in self.mapped('company_id'):
            cfg = Config.with_company(company).get_config()
            if not (cfg and cfg.enable_dispatch_validation):
                raise UserError(_('La validación de despacho está desactivada para %s. '
                                  'Activala en Ajustes del planificador → Producción.',
                                  company.display_name))

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_mark_dispatched(self):
        """Marca como despachadas las salidas seleccionadas.

        Funciona desde el botón del formulario y desde la acción masiva de la
        lista. Exige que TODOS los remitos a despachar estén validados (done):
        si alguno no lo está, se rechaza la operación completa para que el
        error no pase inadvertido en un despacho en lote.
        """
        self._dispatch_check_rights()
        _lookup, allowed = self._dispatch_type_cache()
        todo = self.filtered(
            lambda p: allowed(p) and p.x_dispatch_state != 'dispatched')
        if not todo:
            raise UserError(_('Nada para despachar: las salidas seleccionadas ya están despachadas.'))
        not_done = todo.filtered(lambda p: p.state != 'done')
        if not_done:
            raise UserError(_('No se puede despachar una entrega sin validar: %s',
                              ', '.join(not_done.mapped('name'))))
        now = fields.Datetime.now()
        todo.write({
            'x_dispatch_state':   'dispatched',
            'x_dispatch_date':    now,
            'x_dispatch_user_id': self.env.user.id,
        })
        for pick in todo:
            pick.message_post(body=_('Entrega despachada por %s.', self.env.user.display_name))
        return True

    def action_reset_dispatch(self):
        """Reversa a "Sin despachar" — solo administradores (queda en el chatter)."""
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner.group_admin') or u.has_group('base.group_system')):
            raise AccessError(_('Solo los administradores del planificador pueden '
                                'revertir un despacho.'))
        todo = self.filtered(lambda p: p.x_dispatch_state == 'dispatched')
        todo.write({
            'x_dispatch_state':   'to_dispatch',
            'x_dispatch_date':    False,
            'x_dispatch_user_id': False,
        })
        for pick in todo:
            pick.message_post(body=_('Despacho revertido a "Sin despachar" por %s.',
                                     self.env.user.display_name))
        return True
