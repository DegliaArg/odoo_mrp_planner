import logging
import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .mrp_schedule_mixin import INDENT_MAP

_logger = logging.getLogger(__name__)


def _get_old_code(mo):
    """
    Devuelve x_studio_cdigo_viejo (campo Studio en product.template) para una
    mrp.production.  La delegación de herencia de Odoo no propaga el campo al
    _fields de product.product, por eso buscamos en product_tmpl_id._fields.
    Retorna '' si el campo no existe en la instancia.
    """
    # 1. Directo en la orden de fabricación (por si Studio lo puso ahí)
    if 'x_studio_cdigo_viejo' in mo._fields:
        return mo.x_studio_cdigo_viejo or ''
    # 2. En product.template vía product_id.product_tmpl_id
    product = getattr(mo, 'product_id', None)
    if product:
        tmpl = getattr(product, 'product_tmpl_id', None)
        if tmpl and 'x_studio_cdigo_viejo' in tmpl._fields:
            return tmpl.x_studio_cdigo_viejo or ''
    return ''


MRP_STATES = {
    'draft': 'Borrador', 'confirmed': 'Confirmado', 'progress': 'En proceso',
    'to_close': 'Por cerrar', 'done': 'Hecho', 'cancel': 'Cancelado',
}
PO_STATES = {
    'draft': 'Presupuesto', 'sent': 'Enviado', 'to approve': 'Por aprobar',
    'purchase': 'OC confirmada', 'done': 'Bloqueado', 'cancel': 'Cancelado',
}


