"""
Módulo: mrp_reschedule_plan_line.py
Modelo: mrp.reschedule.plan.line

Línea de plan de reprogramación en cascada. Representa una MO o PO
incluida en el plan, con sus fechas actuales y propuestas.
"""

from odoo import models, fields, api, _

from .mrp_reschedule_cascade_mixin import _get_old_code, MRP_STATES, PO_STATES
from .mrp_schedule_mixin import INDENT_MAP


class MrpReschedulePlanLine(models.Model):
    _name = 'mrp.reschedule.plan.line'
    _description = 'Línea de plan de reprogramación en cascada'
    _order = 'reschedule_sequence, id'
    _rec_name = 'record_label'

    plan_id  = fields.Many2one('mrp.reschedule.plan', required=True, ondelete='cascade',
                               string='Plan', help='Plan de reprogramación al que pertenece esta línea.')
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10,
                              help='Orden interno de creación usado como fallback de visualización.')
    reschedule_sequence = fields.Integer(
        string='Orden',
        default=0,
        help='Secuencia editable por el usuario para ordenar manualmente las MOs '
             'antes de calcular con la estrategia "manual".',
    )

    apply             = fields.Boolean(
        string='Aplicar', default=True,
        help='Si está activo, esta línea se incluirá al ejecutar "Aplicar plan". '
             'Las líneas de MOs anchor y POs en estado cerrado se marcan en False por defecto.',
    )
    is_anchor         = fields.Boolean(
        string='Fijo', default=False,
        help='Las líneas fijas no se desplazan: conservan sus fechas actuales (o usan '
             'inicio forzado). Las MOs en estado progress/done/to_close se fijan automáticamente.',
    )
    forced_start_date = fields.Datetime(
        string='Inicio forzado',
        help='Si está definido en una línea fija, el algoritmo programa '
             'esta OF a partir de esta fecha (respetando el calendario del WC) '
             'en lugar de usar su fecha actual.',
    )
    color     = fields.Integer(
        compute='_compute_color', store=True,
        help='Color Kanban: rojo=OC confirmada, naranja=hija ajustada, gris=anchor, '
             'verde=compra, azul=fabricación.',
    )

    record_type  = fields.Selection(
        [('mrp', 'Fabricación'), ('purchase', 'Compra')], string='Tipo', required=True,
        help='Indica si la línea representa una orden de fabricación o una orden de compra.',
    )
    level        = fields.Integer(
        default=0,
        help='Profundidad en el árbol de cascada. 0=raíz, 1=hija directa, 2=nieta, etc. '
             'Usado para indentar la referencia en la vista árbol.',
    )
    parent_label = fields.Char(
        string='Generado por',
        help='Nombre de la MO padre que originó esta línea (para trazabilidad en la vista).',
    )

    production_id = fields.Many2one('mrp.production', string='Orden de fabricación',
                                    help='MO asociada a esta línea (solo para record_type="mrp").')
    purchase_id   = fields.Many2one('purchase.order',  string='Orden de compra',
                                    help='PO asociada a esta línea (solo para record_type="purchase").')

    duration_hours = fields.Float(
        string='Duración (hs)', digits=(10, 2),
        help='Duración estimada del bloque de producción en horas. '
             'Editable para ajustar el largo del bloque antes de recalcular.',
    )
    warning_type = fields.Selection(
        [('confirmed_po', 'OC confirmada'), ('child_adjusted', 'Hija ajustada')],
        string='Tipo advertencia', default=False,
        help='confirmed_po: la PO ya está confirmada y requiere gestión con el proveedor. '
             'child_adjusted: la MO hija fue ajustada al primer turno disponible.',
    )
    warning_message = fields.Char(
        string='Advertencia',
        help='Descripción detallada del tipo de advertencia para mostrar en la vista.',
    )

    # Campos de display almacenados para que el Gantt los lea sin recomputar
    record_label      = fields.Char(string='Referencia',           compute='_compute_display', store=True)
    description_label = fields.Char(string='Producto / Proveedor', compute='_compute_display', store=True)
    workcenter_label  = fields.Char(string='Centros de trabajo',   compute='_compute_display', store=True)
    product_qty_display = fields.Char(string='Cantidad',           compute='_compute_display', store=True)
    type_label        = fields.Char(string='Tipo',                 compute='_compute_display', store=True)
    state_display     = fields.Char(string='Estado',               compute='_compute_state_display', store=False)
    date_delta_display = fields.Char(string='Δ Tiempo',            compute='_compute_delta_display_line', store=False)

    current_date_start  = fields.Datetime(string='Inicio actual')
    current_date_finish = fields.Datetime(string='Fin actual')
    new_date_start      = fields.Datetime(string='Nuevo inicio')
    new_date_finish     = fields.Datetime(string='Nuevo fin')

    @api.depends('warning_type', 'is_anchor', 'record_type')
    def _compute_color(self):
        """
        Calcula color para cada línea.

        Fórmula: jerarquía de prioridad — advertencia OC confirmada (1=rojo) >
        hija ajustada (3=naranja) > anchor (0=gris) > compra (10=verde) > MO (4=azul).
        Depende de: warning_type, is_anchor, record_type.
        """
        for line in self:
            if line.warning_type == 'confirmed_po':
                line.color = 1   # rojo
            elif line.warning_type == 'child_adjusted':
                line.color = 3   # naranja
            elif line.is_anchor:
                line.color = 0   # gris
            elif line.record_type == 'purchase':
                line.color = 10  # verde
            else:
                line.color = 4   # azul

    @api.depends('level', 'record_type', 'production_id', 'purchase_id',
                 'production_id.workorder_ids.workcenter_id',
                 'production_id.product_qty', 'production_id.product_uom_id')
    def _compute_display(self):
        """
        Calcula los campos de etiqueta para mostrar en vistas árbol y Gantt.

        Fórmula: construye record_label con indentación según level (usando INDENT_MAP),
        prefijando el código viejo del producto si existe. Compone description_label,
        workcenter_label (secuencia de WCs con ' › '), product_qty_display y type_label.
        Depende de: level, record_type, production_id, purchase_id y sus subfields.
        """
        for line in self:
            prefix = INDENT_MAP.get(line.level, ' ' * 9 + '└─ ')
            if line.record_type == 'mrp' and line.production_id:
                mo = line.production_id
                code = _get_old_code(mo)
                base_label = f'[{code}] {mo.name}' if code else mo.name
                line.record_label        = f'{prefix}{base_label}'
                line.description_label   = mo.product_id.display_name if mo.product_id else ''
                wcs = mo.workorder_ids.mapped('workcenter_id')
                line.workcenter_label    = ' › '.join(wcs.mapped('name')) if wcs else ''
                qty = mo.product_qty
                uom = mo.product_uom_id.name if mo.product_uom_id else ''
                line.product_qty_display = f'{qty:g} {uom}'.strip() if qty else ''
                line.type_label          = 'OF' if line.level == 0 else 'OF hija'
            elif line.record_type == 'purchase' and line.purchase_id:
                po = line.purchase_id
                line.record_label        = f'{prefix}{po.name}'
                line.description_label   = po.partner_id.display_name if po.partner_id else ''
                line.workcenter_label    = ''
                line.product_qty_display = ''
                line.type_label          = 'OC'
            else:
                line.record_label        = f'{prefix}—'
                line.description_label   = ''
                line.workcenter_label    = ''
                line.product_qty_display = ''
                line.type_label          = ''

    @api.depends('record_type', 'production_id.state', 'purchase_id.state')
    def _compute_state_display(self):
        """
        Calcula state_display para cada línea.

        Fórmula: traduce el estado técnico de la MO o PO usando MRP_STATES / PO_STATES.
        No se almacena (store=False) ya que cambia con frecuencia en producción.
        Depende de: record_type, production_id.state, purchase_id.state.
        """
        for line in self:
            if line.record_type == 'mrp' and line.production_id:
                line.state_display = MRP_STATES.get(line.production_id.state, line.production_id.state)
            elif line.record_type == 'purchase' and line.purchase_id:
                line.state_display = PO_STATES.get(line.purchase_id.state, line.purchase_id.state)
            else:
                line.state_display = ''

    @api.depends('current_date_finish', 'new_date_finish')
    def _compute_delta_display_line(self):
        """
        Calcula date_delta_display para cada línea.

        Fórmula: diferencia entre new_date_finish y current_date_finish expresada
        como ±Xd Yh. Muestra '—' si alguna fecha es nula y 'sin cambio' si la
        diferencia es menor a 60 segundos.
        Depende de: current_date_finish, new_date_finish.
        """
        for line in self:
            cur = line.current_date_finish
            new = line.new_date_finish
            if not cur or not new:
                line.date_delta_display = '—'
                continue
            secs = (new - cur).total_seconds()
            if abs(secs) < 60:
                line.date_delta_display = 'sin cambio'
                continue
            sign = '+' if secs >= 0 else '-'
            h = abs(secs) / 3600.0
            d = int(h // 24)
            h_rem = int(h % 24)
            if d and h_rem:
                line.date_delta_display = f'{sign}{d}d {h_rem}h'
            elif d:
                line.date_delta_display = f'{sign}{d}d'
            else:
                line.date_delta_display = f'{sign}{h_rem}h'
