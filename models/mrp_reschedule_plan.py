"""
Módulo: mrp_reschedule_plan.py
Modelo: mrp.reschedule.plan

Motor de reprogramación en cascada para órdenes de fabricación (MOs) y compras (POs).

Responsabilidades:
- Calcular nuevas fechas de inicio/fin para todas las MOs dependientes de una
  orden pivot (o para todas las MOs activas en modo global) dado un desplazamiento.
- Respetar los calendarios laborales de los centros de trabajo y los anchos de
  capacidad compartida entre órdenes.
- Registrar las líneas propuestas (MrpReschedulePlanLine) y la carga detallada
  por centro de trabajo (MrpReschedulePlanWcLine) antes de aplicar cambios.
- Aplicar los cambios en Odoo sólo al ejecutar action_apply, con control de
  permisos por grupo de seguridad.

Relacionado con:
- mrp.production: órdenes de fabricación que se reprograman.
- purchase.order: órdenes de compra vinculadas que se actualizan en cascada.
- mrp.reschedule.config: configuración global del módulo (heurística WC, etc.).
- mrp.schedule.mixin: mixin que provee _schedule_duration y INDENT_MAP.
- mrp.reschedule.cascade.mixin: motor de cálculo de cascada (_build_lines y helpers).
"""

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .mrp_reschedule_cascade_mixin import MrpRescheduleCascadeMixin

_logger = logging.getLogger(__name__)


