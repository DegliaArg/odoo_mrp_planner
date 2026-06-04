import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Prefijos unicode para indentar visualmente en la lista
INDENT_MAP = {
    0: '',
    1: '└─ ',
    2: '   └─ ',
    3: '      └─ ',
}

MRP_STATES = {
    'draft': 'Borrador',
    'confirmed': 'Confirmado',
    'progress': 'En proceso',
    'to_close': 'Por cerrar',
    'done': 'Hecho',
    'cancel': 'Cancelado',
}

PO_STATES = {
    'draft': 'Presupuesto',
    'sent': 'Enviado',
    'to approve': 'Por aprobar',
    'purchase': 'OC confirmada',
    'done': 'Bloqueado',
    'cancel': 'Cancelado',
}


class MrpRescheduleWizard(models.TransientModel):
    _name = 'mrp.reschedule.wizard'
    _description = 'Reprogramación en cascada de órdenes de fabricación'

    # ------------------------------------------------------------------
    # Campos principales
    # ------------------------------------------------------------------

    production_id = fields.Many2one(
        'mrp.production',
        string='Orden pivot',
        required=True,
        help='Orden de fabricación cuya fecha real de fin define el desplazamiento.',
    )
    new_finish_date = fields.Datetime(
        string='Nueva fecha de finalización',
        required=True,
        default=fields.Datetime.now,
        help=(
            'Fecha real (o estimada) de finalización de la orden pivot. '
            'El delta entre esta fecha y la fecha planificada original se '
            'aplica a todas las órdenes subsecuentes.'
        ),
    )
    delta_display = fields.Char(
        string='Desplazamiento calculado',
        compute='_compute_delta_display',
        help='Diferencia entre la nueva fecha de fin y la fecha planificada original.',
    )
    has_lines = fields.Boolean(compute='_compute_has_lines')
    line_ids = fields.One2many(
        'mrp.reschedule.wizard.line',
        'wizard_id',
        string='Cambios propuestos',
    )

    # ------------------------------------------------------------------
    # Campos calculados
    # ------------------------------------------------------------------

    @api.depends('line_ids')
    def _compute_has_lines(self):
        for rec in self:
            rec.has_lines = bool(rec.line_ids)

    @api.depends('new_finish_date', 'production_id', 'production_id.date_finished')
    def _compute_delta_display(self):
        for rec in self:
            planned = rec.production_id.date_finished if rec.production_id else False
            if planned and rec.new_finish_date:
                delta = rec.new_finish_date - planned
                total_secs = delta.total_seconds()
                sign = '+' if total_secs >= 0 else '-'
                hours_abs = abs(total_secs) / 3600
                days = int(hours_abs // 24)
                hours = int(hours_abs % 24)
                rec.delta_display = (
                    f'{sign}{days}d {hours}h' if days else f'{sign}{hours}h'
                )
            elif not planned:
                rec.delta_display = _('Sin fecha planificada en la orden pivot')
            else:
                rec.delta_display = '—'

    # ------------------------------------------------------------------
    # Onchanges
    # ------------------------------------------------------------------

    @api.onchange('production_id')
    def _onchange_production_id(self):
        """Auto-completa new_finish_date desde las WOs terminadas de la orden pivot."""
        if not self.production_id:
            return
        done_wos = self.production_id.workorder_ids.filtered(
            lambda w: w.state == 'done' and w.date_finished
        )
        finish_dates = [w.date_finished for w in done_wos]
        if finish_dates:
            self.new_finish_date = max(finish_dates)
        elif self.production_id.date_finished:
            self.new_finish_date = self.production_id.date_finished
        # Si ninguna fecha disponible, conservar el valor actual

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _get_delta(self):
        """Retorna el timedelta entre new_finish_date y la date_finished planificada."""
        self.ensure_one()
        planned = self.production_id.date_finished
        if not planned or not self.new_finish_date:
            return timedelta(0)
        return self.new_finish_date - planned

    def _get_subsequent_mos(self):
        """
        Retorna MOs no terminadas/canceladas que:
        - Comparten al menos un centro de trabajo con la orden pivot.
        - Tienen date_start >= date_start de la pivot (ordenadas cronológicamente).
        - No son la pivot misma.
        """
        pivot = self.production_id

        # Necesitamos date_start en la pivot para filtrar
        if not pivot.date_start:
            return self.env['mrp.production']

        wc_ids = pivot.workorder_ids.mapped('workcenter_id').ids
        if not wc_ids:
            return self.env['mrp.production']

        return self.env['mrp.production'].search([
            ('id', '!=', pivot.id),
            ('state', 'not in', ['done', 'cancel']),
            ('date_start', '!=', False),
            ('date_start', '>=', pivot.date_start),
            ('workorder_ids.workcenter_id', 'in', wc_ids),
        ], order='date_start, id')

    def _get_pos_for_mo(self, mo):
        """
        Retorna las órdenes de compra abiertas vinculadas a una MO:
          1. PO de subcontratación (purchase_order_id directo).
          2. PO vía purchase_line_id (otro vínculo directo).
          3. POs de componentes cuyo campo origin contiene el nombre de la MO.
        """
        pos = self.env['purchase.order']

        # 1. Vínculo directo de subcontratación
        if mo.purchase_order_id and mo.purchase_order_id.state not in ('done', 'cancel'):
            pos |= mo.purchase_order_id

        # 2. Vínculo vía línea de OC
        if mo.purchase_line_id and mo.purchase_line_id.order_id:
            po_via_line = mo.purchase_line_id.order_id
            if po_via_line.state not in ('done', 'cancel'):
                pos |= po_via_line

        # 3. POs de componentes auto-generadas (campo origin en la OC)
        if mo.name:
            origin_pos = self.env['purchase.order'].search([
                ('origin', 'ilike', mo.name),
                ('state', 'not in', ('done', 'cancel')),
            ])
            pos |= origin_pos

        return pos

    def _get_child_mos(self, mo):
        """Retorna MOs hijas cuyo campo origin apunta a la MO dada."""
        return self.env['mrp.production'].search([
            ('origin', '=', mo.name),
            ('state', 'not in', ['done', 'cancel']),
        ])

    # ------------------------------------------------------------------
    # Construcción de líneas
    # ------------------------------------------------------------------

    def _build_lines(self):
        """
        Calcula la cascada completa y escribe las líneas en line_ids.

        Recorrido (BFS / recursivo):
          1. MOs subsecuentes en los mismos WC (nivel 0).
          2. Para cada MO: OCs vinculadas (nivel +1) y MOs hijas (nivel +1, recursivo).

        Usa sets de IDs visitados para evitar ciclos y duplicados.
        """
        self.ensure_one()
        delta = self._get_delta()
        pivot = self.production_id

        lines_vals = []
        seq = 10
        visited_mo_ids = {pivot.id}
        visited_po_ids = set()

        def shift(dt):
            """Desplaza un datetime por delta; retorna False si dt es False."""
            return dt + delta if dt else False

        def add_mo(mo, level, parent_label):
            nonlocal seq
            if mo.id in visited_mo_ids:
                return
            visited_mo_ids.add(mo.id)

            # — Línea de la MO —
            lines_vals.append({
                'wizard_id': self.id,
                'sequence': seq,
                'record_type': 'mrp',
                'production_id': mo.id,
                'level': level,
                'parent_label': parent_label,
                'current_date_start': mo.date_start,
                'current_date_finish': mo.date_finished,
                'new_date_start': shift(mo.date_start),
                'new_date_finish': shift(mo.date_finished),
                'apply': True,
            })
            seq += 10

            # — Líneas de OCs vinculadas a esta MO —
            for po in self._get_pos_for_mo(mo):
                if po.id in visited_po_ids:
                    continue
                visited_po_ids.add(po.id)
                lines_vals.append({
                    'wizard_id': self.id,
                    'sequence': seq,
                    'record_type': 'purchase',
                    'purchase_id': po.id,
                    'level': level + 1,
                    'parent_label': mo.name,
                    'current_date_start': po.date_order,
                    'current_date_finish': po.date_planned,
                    'new_date_start': False,
                    'new_date_finish': shift(po.date_planned),
                    'apply': True,
                })
                seq += 10

            # — MOs hijas (recursivo) —
            for child in self._get_child_mos(mo):
                add_mo(child, level + 1, mo.name)

        # Semilla: MOs subsecuentes en los mismos centros de trabajo
        for mo in self._get_subsequent_mos():
            add_mo(mo, 0, pivot.name)

        # Reemplazar líneas existentes
        self.line_ids.unlink()
        if lines_vals:
            self.env['mrp.reschedule.wizard.line'].create(lines_vals)

    # ------------------------------------------------------------------
    # Acciones de botones
    # ------------------------------------------------------------------

    def action_recalculate(self):
        """Recalcula todas las líneas desde cero usando new_finish_date actual."""
        self.ensure_one()
        if not self.production_id:
            raise UserError(_('Seleccione una orden de fabricación primero.'))
        if not self.production_id.date_finished:
            raise UserError(_(
                'La orden "%s" no tiene fecha de finalización planificada. '
                'No es posible calcular el desplazamiento.'
            ) % self.production_id.name)
        self._build_lines()
        # Reabrir el mismo wizard para refrescar la vista
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reprogramar en cascada'),
            'res_model': 'mrp.reschedule.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        """Aplica los cambios marcados: actualiza fechas en MOs y OCs, luego replanifica."""
        self.ensure_one()

        active_lines = self.line_ids.filtered('apply')
        if not active_lines:
            raise UserError(_('No hay líneas marcadas para aplicar.'))

        mos_to_replan = self.env['mrp.production']

        for line in active_lines:

            # — Actualizar orden de fabricación —
            if line.record_type == 'mrp' and line.production_id:
                vals = {}
                if line.new_date_start:
                    vals['date_start'] = line.new_date_start
                if line.new_date_finish:
                    vals['date_finished'] = line.new_date_finish
                if vals:
                    line.production_id.write(vals)
                    # Marcar para replanificar si tiene órdenes de trabajo
                    if line.production_id.workorder_ids:
                        mos_to_replan |= line.production_id

            # — Actualizar orden de compra —
            elif line.record_type == 'purchase' and line.purchase_id:
                if line.new_date_finish:
                    # Actualizar líneas de OC no completamente recibidas
                    open_lines = line.purchase_id.order_line.filtered(
                        lambda l: l.product_qty > l.qty_received
                    )
                    if open_lines:
                        open_lines.write({'date_planned': line.new_date_finish})

        # Replanificar órdenes de trabajo usando el botón nativo de Odoo
        for mo in mos_to_replan:
            if mo.state in ('confirmed', 'progress', 'to_close'):
                try:
                    mo.button_plan()
                except Exception as e:
                    _logger.warning(
                        'No se pudo replanificar la MO %s: %s', mo.name, e
                    )

        return {'type': 'ir.actions.act_window_close'}


# ======================================================================
# Modelo de línea del wizard
# ======================================================================

class MrpRescheduleWizardLine(models.TransientModel):
    _name = 'mrp.reschedule.wizard.line'
    _description = 'Línea de reprogramación en cascada'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'mrp.reschedule.wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    apply = fields.Boolean(string='Aplicar', default=True)

    record_type = fields.Selection(
        [('mrp', 'Fabricación'), ('purchase', 'Compra')],
        string='Tipo',
        required=True,
    )
    level = fields.Integer(default=0)
    parent_label = fields.Char(string='Generado por')

    production_id = fields.Many2one('mrp.production', string='Orden de fabricación')
    purchase_id = fields.Many2one('purchase.order', string='Orden de compra')

    # Campos de visualización calculados (no almacenados)
    record_label = fields.Char(
        string='Referencia',
        compute='_compute_display',
        store=False,
    )
    description_label = fields.Char(
        string='Producto / Proveedor',
        compute='_compute_display',
        store=False,
    )
    state_display = fields.Char(
        string='Estado actual',
        compute='_compute_display',
        store=False,
    )

    # Fechas
    current_date_start = fields.Datetime(string='Inicio actual')
    current_date_finish = fields.Datetime(string='Fin actual')
    new_date_start = fields.Datetime(string='Nuevo inicio')
    new_date_finish = fields.Datetime(string='Nuevo fin')

    @api.depends('level', 'record_type', 'production_id', 'purchase_id')
    def _compute_display(self):
        for line in self:
            prefix = INDENT_MAP.get(line.level, '         └─ ')

            if line.record_type == 'mrp' and line.production_id:
                mo = line.production_id
                line.record_label = f'{prefix}{mo.name}'
                line.description_label = (
                    mo.product_id.display_name if mo.product_id else ''
                )
                line.state_display = MRP_STATES.get(mo.state, mo.state)

            elif line.record_type == 'purchase' and line.purchase_id:
                po = line.purchase_id
                line.record_label = f'{prefix}{po.name}'
                line.description_label = (
                    po.partner_id.display_name if po.partner_id else ''
                )
                line.state_display = PO_STATES.get(po.state, po.state)

            else:
                line.record_label = f'{prefix}—'
                line.description_label = ''
                line.state_display = ''