class MrpReschedulePlan(models.Model):
    _name = 'mrp.reschedule.plan'
    _description = 'Plan de reprogramación en cascada'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mrp.schedule.mixin']
    _order = 'id desc'

    name = fields.Char(string='Referencia', readonly=True, default='Nuevo', copy=False)
    state = fields.Selection([
        ('draft',       'Borrador'),
        ('calculated',  'Calculado'),
        ('applied',     'Aplicado'),
        ('cancelled',   'Cancelado'),
    ], string='Estado', default='draft', tracking=True, copy=False)

    active = fields.Boolean(default=True, string='Activo')

    production_id = fields.Many2one(
        'mrp.production', string='Orden pivot',
        help='Orden de referencia. Dejar vacío para reprogramar globalmente '
             'todas las órdenes activas a partir de "Replanificar desde".',
    )
    new_finish_date = fields.Datetime(
        string='Nueva fecha de finalización', default=fields.Datetime.now,
    )
    replan_from = fields.Datetime(
        string='Replanificar desde',
        default=fields.Datetime.now,
        help='Punto de inicio para el modo global (sin pivot). '
             'En modo pivot se usa la nueva fecha de fin de la MO pivot.',
    )
    delta_display = fields.Char(string='Desplazamiento', compute='_compute_delta_display')
    line_ids    = fields.One2many('mrp.reschedule.plan.line',    'plan_id', string='Líneas')
    wc_line_ids = fields.One2many('mrp.reschedule.plan.wc.line', 'plan_id', string='Líneas WC')
    line_count  = fields.Integer(compute='_compute_line_count')

    applied_date = fields.Datetime(string='Fecha de aplicación', readonly=True, copy=False)
    applied_by = fields.Many2one('res.users', string='Aplicado por', readonly=True, copy=False)

    # ── Migración ────────────────────────────────────────────────────────────

    def _auto_init(self):
        super()._auto_init()
        # production_id pasa a ser opcional (modo global sin pivot)
        self.env.cr.execute("SAVEPOINT drop_nn_production_id")
        try:
            self.env.cr.execute(
                "ALTER TABLE mrp_reschedule_plan "
                "ALTER COLUMN production_id DROP NOT NULL"
            )
            self.env.cr.execute("RELEASE SAVEPOINT drop_nn_production_id")
        except Exception:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT drop_nn_production_id")

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mrp.reschedule.plan')
                    or 'Nuevo'
                )
        return super().create(vals_list)

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
        if self.state == 'calculated':
            self.state = 'draft'

    @api.onchange('new_finish_date')
    def _onchange_new_finish_date(self):
        if self.state == 'calculated':
            self.state = 'draft'

    # ── Campos computados ────────────────────────────────────────────────────

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('new_finish_date', 'replan_from', 'production_id', 'production_id.date_finished')
    def _compute_delta_display(self):
        for rec in self:
            if not rec.production_id:
                dt = rec.replan_from
                rec.delta_display = (
                    _('Replan global desde ') + dt.strftime('%d/%m/%Y %H:%M')
                    if dt else '—'
                )
                continue
            planned = rec.production_id.date_finished
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

    # ── Acciones de estado ───────────────────────────────────────────────────

    def action_calculate(self):
        self.ensure_one()
        if self.production_id:
            if not self.production_id.date_finished:
                raise UserError(_(
                    'La orden "%s" no tiene fecha de finalización planificada.'
                ) % self.production_id.name)
        else:
            if not self.replan_from:
                raise UserError(_('Defina la fecha de inicio para el replan global.'))
        self._build_lines()
        self.state = 'calculated'

    def action_reset_draft(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.wc_line_ids.unlink()
        self.state = 'draft'

    def action_cancel(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.wc_line_ids.unlink()
        self.write({'state': 'cancelled'})
        self.message_post(body=_('Plan cancelado.'))

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise UserError(_(
                'Solo los responsables de fabricación pueden aplicar un plan de reprogramación.'
            ))
        if self.state != 'calculated':
            raise UserError(_('El plan debe estar en estado Calculado para aplicar.'))
        active_lines = self.line_ids.filtered('apply')
        if not active_lines:
            raise UserError(_('No hay líneas marcadas para aplicar.'))

        pivot = self.production_id
        if pivot:
            delta = self._get_delta()
            if pivot.state == 'confirmed' and delta:
                pivot_vals = {'date_finished': self.new_finish_date}
                if pivot.date_start:
                    pivot_vals['date_start'] = pivot.date_start + delta
                pivot.write(pivot_vals)
                if pivot.workorder_ids:
                    try:
                        pivot.button_plan()
                    except Exception as e:
                        _logger.warning('No se pudo replanificar pivot %s: %s', pivot.name, e)

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

        self.write({
            'state': 'applied',
            'applied_date': fields.Datetime.now(),
            'applied_by': self.env.user.id,
        })
        self.message_post(
            body=_('Plan aplicado: %d líneas actualizadas.') % len(active_lines)
        )

    def action_open_gantt(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Primero calcule los cambios propuestos.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gantt propuesto — %s') % self.name,
            'res_model': 'mrp.reschedule.plan.line',
            'view_mode': 'gantt',
            'domain': [
                ('plan_id', '=', self.id),
                ('record_type', '=', 'mrp'),
                ('new_date_start', '!=', False),
            ],
            'context': {'create': False, 'edit': False},
            'target': 'current',
        }

    def action_open_current_gantt(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Primero calcule los cambios propuestos.'))
        gantt_view = self.env.ref(
            'odoo_mrp_reschedule.mrp_reschedule_plan_line_gantt_current',
            raise_if_not_found=False,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gantt actual — %s') % self.name,
            'res_model': 'mrp.reschedule.plan.line',
            'view_mode': 'gantt',
            'views': [(gantt_view.id if gantt_view else False, 'gantt')],
            'domain': [
                ('plan_id', '=', self.id),
                ('record_type', '=', 'mrp'),
                ('current_date_start', '!=', False),
            ],
            'context': {'create': False, 'edit': False},
            'target': 'current',
        }

    # ── Helpers — consultas ──────────────────────────────────────────────────

    def _get_delta(self):
        self.ensure_one()
        planned = self.production_id.date_finished
        if not planned or not self.new_finish_date:
            return timedelta(0)
        return self.new_finish_date - planned

    def _get_subsequent_mos(self):
        pivot = self.production_id
        if not pivot.date_start:
            return self.env['mrp.production']
        wc_ids = pivot.workorder_ids.mapped('workcenter_id').ids
        if not wc_ids:
            return self.env['mrp.production']
        return self.env['mrp.production'].search([
            ('id', '!=', pivot.id),
            ('state', '=', 'confirmed'),
            ('date_start', '!=', False),
            ('date_start', '>=', pivot.date_start),
            ('workorder_ids.workcenter_id', 'in', wc_ids),
        ], order='date_start, id')

    def _get_all_active_mos(self):
        """Modo global: solo MOs confirmadas (pendientes de iniciar) con fecha de inicio."""
        return self.env['mrp.production'].search([
            ('state', '=', 'confirmed'),
            ('date_start', '!=', False),
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
        children = self.env['mrp.production'].search([
            ('x_parent_mo_id', '=', mo.id),
            ('state', 'not in', ['done', 'cancel']),
        ])
        if mo.name:
            children |= self.env['mrp.production'].search([
                ('origin', '=', mo.name),
                ('x_parent_mo_id', '=', False),
                ('state', 'not in', ['done', 'cancel']),
            ])
        return children

    # ── Helpers — calendario ─────────────────────────────────────────────────

    def _get_mo_duration_hours(self, mo):
        if mo.workorder_ids:
            total = sum(wo.duration_expected or 0.0 for wo in mo.workorder_ids)
            if total > 0:
                return total / 60.0
        if mo.date_start and mo.date_finished and mo.date_finished > mo.date_start:
            return (mo.date_finished - mo.date_start).total_seconds() / 3600.0
        return 8.0

    def _get_mo_calendar(self, mo, pivot_wc_ids=None):
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

    def _schedule_mo_block(self, mo, wc_anchors, base_dt, duration_override=None, wc_collector=None):
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
        scale = (duration_override / (total_wo_dur / 60.0)
                 if duration_override and total_wo_dur > 0 else None)

        for wo in wos:
            wc = wo.workcenter_id
            wc_id = wc.id if wc else 0
            calendar = (
                wc.resource_calendar_id if wc and wc.resource_calendar_id
                else self.env.company.resource_calendar_id
            )
            wo_dur_h = (wo.duration_expected or 60.0) / 60.0
            if scale is not None:
                wo_dur_h *= scale
            earliest = max(wo_prev_end, wc_anchors.get(wc_id, base_dt), base_dt)
            wo_start, wo_end = self._schedule_duration(calendar, earliest, wo_dur_h)
            wc_anchors[wc_id] = wo_end
            if wc_collector is not None and wc_id and wo_start and wo_end:
                wc_collector.append({
                    'production_id': mo.id,
                    'workorder_id':  wo.id,
                    'workcenter_id': wc_id,
                    'new_date_start':  wo_start,
                    'new_date_finish': wo_end,
                })
            if mo_start is None:
                mo_start = wo_start
            wo_prev_end = wo_end

        return (mo_start, wo_prev_end)

    def _sort_mos_by_priority(self, mos, sequence_overrides=None):
        priority = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.priority', 'chronological'
        )
        seq_map = sequence_overrides or {}
        dt_max = datetime(9999, 12, 31)
        if priority == 'shortest_first':
            return sorted(mos, key=lambda m: (
                self._get_mo_duration_hours(m), m.date_start or dt_max,
            ))
        elif priority == 'manual' and seq_map:
            return sorted(mos, key=lambda m: (
                seq_map.get(m.id, 9999), m.date_start or dt_max,
            ))
        return sorted(mos, key=lambda m: (m.date_start or dt_max, m.id))

    # ── Construcción de líneas ────────────────────────────────────────────────

    def _build_lines(self):
        self.ensure_one()
        pivot = self.production_id
        is_global = not pivot

        duration_overrides = {}
        anchor_overrides = {}
        sequence_overrides = {}
        forced_start_overrides = {}
        for line in self.line_ids:
            if line.record_type == 'mrp' and line.production_id:
                pid = line.production_id.id
                if line.duration_hours > 0:
                    duration_overrides[pid] = line.duration_hours
                anchor_overrides[pid] = line.is_anchor
                if line.reschedule_sequence:
                    sequence_overrides[pid] = line.reschedule_sequence
                if line.forced_start_date:
                    forced_start_overrides[pid] = line.forced_start_date

        self.line_ids.unlink()
        self.wc_line_ids.unlink()

        lines_vals = []
        wc_lines_data = []
        seq = 10
        visited_mo_ids = set()
        visited_po_ids = set()

        # En modo pivot el pivot es siempre un anchor (punto fijo de referencia)
        if pivot:
            anchor_overrides.setdefault(pivot.id, True)

        if is_global:
            base_dt = self.replan_from or fields.Datetime.now()
            if hasattr(base_dt, 'tzinfo') and base_dt.tzinfo:
                base_dt = base_dt.astimezone(pytz.utc).replace(tzinfo=None)
            subsequent_mos = self._get_all_active_mos()
            wc_anchors = {}
            pivot_wc_ids = set()
        else:
            base_dt = self.new_finish_date
            subsequent_mos = self._get_subsequent_mos()
            pivot_wc_ids = set(pivot.workorder_ids.mapped('workcenter_id').ids)
            wc_anchors = {wc_id: base_dt for wc_id in pivot_wc_ids}

        all_wc_ids = set(pivot_wc_ids)
        for mo in subsequent_mos:
            all_wc_ids |= set(mo.workorder_ids.mapped('workcenter_id').ids)

        if all_wc_ids:
            exclude_ids = ([] if is_global else [pivot.id]) + subsequent_mos.ids
            in_progress = self.env['mrp.production'].search([
                ('id', 'not in', exclude_ids),
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

        mos_sorted = self._sort_mos_by_priority(subsequent_mos, sequence_overrides)

        def add_mo(mo, level, parent_label, parent_delta=None):
            nonlocal seq
            if mo.id in visited_mo_ids:
                return
            visited_mo_ids.add(mo.id)

            is_anchor    = anchor_overrides.get(mo.id, mo.state in ('done', 'progress', 'to_close'))
            forced_start = forced_start_overrides.get(mo.id)
            duration_h   = duration_overrides.get(mo.id) or self._get_mo_duration_hours(mo)
            warning_type = False
            warning_msg  = ''

            if is_anchor:
                if forced_start:
                    # Anchor con inicio forzado: calcular fin respetando calendario
                    calendar = self._get_mo_calendar(mo)
                    new_start, new_end = self._schedule_duration(
                        calendar, forced_start, duration_h
                    )
                else:
                    new_start = mo.date_start
                    new_end   = mo.date_finished
                    if not new_end and mo.date_start:
                        new_end = mo.date_start + timedelta(hours=duration_h)
                if new_end:
                    for wo in mo.workorder_ids:
                        wc_id = wo.workcenter_id.id
                        if wc_id:
                            wc_anchors[wc_id] = max(wc_anchors.get(wc_id, new_end), new_end)
            elif level == 0:
                new_start, new_end = self._schedule_mo_block(
                    mo, wc_anchors, base_dt, duration_override=duration_h,
                    wc_collector=wc_lines_data,
                )
            else:
                pd = parent_delta or timedelta(0)
                proposed_start = (mo.date_start + pd) if mo.date_start else base_dt
                child_wc_anchors = dict(wc_anchors)
                new_start, new_end = self._schedule_mo_block(
                    mo, child_wc_anchors, proposed_start, duration_override=duration_h,
                    wc_collector=wc_lines_data,
                )
                if mo.date_start and abs((new_start - proposed_start).total_seconds()) > 900:
                    warning_type = 'child_adjusted'
                    warning_msg = _(
                        'Ajustada al primer turno disponible (propuesta: %s)'
                    ) % proposed_start.strftime('%d/%m %H:%M')

            mo_delta = (
                (new_start - mo.date_start)
                if (new_start and mo.date_start) else timedelta(0)
            )

            lines_vals.append({
                'plan_id':             self.id,
                'sequence':            seq,
                'reschedule_sequence': sequence_overrides.get(mo.id, seq),
                'record_type':         'mrp',
                'production_id':       mo.id,
                'level':               level,
                'parent_label':        parent_label,
                'duration_hours':      duration_h,
                'is_anchor':           is_anchor,
                'forced_start_date':   forced_start or False,
                'current_date_start':  mo.date_start,
                'current_date_finish': mo.date_finished,
                'new_date_start':      new_start,
                'new_date_finish':     new_end,
                'warning_type':        warning_type,
                'warning_message':     warning_msg,
                # Aplicar si no es anchor, O si es anchor con inicio forzado
                'apply':               not is_anchor or bool(forced_start),
            })
            seq += 10

            for po in self._get_pos_for_mo(mo):
                if po.id in visited_po_ids:
                    continue
                visited_po_ids.add(po.id)
                new_po_finish = (po.date_planned + mo_delta) if po.date_planned else False
                po_warn = po.state in ('purchase', 'done')
                lines_vals.append({
                    'plan_id':             self.id,
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

        root_label = pivot.name if pivot else ''

        # Agregar el pivot primero (como anchor) y luego sus hijas en cascada
        if not is_global and pivot:
            add_mo(pivot, 0, '')

        for mo in mos_sorted:
            add_mo(mo, 0, root_label)

        if lines_vals:
            self.env['mrp.reschedule.plan.line'].create(lines_vals)
        if wc_lines_data:
            for d in wc_lines_data:
                d['plan_id'] = self.id
            self.env['mrp.reschedule.plan.wc.line'].create(wc_lines_data)


class MrpReschedulePlanLine(models.Model):
    _name = 'mrp.reschedule.plan.line'
    _description = 'Línea de plan de reprogramación en cascada'
    _order = 'reschedule_sequence, id'
    _rec_name = 'record_label'

    plan_id  = fields.Many2one('mrp.reschedule.plan', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    reschedule_sequence = fields.Integer(string='Orden', default=0)

    apply             = fields.Boolean(string='Aplicar', default=True)
    is_anchor         = fields.Boolean(string='Fijo', default=False)
    forced_start_date = fields.Datetime(
        string='Inicio forzado',
        help='Si está definido en una línea fija, el algoritmo programa '
             'esta OF a partir de esta fecha (respetando el calendario del WC) '
             'en lugar de usar su fecha actual.',
    )
    color     = fields.Integer(compute='_compute_color', store=True)

    record_type  = fields.Selection(
        [('mrp', 'Fabricación'), ('purchase', 'Compra')], string='Tipo', required=True,
    )
    level        = fields.Integer(default=0)
    parent_label = fields.Char(string='Generado por')

    production_id = fields.Many2one('mrp.production', string='Orden de fabricación')
    purchase_id   = fields.Many2one('purchase.order',  string='Orden de compra')

    duration_hours = fields.Float(string='Duración (hs)', digits=(10, 2))
    warning_type = fields.Selection(
        [('confirmed_po', 'OC confirmada'), ('child_adjusted', 'Hija ajustada')],
        string='Tipo advertencia', default=False,
    )
    warning_message = fields.Char(string='Advertencia')

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
        for line in self:
            prefix = INDENT_MAP.get(line.level, ' ' * 9 + '└─ ')
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
        for line in self:
            if line.record_type == 'mrp' and line.production_id:
                line.state_display = MRP_STATES.get(line.production_id.state, line.production_id.state)
            elif line.record_type == 'purchase' and line.purchase_id:
                line.state_display = PO_STATES.get(line.purchase_id.state, line.purchase_id.state)
            else:
                line.state_display = ''

    @api.depends('current_date_finish', 'new_date_finish')
    def _compute_delta_display_line(self):
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


class MrpReschedulePlanWcLine(models.Model):
    _name = 'mrp.reschedule.plan.wc.line'
    _description = 'Carga de centro de trabajo — plan de reprogramación'
    _order = 'new_date_start, id'
    _rec_name = 'record_label'

    plan_id       = fields.Many2one('mrp.reschedule.plan', required=True, ondelete='cascade', string='Plan')
    production_id = fields.Many2one('mrp.production', string='Orden de fabricación')
    workorder_id  = fields.Many2one('mrp.workorder',  string='Operación')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Centro de trabajo')

    new_date_start  = fields.Datetime(string='Nuevo inicio')
    new_date_finish = fields.Datetime(string='Nuevo fin')

    record_label = fields.Char(string='OF',        compute='_compute_display', store=True)
    wo_name      = fields.Char(string='Operación', compute='_compute_display', store=True)
    color        = fields.Integer(compute='_compute_color', store=True)

    plan_state = fields.Selection(related='plan_id.state', store=True, string='Estado plan')
    plan_name  = fields.Char(related='plan_id.name',  store=True, string='Plan')

    @api.depends('production_id', 'workorder_id')
    def _compute_display(self):
        for line in self:
            mo = line.production_id
            wo = line.workorder_id
            if mo:
                code = _get_old_code(mo)
                line.record_label = f'[{code}] {mo.name}' if code else mo.name
            else:
                line.record_label = '—'
            line.wo_name = wo.name if wo else (
                mo.product_id.display_name if mo and mo.product_id else ''
            )

    @api.depends('plan_state')
    def _compute_color(self):
        for line in self:
            if line.plan_state == 'applied':
                line.color = 10   # verde
            elif line.plan_state == 'calculated':
                line.color = 4    # azul
            else:
                line.color = 0    # gris