class MrpReschedulePlan(MrpRescheduleCascadeMixin, models.Model):
    _name = 'mrp.reschedule.plan'
    _description = 'Plan de reprogramación en cascada'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mrp.schedule.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Referencia', readonly=True, default='Nuevo', copy=False,
        help='Secuencia autogenerada al crear el plan (ej. REPLAN/2024/001).',
    )
    state = fields.Selection([
        ('draft',       'Borrador'),
        ('calculated',  'Calculado'),
        ('applied',     'Aplicado'),
        ('cancelled',   'Cancelado'),
    ], string='Estado', default='draft', tracking=True, copy=False)

    active = fields.Boolean(default=True, string='Activo')

    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    production_id = fields.Many2one(
        'mrp.production', string='Orden pivot',
        help='Orden de referencia. Dejar vacío para reprogramar globalmente '
             'todas las órdenes activas a partir de "Replanificar desde".',
    )
    new_finish_date = fields.Datetime(
        string='Nueva fecha de finalización', default=fields.Datetime.now,
        help='Nueva fecha de fin deseada para la orden pivot. '
             'El algoritmo calcula el desplazamiento respecto a la fecha actual '
             'y lo propaga en cascada a todas las órdenes dependientes.',
    )
    replan_from = fields.Datetime(
        string='Replanificar desde',
        default=fields.Datetime.now,
        help='Punto de inicio para el modo global (sin pivot). '
             'En modo pivot se usa la nueva fecha de fin de la MO pivot.',
    )
    delta_display = fields.Char(
        string='Desplazamiento', compute='_compute_delta_display',
        help='Diferencia entre la nueva fecha de fin y la planificada actualmente '
             'en la orden pivot (ej. +2d 4h). En modo global muestra la fecha de inicio.',
    )
    line_ids    = fields.One2many('mrp.reschedule.plan.line',    'plan_id', string='Líneas')
    wc_line_ids = fields.One2many('mrp.reschedule.plan.wc.line', 'plan_id', string='Líneas WC')
    line_count  = fields.Integer(
        compute='_compute_line_count',
        help='Cantidad de líneas (MOs + POs) incluidas en este plan.',
    )

    applied_date = fields.Datetime(
        string='Fecha de aplicación', readonly=True, copy=False,
        help='Momento en que se ejecutó action_apply y se escribieron las fechas en Odoo.',
    )
    applied_by = fields.Many2one(
        'res.users', string='Aplicado por', readonly=True, copy=False,
        help='Usuario que ejecutó la acción "Aplicar plan".',
    )

    # ── Migración ────────────────────────────────────────────────────────────

    def _auto_init(self):
        """Migración DDL: elimina NOT NULL de production_id y rellena company_id en planes históricos."""
        super()._auto_init()
        cr = self.env.cr
        # production_id pasa a ser opcional (modo global sin pivot)
        cr.execute("SAVEPOINT drop_nn_production_id")
        try:
            cr.execute(
                "ALTER TABLE mrp_reschedule_plan "
                "ALTER COLUMN production_id DROP NOT NULL"
            )
            cr.execute("RELEASE SAVEPOINT drop_nn_production_id")
        except Exception:
            cr.execute("ROLLBACK TO SAVEPOINT drop_nn_production_id")
        # Fill company_id for plans created before multi-company support
        cr.execute("SAVEPOINT fill_plan_company_id")
        try:
            cr.execute("""
                UPDATE mrp_reschedule_plan
                SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
                WHERE company_id IS NULL
            """)
            cr.execute("RELEASE SAVEPOINT fill_plan_company_id")
        except Exception:
            cr.execute("ROLLBACK TO SAVEPOINT fill_plan_company_id")

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """
        Asigna número de secuencia automático al crear un plan.

        Reemplaza el valor por defecto 'Nuevo' por el siguiente número de la
        secuencia 'mrp.reschedule.plan'. Si la secuencia no está configurada
        en la instancia, mantiene 'Nuevo' como fallback.

        :param vals_list: lista de dicts con los valores a crear.
        :returns: recordset con los registros creados.
        """
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mrp.reschedule.plan')
                    or 'Nuevo'
                )
        return super().create(vals_list)

    @api.onchange('production_id')
    def _onchange_production_id(self):
        """Actualiza new_finish_date con la fecha real de fin de la nueva orden pivot."""
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
        """Invalida el cálculo previo si el usuario modifica la fecha objetivo."""
        if self.state == 'calculated':
            self.state = 'draft'

    # ── Campos computados ────────────────────────────────────────────────────

    @api.depends('line_ids')
    def _compute_line_count(self):
        """
        Calcula line_count para cada registro.

        Fórmula: longitud de line_ids (incluye MOs y POs).
        Depende de: line_ids.
        """
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('new_finish_date', 'replan_from', 'production_id', 'production_id.date_finished')
    def _compute_delta_display(self):
        """
        Calcula delta_display para cada registro.

        Fórmula: en modo pivot, diferencia entre new_finish_date y date_finished
        del pivot expresada como ±Xd Yh. En modo global, muestra la fecha de
        replan_from como texto informativo.
        Depende de: new_finish_date, replan_from, production_id.date_finished.
        """
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
        """
        Construye las líneas propuestas de reprogramación sin modificar registros en Odoo.

        Valida precondiciones (fecha de fin en la pivot o fecha de inicio en modo global),
        delega la construcción al método _build_lines y transiciona el estado a 'calculated'.

        :raises UserError: si la orden pivot no tiene fecha_finished planificada.
        :raises UserError: si en modo global falta el campo replan_from.
        """
        self.ensure_one()
        if self.production_id:
            if not self.production_id.date_finished:
                raise UserError(_(
                    'La orden "%s" no tiene fecha de finalización planificada.'
                ) % self.production_id.name)
        else:
            if not self.replan_from:
                raise UserError(_(
                    'Falta la fecha de inicio para el replan global. '
                    'Completá el campo "Replanificar desde" antes de calcular.'
                ))
        self._build_lines()
        self.state = 'calculated'

    def action_reset_draft(self):
        """
        Vuelve el plan a estado borrador y borra todas las líneas calculadas.

        Permite recalcular el plan con parámetros modificados. Solo usuarios con
        el permiso 'Producción - Planificar' o superior pueden ejecutar esta acción.

        :raises UserError: si el usuario no tiene el grupo de planificación o admin.
        """
        self.ensure_one()
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner.group_prod') or
                u.has_group('odoo_mrp_planner.group_admin') or
                u.has_group('base.group_system')):
            raise UserError(_(
                'Solo los usuarios con permiso "Producción - Planificar" o "Administrador" '
                'pueden recalcular un plan de reprogramación.'
            ))
        self.line_ids.unlink()
        self.wc_line_ids.unlink()
        self.state = 'draft'

    def action_cancel(self):
        """
        Cancela el plan y elimina todas las líneas sin aplicar cambios en Odoo.

        :raises UserError: si el usuario no tiene el grupo de planificación o admin.
        """
        self.ensure_one()
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner.group_prod') or
                u.has_group('odoo_mrp_planner.group_admin') or
                u.has_group('base.group_system')):
            raise UserError(_(
                'Solo los usuarios con permiso "Producción - Planificar" o "Administrador" '
                'pueden cancelar un plan de reprogramación.'
            ))
        self.line_ids.unlink()
        self.wc_line_ids.unlink()
        self.write({'state': 'cancelled'})
        self.message_post(body=_('Plan cancelado.'))

    def action_apply(self):
        """
        Aplica las fechas propuestas en las MOs y POs marcadas con 'apply=True'.

        Secuencia de operaciones:
        1. Verifica permisos del usuario.
        2. Requiere estado 'calculated' y al menos una línea marcada para aplicar.
        3. En modo pivot: desplaza fechas de la MO pivot si está confirmada.
        4. Escribe date_start / date_finished en cada MO de las líneas activas.
        5. Actualiza date_planned en las líneas abiertas de las POs activas.
        6. Ejecuta button_plan() en todas las MOs modificadas para re-secuenciar WOs.
        7. Registra applied_date, applied_by y publica mensaje en el chatter.

        :raises UserError: si el usuario no tiene permisos de planificación.
        :raises UserError: si el plan no está en estado 'calculated'.
        :raises UserError: si no hay líneas marcadas para aplicar.
        """
        self.ensure_one()
        u = self.env.user
        can_apply = (
            u.has_group('odoo_mrp_planner.group_prod') or
            u.has_group('odoo_mrp_planner.group_admin') or
            u.has_group('base.group_system')
        )
        if not can_apply:
            raise UserError(_(
                'Solo los usuarios con permiso "Producción - Planificar" o "Administrador" '
                'pueden aplicar un plan de reprogramación.'
            ))
        if self.state != 'calculated':
            raise UserError(_(
                'El plan está en estado "%s". Primero calculá el plan (botón Calcular) '
                'para poder aplicarlo.'
            ) % self.state)
        active_lines = self.line_ids.filtered('apply')
        if not active_lines:
            raise UserError(_(
                'No hay líneas marcadas para aplicar. Activá al menos una línea '
                'con el campo "Aplicar" antes de continuar.'
            ))

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
        """
        Abre la vista Gantt con las fechas PROPUESTAS (new_date_start / new_date_finish).

        Solo muestra líneas de tipo 'mrp' con new_date_start definido.

        :raises UserError: si el plan no tiene líneas calculadas.
        :returns: acción de ventana con vista gantt de mrp.reschedule.plan.line.
        """
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
        """
        Abre la vista Gantt con las fechas ACTUALES (current_date_start / current_date_finish).

        Usa la vista específica 'mrp_reschedule_plan_line_gantt_current' si existe.

        :raises UserError: si el plan no tiene líneas calculadas.
        :returns: acción de ventana con vista gantt de mrp.reschedule.plan.line.
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Primero calcule los cambios propuestos.'))
        gantt_view = self.env.ref(
            'odoo_mrp_planner.mrp_reschedule_plan_line_gantt_current',
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
