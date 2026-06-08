import logging
import pytz
from datetime import datetime, time, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INDENT_MAP = {0: '', 1: '└─ ', 2: '   └─ ', 3: '      └─ '}

MRP_STATES = {
    'draft': 'Borrador', 'confirmed': 'Confirmado', 'progress': 'En proceso',
    'to_close': 'Por cerrar', 'done': 'Hecho', 'cancel': 'Cancelado',
}
PO_STATES = {
    'draft': 'Presupuesto', 'sent': 'Enviado', 'to approve': 'Por aprobar',
    'purchase': 'OC confirmada', 'done': 'Bloqueado', 'cancel': 'Cancelado',
}


class MrpRescheduleWizard(models.TransientModel):
    _name = 'mrp.reschedule.wizard'
    _description = 'Reprogramación en cascada de órdenes de fabricación'

    # ── Campos ──────────────────────────────────────────────────────────────

    production_id = fields.Many2one(
        'mrp.production', string='Orden pivot', required=True,
        help='Orden de referencia. Las órdenes subsecuentes en los mismos WC '
             'se reprograman a partir de su nueva fecha de fin.',
    )
    new_finish_date = fields.Datetime(
        string='Nueva fecha de finalización', required=True,
        default=fields.Datetime.now,
    )
    delta_display = fields.Char(
        string='Desplazamiento', compute='_compute_delta_display',
    )
    has_lines = fields.Boolean(compute='_compute_has_lines')
    line_ids = fields.One2many(
        'mrp.reschedule.wizard.line', 'wizard_id', string='Cambios propuestos',
    )

    @api.depends('line_ids')
    def _compute_has_lines(self):
        for rec in self:
            rec.has_lines = bool(rec.line_ids)

    @api.depends('new_finish_date', 'production_id', 'production_id.date_finished')
    def _compute_delta_display(self):
        for rec in self:
            planned = rec.production_id.date_finished if rec.production_id else False
            if planned and rec.new_finish_date:
                secs = (rec.new_finish_date - planned).total_seconds()
                sign = '+' if secs >= 0 else '-'
                h = abs(secs) / 3600
                d = int(h // 24)
                rec.delta_display = (f'{sign}{d}d {int(h % 24)}h' if d else f'{sign}{int(h)}h')
            elif not planned:
                rec.delta_display = _('Sin fecha planificada en la orden pivot')
            else:
                rec.delta_display = '—'

    @api.onchange('production_id')
    def _onchange_production_id(self):
        if not self.production_id:
            return
        done_wos = self.production_id.workorder_ids.filtered(
            lambda w: w.state == 'done' and w.date_finished
        )
        if done_wos:
            self.new_finish_date = max(w.date_finished for w in done_wos)
        elif self.production_id.date_finished:
            self.new_finish_date = self.production_id.date_finished

    # ── Helpers — consultas de registros ────────────────────────────────────

    def _get_delta(self):
        self.ensure_one()
        planned = self.production_id.date_finished
        if not planned or not self.new_finish_date:
            return timedelta(0)
        return self.new_finish_date - planned

    def _get_subsequent_mos(self):
        """MOs pendientes en los mismos WC que el pivot, orden cronológico."""
        pivot = self.production_id
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
        pos = self.env['purchase.order']
        if mo.purchase_order_id and mo.purchase_order_id.state not in ('done', 'cancel'):
            pos |= mo.purchase_order_id
        if mo.purchase_line_id and mo.purchase_line_id.order_id:
            po = mo.purchase_line_id.order_id
            if po.state not in ('done', 'cancel'):
                pos |= po
        if mo.name:
            pos |= self.env['purchase.order'].search([
                ('origin', 'ilike', mo.name),
                ('state', 'not in', ('done', 'cancel')),
            ])
        return pos

    def _get_child_mos(self, mo):
        """
        MOs hijas vinculadas a la MO dada.
        Prioridad: x_parent_mo_id (campo tipado, confiable) → origin (texto, legado).
        """
        children = self.env['mrp.production'].search([
            ('x_parent_mo_id', '=', mo.id),
            ('state', 'not in', ['done', 'cancel']),
        ])
        if mo.name:
            origin_children = self.env['mrp.production'].search([
                ('origin', '=', mo.name),
                ('x_parent_mo_id', '=', False),
                ('state', 'not in', ['done', 'cancel']),
            ])
            children |= origin_children
        return children

    # ── Helpers — calendario ─────────────────────────────────────────────────

    def _get_mo_duration_hours(self, mo):
        """
        Duración prevista en horas:
          1. Suma de duration_expected de WOs (minutos → horas), si > 0.
          2. Diferencia date_finished − date_start.
          3. Fallback: 8 horas.
        """
        if mo.workorder_ids:
            total = sum(wo.duration_expected or 0.0 for wo in mo.workorder_ids)
            if total > 0:
                return total / 60.0
        if mo.date_start and mo.date_finished and mo.date_finished > mo.date_start:
            return (mo.date_finished - mo.date_start).total_seconds() / 3600.0
        return 8.0

    def _get_mo_calendar(self, mo, pivot_wc_ids=None):
        """
        Calendario del WC más relevante para una MO:
          1. WC compartido con los del pivot.
          2. Primer WC con calendario definido (por sequence de WO).
          3. Calendario de la empresa.
        """
        pivot_wc_ids = set(pivot_wc_ids or [])
        if mo.workorder_ids:
            if pivot_wc_ids:
                shared = mo.workorder_ids.mapped('workcenter_id').filtered(
                    lambda wc: wc.id in pivot_wc_ids and wc.resource_calendar_id
                )
                if shared:
                    return shared[0].resource_calendar_id
            for wo in mo.workorder_ids.sorted('sequence'):
                if wo.workcenter_id.resource_calendar_id:
                    return wo.workcenter_id.resource_calendar_id
        return self.env.company.resource_calendar_id

    def _schedule_duration(self, calendar, after_dt, duration_hours):
        """
        Primer slot de `duration_hours` horas laborables desde `after_dt` (UTC naive).
        Respeta el calendario de attendance del WC, sin considerar leaves.
        Returns: (start_dt, end_dt) — UTC naive.
        """
        if hasattr(after_dt, 'tzinfo') and after_dt.tzinfo:
            after_dt = after_dt.astimezone(pytz.utc).replace(tzinfo=None)
        if not calendar or not duration_hours:
            return (after_dt, after_dt + timedelta(hours=duration_hours or 8.0))

        tz = pytz.timezone(calendar.tz or 'UTC')
        remaining = float(duration_hours)
        start_result = None
        current = pytz.utc.localize(after_dt).astimezone(tz)

        for _ in range(365):
            day_date = current.date()
            weekday = str(day_date.weekday())
            day_atts = calendar.attendance_ids.filtered(
                lambda a: a.dayofweek == weekday
                and (not a.date_from or a.date_from <= day_date)
                and (not a.date_to   or a.date_to   >= day_date)
            ).sorted('hour_from')

            for att in day_atts:
                def _hm(hf):
                    h = int(hf)
                    return h, min(int(round((hf - h) * 60)), 59)
                h_from, m_from = _hm(att.hour_from)
                h_to,   m_to   = _hm(att.hour_to)
                iv_start = tz.localize(datetime.combine(day_date, time(h_from, m_from)))
                iv_end   = tz.localize(datetime.combine(day_date, time(h_to,   m_to)))
                if current >= iv_end:
                    continue
                seg_start = max(current, iv_start)
                seg_hours = (iv_end - seg_start).total_seconds() / 3600.0
                if seg_hours <= 1e-9:
                    continue
                if start_result is None:
                    start_result = seg_start
                if remaining <= seg_hours + 1e-9:
                    end_result = seg_start + timedelta(hours=remaining)
                    return (
                        start_result.astimezone(pytz.utc).replace(tzinfo=None),
                        end_result.astimezone(pytz.utc).replace(tzinfo=None),
                    )
                remaining -= seg_hours
                current = iv_end

            current = tz.localize(datetime.combine(day_date + timedelta(days=1), time(0, 0)))

        _logger.warning('MRP Reschedule: sin slot en 365 días (%s)', calendar.name)
        return (after_dt, after_dt + timedelta(hours=duration_hours))

    def _schedule_mo_block(self, mo, wc_anchors, base_dt, duration_override=None):
        """
        Programa todos los WOs de una MO secuencialmente usando wc_anchors.

        Para cada WO:
          earliest = max(prev_wo_end, wc_anchors[wc_id], base_dt)

        Actualiza wc_anchors en place.
        Returns: (mo_new_start, mo_new_end)
        """
        wos = mo.workorder_ids.sorted('sequence')
        total_wo_dur = sum(wo.duration_expected or 0.0 for wo in wos)

        if not wos or total_wo_dur <= 0:
            calendar = self._get_mo_calendar(mo)
            duration_h = duration_override or self._get_mo_duration_hours(mo)
            wc_times = [wc_anchors.get(wc.id, base_dt)
                        for wc in mo.workorder_ids.mapped('workcenter_id')]
            start_from = max([base_dt] + wc_times)
            wo_start, wo_end = self._schedule_duration(calendar, start_from, duration_h)
            for wc in mo.workorder_ids.mapped('workcenter_id'):
                wc_anchors[wc.id] = max(wc_anchors.get(wc.id, wo_end), wo_end)
            return (wo_start, wo_end)

        mo_start = None
        wo_prev_end = base_dt

        for wo in wos:
            wc = wo.workcenter_id
            wc_id = wc.id if wc else 0
            calendar = (
                wc.resource_calendar_id
                if wc and wc.resource_calendar_id
                else self.env.company.resource_calendar_id
            )
            wo_dur_h = (wo.duration_expected or 60.0) / 60.0
            earliest = max(wo_prev_end, wc_anchors.get(wc_id, base_dt), base_dt)
            wo_start, wo_end = self._schedule_duration(calendar, earliest, wo_dur_h)
            wc_anchors[wc_id] = wo_end
            if mo_start is None:
                mo_start = wo_start
            wo_prev_end = wo_end

        return (mo_start, wo_prev_end)

    # ── Helper — prioridad (Fase 3) ──────────────────────────────────────────

    def _sort_mos_by_priority(self, mos, sequence_overrides=None):
        """
        Ordena las MOs según el criterio configurado en Ajustes → Fabricación.
          - chronological (default): orden por date_start actual.
          - shortest_first: más cortas primero (SPT).
          - manual: según reschedule_sequence editado en el wizard.
        """
        priority = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.priority', 'chronological'
        )
        seq_map = sequence_overrides or {}
        dt_max = datetime(9999, 12, 31)

        if priority == 'shortest_first':
            return sorted(mos, key=lambda m: (
                self._get_mo_duration_hours(m),
                m.date_start or dt_max,
            ))
        elif priority == 'manual' and seq_map:
            return sorted(mos, key=lambda m: (
                seq_map.get(m.id, 9999),
                m.date_start or dt_max,
            ))
        # chronological (default)
        return sorted(mos, key=lambda m: (m.date_start or dt_max, m.id))

    # ── Construcción de líneas — ALGORITMO PRINCIPAL ─────────────────────────

    def _build_lines(self):
        """
        Reprogramación multi-WC con wc_anchors independientes por WC.

        Flujo:
          1. Inicializar wc_anchors desde pivot + MOs en progreso fuera del scope.
          2. Ordenar MOs subsecuentes según prioridad configurada.
          3. Para cada MO (nivel 0):
               - is_anchor=True (en progreso / marcada como fija): anclar sus WCs
                 sin moverla.
               - is_anchor=False: programar WO a WO con _schedule_mo_block().
          4. Para MOs hijas (nivel > 0): aplicar delta del padre, ajustar al
             calendario propio, generar advertencia si hubo ajuste.
          5. Para OCs vinculadas: propagar delta, advertir si ya confirmadas.
          6. Preservar ediciones del usuario entre recálculos (duration_hours,
             is_anchor, reschedule_sequence).
        """
        self.ensure_one()
        pivot = self.production_id

        # ── Preservar ediciones del usuario ─────────────────────────
        duration_overrides  = {}
        anchor_overrides    = {}
        sequence_overrides  = {}
        for line in self.line_ids:
            if line.record_type == 'mrp' and line.production_id:
                pid = line.production_id.id
                if line.duration_hours > 0:
                    duration_overrides[pid] = line.duration_hours
                anchor_overrides[pid] = line.is_anchor
                if line.reschedule_sequence:
                    sequence_overrides[pid] = line.reschedule_sequence

        self.line_ids.unlink()

        lines_vals     = []
        seq            = 10
        visited_mo_ids = {pivot.id}
        visited_po_ids = set()
        base_dt        = self.new_finish_date  # UTC naive

        # ── Recopilar MOs subsecuentes ───────────────────────────────
        subsequent_mos = self._get_subsequent_mos()

        # ── Todos los WCs relevantes ─────────────────────────────────
        pivot_wc_ids = set(pivot.workorder_ids.mapped('workcenter_id').ids)
        all_wc_ids   = set(pivot_wc_ids)
        for mo in subsequent_mos:
            all_wc_ids |= set(mo.workorder_ids.mapped('workcenter_id').ids)

        # ── Inicializar wc_anchors ────────────────────────────────────
        wc_anchors = {wc_id: base_dt for wc_id in pivot_wc_ids}

        if all_wc_ids:
            in_progress = self.env['mrp.production'].search([
                ('id', 'not in', [pivot.id] + subsequent_mos.ids),
                ('state', '=', 'progress'),
                ('workorder_ids.workcenter_id', 'in', list(all_wc_ids)),
            ])
            for mo in in_progress:
                est = mo.date_finished or (
                    mo.date_start + timedelta(hours=self._get_mo_duration_hours(mo))
                    if mo.date_start else None
                )
                if est:
                    for wo in mo.workorder_ids:
                        wc_id = wo.workcenter_id.id
                        if wc_id in all_wc_ids:
                            wc_anchors[wc_id] = max(wc_anchors.get(wc_id, est), est)

        # ── Ordenar por prioridad configurada (Fase 3) ───────────────
        mos_sorted = self._sort_mos_by_priority(subsequent_mos, sequence_overrides)

        # ── Función recursiva ────────────────────────────────────────

        def add_mo(mo, level, parent_label, parent_delta=None):
            nonlocal seq
            if mo.id in visited_mo_ids:
                return
            visited_mo_ids.add(mo.id)

            is_anchor  = anchor_overrides.get(mo.id, mo.state in ('done', 'progress'))
            duration_h = duration_overrides.get(mo.id) or self._get_mo_duration_hours(mo)
            warning_type = False
            warning_msg  = ''

            if is_anchor:
                new_start = mo.date_start
                new_end   = mo.date_finished
                if new_end:
                    for wo in mo.workorder_ids:
                        wc_id = wo.workcenter_id.id
                        if wc_id:
                            wc_anchors[wc_id] = max(wc_anchors.get(wc_id, new_end), new_end)

            elif level == 0:
                new_start, new_end = self._schedule_mo_block(
                    mo, wc_anchors, base_dt, duration_override=duration_h,
                )

            else:
                pd = parent_delta or timedelta(0)
                proposed_start = (mo.date_start + pd) if mo.date_start else base_dt
                child_wc_anchors = dict(wc_anchors)
                new_start, new_end = self._schedule_mo_block(
                    mo, child_wc_anchors, proposed_start, duration_override=duration_h,
                )
                if mo.date_start and abs((new_start - proposed_start).total_seconds()) > 900:
                    warning_type = 'child_adjusted'
                    warning_msg  = _(
                        'Ajustada al primer turno disponible (propuesta: %s)'
                    ) % proposed_start.strftime('%d/%m %H:%M')

            mo_delta = (
                (new_start - mo.date_start)
                if (new_start and mo.date_start) else timedelta(0)
            )

            lines_vals.append({
                'wizard_id':           self.id,
                'sequence':            seq,
                'reschedule_sequence': sequence_overrides.get(mo.id, seq),
                'record_type':         'mrp',
                'production_id':       mo.id,
                'level':               level,
                'parent_label':        parent_label,
                'duration_hours':      duration_h,
                'is_anchor':           is_anchor,
                'current_date_start':  mo.date_start,
                'current_date_finish': mo.date_finished,
                'new_date_start':      new_start,
                'new_date_finish':     new_end,
                'warning_type':        warning_type,
                'warning_message':     warning_msg,
                'apply':               not is_anchor,
            })
            seq += 10

            for po in self._get_pos_for_mo(mo):
                if po.id in visited_po_ids:
                    continue
                visited_po_ids.add(po.id)
                new_po_finish = (po.date_planned + mo_delta) if po.date_planned else False
                po_warn = po.state in ('purchase', 'done')
                lines_vals.append({
                    'wizard_id':           self.id,
                    'sequence':            seq,
                    'reschedule_sequence': seq,
                    'record_type':         'purchase',
                    'purchase_id':         po.id,
                    'level':               level + 1,
                    'parent_label':        mo.name,
                    'duration_hours':      0.0,
                    'is_anchor':           False,
                    'current_date_start':  po.date_order,
                    'current_date_finish': po.date_planned,
                    'new_date_start':      False,
                    'new_date_finish':     new_po_finish,
                    'warning_type':        'confirmed_po' if po_warn else False,
                    'warning_message':     (
                        _('OC en estado "%s" — revisar con proveedor')
                        % PO_STATES.get(po.state, po.state)
                    ) if po_warn else '',
                    'apply':               not is_anchor,
                })
                seq += 10

            for child in self._get_child_mos(mo):
                add_mo(child, level + 1, mo.name, parent_delta=mo_delta)

        for mo in mos_sorted:
            add_mo(mo, 0, pivot.name)

        if lines_vals:
            self.env['mrp.reschedule.wizard.line'].create(lines_vals)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_recalculate(self):
        self.ensure_one()
        if not self.production_id:
            raise UserError(_('Seleccione una orden de fabricación primero.'))
        if not self.production_id.date_finished:
            raise UserError(_(
                'La orden "%s" no tiene fecha de finalización planificada.'
            ) % self.production_id.name)
        self._build_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reprogramar en cascada'),
            'res_model': 'mrp.reschedule.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        """Aplica cambios marcados. Las líneas is_anchor (apply=False) se omiten."""
        self.ensure_one()
        active_lines = self.line_ids.filtered('apply')
        if not active_lines:
            raise UserError(_('No hay líneas marcadas para aplicar.'))

        mos_to_replan = self.env['mrp.production']

        for line in active_lines:
            if line.record_type == 'mrp' and line.production_id:
                vals = {}
                if line.new_date_start:
                    vals['date_start'] = line.new_date_start
                if line.new_date_finish:
                    vals['date_finished'] = line.new_date_finish
                if vals:
                    line.production_id.write(vals)
                    if line.production_id.workorder_ids:
                        mos_to_replan |= line.production_id

            elif line.record_type == 'purchase' and line.purchase_id:
                if line.new_date_finish:
                    open_lines = line.purchase_id.order_line.filtered(
                        lambda l: l.product_qty > l.qty_received
                    )
                    if open_lines:
                        open_lines.write({'date_planned': line.new_date_finish})

        for mo in mos_to_replan:
            if mo.state in ('confirmed', 'progress', 'to_close'):
                try:
                    mo.button_plan()
                except Exception as e:
                    _logger.warning('No se pudo replanificar %s: %s', mo.name, e)

        return {'type': 'ir.actions.act_window_close'}


class MrpRescheduleWizardLine(models.TransientModel):
    _name = 'mrp.reschedule.wizard.line'
    _description = 'Línea de reprogramación en cascada'
    _order = 'reschedule_sequence, id'

    wizard_id    = fields.Many2one('mrp.reschedule.wizard', required=True, ondelete='cascade')
    sequence     = fields.Integer(default=10)

    # Fase 3: campo de ordenación manual editable en el wizard
    reschedule_sequence = fields.Integer(
        string='Orden',
        default=0,
        help='Número de orden para la prioridad manual. '
             'Editable en líneas de nivel 0 cuando el criterio es "Manual".',
    )

    apply     = fields.Boolean(string='Aplicar', default=True)
    is_anchor = fields.Boolean(
        string='Fijo', default=False,
        help='MO tratada como punto fijo — no se reprograma. '
             'Las MOs en progreso o terminadas son fijas por defecto.',
    )

    record_type  = fields.Selection(
        [('mrp', 'Fabricación'), ('purchase', 'Compra')], string='Tipo', required=True,
    )
    level        = fields.Integer(default=0)
    parent_label = fields.Char(string='Generado por')

    production_id = fields.Many2one('mrp.production',  string='Orden de fabricación')
    purchase_id   = fields.Many2one('purchase.order',  string='Orden de compra')

    duration_hours = fields.Float(
        string='Duración (hs)', digits=(10, 2),
        help='Calculada desde los tiempos de WO. Editable antes de confirmar.',
    )
    warning_type = fields.Selection(
        [('confirmed_po', 'OC confirmada'), ('child_adjusted', 'Hija ajustada')],
        string='Tipo advertencia', default=False,
    )
    warning_message  = fields.Char(string='Advertencia')
    record_label     = fields.Char(string='Referencia',           compute='_compute_display', store=False)
    description_label= fields.Char(string='Producto / Proveedor', compute='_compute_display', store=False)
    state_display    = fields.Char(string='Estado actual',        compute='_compute_display', store=False)

    current_date_start  = fields.Datetime(string='Inicio actual')
    current_date_finish = fields.Datetime(string='Fin actual')
    new_date_start      = fields.Datetime(string='Nuevo inicio')
    new_date_finish     = fields.Datetime(string='Nuevo fin')

    @api.depends('level', 'record_type', 'production_id', 'purchase_id')
    def _compute_display(self):
        for line in self:
            prefix = INDENT_MAP.get(line.level, '         └─ ')
            if line.record_type == 'mrp' and line.production_id:
                mo = line.production_id
                line.record_label      = f'{prefix}{mo.name}'
                line.description_label = mo.product_id.display_name if mo.product_id else ''
                line.state_display     = MRP_STATES.get(mo.state, mo.state)
            elif line.record_type == 'purchase' and line.purchase_id:
                po = line.purchase_id
                line.record_label      = f'{prefix}{po.name}'
                line.description_label = po.partner_id.display_name if po.partner_id else ''
                line.state_display     = PO_STATES.get(po.state, po.state)
            else:
                line.record_label = f'{prefix}—'
                line.description_label = ''
                line.state_display = ''
