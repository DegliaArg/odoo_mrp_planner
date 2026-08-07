"""
Módulo: mrp_production.py (odoo_mrp_planner_scheduling)
Modelo: extensión de mrp.production

Agrega a la OF las capacidades de reprogramación: contador de planes,
acción para verlos y botón que crea y abre un plan de reprogramación.
La detección (x_reschedule_needed, alertas) vive en el módulo base.

Relacionado con:
- mrp.reschedule.plan: planes de reprogramación creados o vinculados a esta OF.
- mrp.reschedule.plan.line: líneas de planes donde esta OF aparece como afectada.
"""
from odoo import models, fields, _


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # ── Contador de planes ───────────────────────────────────────────────────

    reschedule_plan_count = fields.Integer(
        compute='_compute_reschedule_plan_count',
        string='Planes',
        help='Cantidad de planes de reprogramación en los que participa esta OF, '
             'ya sea como pivot principal o como línea afectada.',
    )

    def _compute_reschedule_plan_count(self):
        """
        Calcula reschedule_plan_count para cada registro.

        Fórmula: unión de IDs de planes donde la OF es pivot + IDs de planes
                 donde la OF aparece como línea afectada.
        Depende de: mrp.reschedule.plan.production_id, mrp.reschedule.plan.line.production_id.
        """
        # PERF: optimización vs versión anterior que hacía N búsquedas por OF
        mo_ids = self.ids
        if not mo_ids:
            for mo in self:
                mo.reschedule_plan_count = 0
            return

        # Plans donde la OF es el pivot
        pivot_map = {}
        pivot_data = self.env['mrp.reschedule.plan'].search_read(
            [('production_id', 'in', mo_ids)],
            ['production_id', 'id'],
        )
        for d in pivot_data:
            mo_id = d['production_id'][0]
            pivot_map.setdefault(mo_id, set()).add(d['id'])

        # Plans donde la OF aparece como línea
        line_data = self.env['mrp.reschedule.plan.line'].search_read(
            [('production_id', 'in', mo_ids)],
            ['production_id', 'plan_id'],
        )
        line_map = {}
        for d in line_data:
            mo_id = d['production_id'][0]
            line_map.setdefault(mo_id, set()).add(d['plan_id'][0])

        for mo in self:
            # Unión de conjuntos para evitar contar el mismo plan dos veces
            all_ids = pivot_map.get(mo.id, set()) | line_map.get(mo.id, set())
            mo.reschedule_plan_count = len(all_ids)

    def action_view_reschedule_plans(self):
        """
        Abre la lista de planes de reprogramación relacionados con esta OF.

        Incluye tanto los planes donde la OF es pivot principal como aquellos
        en los que aparece únicamente como línea afectada.

        :returns: dict — acción de ventana ir.actions.act_window filtrada por los IDs encontrados.
        """
        self.ensure_one()
        pivot_ids = self.env['mrp.reschedule.plan'].search([
            ('production_id', '=', self.id),
        ]).ids
        line_ids = self.env['mrp.reschedule.plan.line'].search([
            ('production_id', '=', self.id),
        ]).mapped('plan_id').ids
        # set() elimina duplicados cuando la OF aparece como pivot y como línea en el mismo plan
        all_ids = list(set(pivot_ids + line_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Planes de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_ids)],
            'target': 'current',
        }

    # ── Acción del botón Reprogramar ─────────────────────────────────────────

    def action_open_reschedule_plan(self):
        """
        Crea un plan de reprogramación y lo abre. Funciona desde:
          - La vista lista (Acción → botón servidor).
          - El botón inteligente en el form (cuando x_reschedule_needed=True).
        """
        production_ids = self.env.context.get('active_ids', self.ids)
        if not production_ids:
            return
        pivot = self.browse(production_ids[0])

        pivot.write({'x_reschedule_needed': False})

        plan = self.env['mrp.reschedule.plan'].create({
            'production_id': pivot.id,
            'new_finish_date': pivot.date_finished or fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Plan de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }
