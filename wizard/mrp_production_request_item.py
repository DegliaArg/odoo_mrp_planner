"""
Módulo: mrp_production_request_item.py
Modelo: mrp.production.request.item

Representa una línea individual dentro de una solicitud de programación MRP.

Responsabilidades:
- Almacenar el producto, cantidad y fecha de entrega deseada por el planificador.
- Calcular la viabilidad de cumplir la fecha, comparando el mínimo alcanzable contra el deadline.
- Advertir al usuario si el producto seleccionado carece de Lista de Materiales (LdM).
- Vincular la línea con la Orden de Fabricación (OF) generada y registrar su avance.

Relacionado con:
- mrp.production.request: cabecera de la solicitud que agrupa estas líneas (Many2one).
- mrp.production: OF vinculada tras ejecutar la planificación (Many2one).
- mrp.bom: se consulta para verificar que el producto tiene una LdM de fabricación activa.
"""
from odoo import models, fields, api, _


class MrpProductionRequestItem(models.Model):
    """Una fila de entrada: qué fabricar, cuánto y para cuándo."""
    _name = 'mrp.production.request.item'
    _description = 'Artículo de solicitud de programación'
    _order = 'sequence, id'
    _rec_name = 'name'

    request_id  = fields.Many2one('mrp.production.request', required=True, ondelete='cascade',
                                  help='Solicitud de programación a la que pertenece esta línea.')
    sequence    = fields.Integer(default=10,
                                 help='Orden de visualización dentro de la solicitud. Valores menores aparecen primero.')
    name        = fields.Char(compute='_compute_name', store=True,
                              help='Nombre de la línea, calculado automáticamente desde el nombre del producto.')
    product_id  = fields.Many2one('product.product', string='Producto', required=True,
                                  domain=[('type', 'in', ['consu', 'product'])],
                                  help='Producto a fabricar. Solo se admiten productos almacenables o consumibles.')
    product_qty = fields.Float(string='Cantidad', default=1.0, required=True,
                               help='Cantidad a producir en la unidad de medida del producto.')
    date_deadline = fields.Datetime(string='Fecha de entrega deseada', required=True,
                                    help='Fecha límite solicitada por el planificador. Se compara con el mínimo alcanzable para calcular la viabilidad.')

    earliest_end    = fields.Datetime(string='Mínimo alcanzable', readonly=True,
                                      help='Fecha mínima posible calculada por el sistema.')
    projected_start = fields.Datetime(string='Inicio planificado', readonly=True,
                                      help='Fecha de inicio de producción calculada por el planificador.')
    projected_end   = fields.Datetime(string='Fin planificado',
                                      help='Fecha de fin de producción. Podés adelantarla al mínimo posible con el botón Adelantar.')
    feasible        = fields.Boolean(compute='_compute_feasible', store=False,
                                     help='True si el mínimo alcanzable es anterior o igual a la fecha de entrega deseada.')
    feasibility_msg = fields.Char(compute='_compute_feasible', store=False, string='Info',
                                  help='Mensaje descriptivo del margen disponible o del atraso estimado.')
    bom_warning     = fields.Char(compute='_compute_bom_warning', store=False,
                                  help='Aviso visible en la línea cuando el producto no tiene Lista de Materiales activa.')

    @api.depends('product_id')
    def _compute_bom_warning(self):
        """
        Calcula [bom_warning] para cada registro.

        Fórmula: busca una LdM de fabricación directa (excluye phantom y subcontratación)
        válida para la empresa activa o global. Si no existe, muestra 'Sin LdM'.
        Depende de: product_id.
        """
        for item in self:
            if not item.product_id:
                item.bom_warning = ''
                continue
            bom = self.env['mrp.bom'].search([
                ('type', 'not in', ['phantom', 'subcontract']),
                ('company_id', 'in', [False, self.env.company.id]),
                '|',
                ('product_id', '=', item.product_id.id),
                '&', ('product_id', '=', False),
                ('product_tmpl_id', '=', item.product_id.product_tmpl_id.id),
            ], limit=1)
            item.bom_warning = '' if bom else _('Sin LdM')

    @api.onchange('product_id')
    def _onchange_product_id_bom(self):
        """Advierte en tiempo real si el producto seleccionado no tiene LdM de fabricación."""
        if not self.product_id:
            return
        bom = self.env['mrp.bom'].search([
            ('type', 'not in', ['phantom', 'subcontract']),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', self.product_id.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
        ], limit=1)
        if not bom:
            return {'warning': {
                'title': _('Sin Lista de Materiales'),
                'message': _(
                    'El producto "%s" no tiene una LdM de fabricación. '
                    'No se podrá calcular el plan.'
                ) % self.product_id.display_name,
            }}

    production_id = fields.Many2one(
        'mrp.production', string='OF madre', readonly=True, copy=False, index=True,
        ondelete='set null',
        help='Orden de Fabricación generada a partir de esta línea. Se asigna al ejecutar el plan.',
    )
    mo_state    = fields.Selection(related='production_id.state', string='Estado OF',
                                   help='Estado actual de la OF vinculada (borrador, confirmada, en progreso, terminada).')
    qty_produced = fields.Float(compute='_compute_tracking', string='Producido', store=False,
                                help='Cantidad ya producida: para OF terminadas usa los movimientos reales; para las demás, la cantidad en producción.')
    qty_delta    = fields.Float(compute='_compute_tracking', string='Δ Cant.', store=False,
                                help='Diferencia entre cantidad producida y cantidad solicitada. Negativo indica producción incompleta.')

    @api.depends('production_id', 'production_id.state', 'production_id.qty_producing',
                 'production_id.move_finished_ids.state')
    def _compute_tracking(self):
        """
        Calcula [qty_produced] y [qty_delta] para cada registro.

        Fórmula: cuando la OF está en estado 'done', suma las cantidades de los movimientos
        de producto terminado completados (move_finished_ids). Si no hay movimientos o
        falla el acceso, usa product_qty como fallback. Para otros estados usa qty_producing.
        qty_delta = qty_produced - product_qty.
        Depende de: production_id, production_id.state, production_id.qty_producing,
                    production_id.move_finished_ids.state.
        """
        for item in self:
            mo = item.production_id
            if not mo:
                item.qty_produced = 0.0
                item.qty_delta    = 0.0
                continue
            if mo.state == 'done':
                try:
                    done = mo.move_finished_ids.filtered(
                        lambda m: m.state == 'done' and m.product_id == mo.product_id
                    )
                    qty = sum(
                        # 'quantity' existe en Odoo 17+; 'quantity_done' en versiones anteriores
                        getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                        for m in done
                    ) if done else mo.product_qty
                except Exception:
                    qty = mo.product_qty
                item.qty_produced = qty
            else:
                item.qty_produced = mo.qty_producing or 0.0
            item.qty_delta = item.qty_produced - item.product_qty

    @api.depends('product_id')
    def _compute_name(self):
        """
        Calcula [name] para cada registro.

        Fórmula: nombre de presentación del producto (display_name). Si no hay producto,
        devuelve '—' para evitar valores vacíos en listas y breadcrumbs.
        Depende de: product_id.
        """
        for item in self:
            item.name = item.product_id.display_name or '—'

    @api.depends('earliest_end', 'date_deadline')
    def _compute_feasible(self):
        """
        Calcula [feasible] y [feasibility_msg] para cada registro.

        Fórmula: compara earliest_end con date_deadline.
        - Si earliest_end <= date_deadline: feasible=True, el mensaje indica el margen
          disponible expresado en días y horas.
        - Si earliest_end > date_deadline: feasible=False, el mensaje indica el atraso
          estimado expresado en días y horas.
        - Si alguno de los dos campos es nulo: feasible=False y mensaje '—'.
        Depende de: earliest_end, date_deadline.
        """
        for item in self:
            if not item.earliest_end or not item.date_deadline:
                item.feasible = False
                item.feasibility_msg = '—'
                continue
            if item.earliest_end <= item.date_deadline:
                secs = (item.date_deadline - item.earliest_end).total_seconds()
                d, h = int(secs // 86400), int((secs % 86400) // 3600)  # 86400 = segundos en un día
                item.feasible = True
                delta = f'{d}d {h}h' if d else f'{h}h'
                item.feasibility_msg = _(
                    'Puede adelantarse %s (mínimo: %s)'
                ) % (delta, item.earliest_end.strftime('%d/%m %H:%M'))
            else:
                secs = (item.earliest_end - item.date_deadline).total_seconds()
                d, h = int(secs // 86400), int((secs % 86400) // 3600)  # 86400 = segundos en un día
                item.feasible = False
                delta = f'{d}d {h}h' if d else f'{h}h'
                item.feasibility_msg = _('Atraso estimado: %s') % delta

    def action_adelantar(self):
        """
        Adelanta la fecha de fin planificada al mínimo alcanzable calculado por el sistema.

        Sobreescribe projected_end con earliest_end, permitiendo al planificador
        aceptar la fecha más optimista sin ingresar el valor manualmente.
        No hace nada si earliest_end está vacío.

        :returns: None
        """
        self.ensure_one()
        if self.earliest_end:
            self.projected_end = self.earliest_end
