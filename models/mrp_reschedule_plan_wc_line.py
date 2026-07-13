"""
Módulo: mrp_reschedule_plan_wc_line.py
Modelo: mrp.reschedule.plan.wc.line

Registro de carga detallada por operación (WO) dentro de un plan de reprogramación.

Cada línea representa el bloque de tiempo que una operación (mrp.workorder) ocupará
en su centro de trabajo con las nuevas fechas propuestas. Se usa principalmente para
la vista Gantt de carga de centros de trabajo y para detectar solapamientos.
"""

from odoo import models, fields, api

from .mrp_reschedule_cascade_mixin import _get_old_code


class MrpReschedulePlanWcLine(models.Model):
    """
    Registro de carga detallada por operación (WO) dentro de un plan de reprogramación.

    Cada línea representa el bloque de tiempo que una operación (mrp.workorder) ocupará
    en su centro de trabajo con las nuevas fechas propuestas. Se usa principalmente para
    la vista Gantt de carga de centros de trabajo y para detectar solapamientos.
    """

    _name = 'mrp.reschedule.plan.wc.line'
    _description = 'Carga de centro de trabajo — plan de reprogramación'
    _order = 'new_date_start, id'
    _rec_name = 'record_label'

    plan_id       = fields.Many2one('mrp.reschedule.plan', required=True, ondelete='cascade', string='Plan',
                                    help='Plan de reprogramación al que pertenece esta línea de WC.')
    production_id = fields.Many2one('mrp.production', string='Orden de fabricación',
                                    help='MO a la que pertenece la operación.')
    workorder_id  = fields.Many2one('mrp.workorder',  string='Operación',
                                    help='Operación específica dentro de la MO.')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Centro de trabajo',
                                    help='Centro de trabajo que ejecuta la operación.')

    new_date_start  = fields.Datetime(string='Nuevo inicio',
                                      help='Fecha/hora de inicio propuesta para esta operación.')
    new_date_finish = fields.Datetime(string='Nuevo fin',
                                      help='Fecha/hora de fin propuesta para esta operación.')

    record_label = fields.Char(string='OF',        compute='_compute_display', store=True,
                               help='Nombre de la MO, con código viejo si aplica.')
    wo_name      = fields.Char(string='Operación', compute='_compute_display', store=True,
                               help='Nombre de la operación o del producto si no hay WO.')
    color        = fields.Integer(compute='_compute_color', store=True,
                                  help='Color según estado del plan: verde=aplicado, azul=calculado, gris=otro.')

    plan_state = fields.Selection(related='plan_id.state', store=True, string='Estado plan',
                                  help='Estado del plan padre, denormalizado para filtros en vista.')
    plan_name  = fields.Char(related='plan_id.name',  store=True, string='Plan',
                             help='Referencia del plan padre, denormalizada para búsquedas.')

    @api.depends('production_id', 'workorder_id')
    def _compute_display(self):
        """
        Calcula record_label y wo_name para cada línea WC.

        Fórmula: record_label = nombre de la MO con prefijo de código viejo si existe.
        wo_name = nombre de la WO o nombre del producto de la MO como fallback.
        Depende de: production_id, workorder_id.
        """
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
        """
        Calcula color para cada línea WC según el estado del plan padre.

        Fórmula: aplicado=10 (verde), calculado=4 (azul), otro=0 (gris).
        Depende de: plan_state.
        """
        for line in self:
            if line.plan_state == 'applied':
                line.color = 10   # verde
            elif line.plan_state == 'calculated':
                line.color = 4    # azul
            else:
                line.color = 0    # gris
