"""
Módulo: mrp_reschedule_alert.py (odoo_mrp_planner_scheduling)
Modelo: extensión de mrp.reschedule.alert

Agrega a la alerta del planificador la integración con los planes de
reprogramación: el vínculo al plan generado, el flag de programación
habilitada (para la visibilidad del botón) y la acción de crear/abrir
el plan desde la alerta. La detección de alertas vive en el módulo base.

Relacionado con:
- mrp.reschedule.plan: plan generado a partir de la alerta.
- mrp.reschedule.config: enable_scheduling (campo agregado por este módulo).
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)


class MrpRescheduleAlert(models.Model):
    _inherit = 'mrp.reschedule.alert'

    plan_id      = fields.Many2one('mrp.reschedule.plan', string='Plan generado', readonly=True,
                                   help='Plan de reprogramación creado a partir de esta alerta.')

    scheduling_enabled = fields.Boolean(
        string='Programación habilitada', compute='_compute_scheduling_enabled',
        help='Refleja el flag enable_scheduling de la configuración de la empresa de la alerta. '
             'Se usa para ocultar el botón de reprogramación cuando la función está desactivada.')

    @api.depends('company_id')
    def _compute_scheduling_enabled(self):
        """Lee enable_scheduling de la config de cada empresa (con caché por empresa).

        Si la empresa no tiene registro de configuración, se asume deshabilitado
        (coincide con el default=False del campo enable_scheduling).
        """
        Config = self.env['mrp.reschedule.config']
        cache = {}
        for rec in self:
            cid = rec.company_id.id
            if cid not in cache:
                cfg = Config.search([('company_id', '=', cid)], limit=1)
                cache[cid] = bool(cfg.enable_scheduling) if cfg else False
            rec.scheduling_enabled = cache[cid]

    def _ensure_scheduling_enabled(self):
        """Valida que la reprogramación esté habilitada y que el usuario tenga permiso.

        Red de seguridad para la acción de reprogramar desde la alerta: aunque el
        botón se oculta cuando enable_scheduling está en falso, este método impide
        crear el plan por RPC directo o si la función fue desactivada.

        :raises UserError: si las funciones de programación están desactivadas para la empresa.
        :raises AccessError: si el usuario no pertenece al grupo de Programación ni es admin.
        """
        if not self.scheduling_enabled:
            raise UserError(_(
                'Las funciones de programación y reprogramación están desactivadas '
                'en la configuración. Actívalas en Ajustes para crear planes de reprogramación.'
            ))
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner_scheduling.group_scheduling')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system')):
            raise AccessError(_('Solo los usuarios del grupo Programación pueden crear planes de reprogramación.'))

    def action_create_reschedule_plan(self):
        """
        Crea o abre el plan de reprogramación vinculado a esta alerta.

        Si ya existe un plan activo (no aplicado ni cancelado), lo abre directamente.
        De lo contrario crea un nuevo mrp.reschedule.plan, intentando asociarlo a la
        OF correspondiente. Cuando la alerta proviene de una OC (purchase_id), busca
        la OF relacionada mediante los campos purchase_order_id, purchase_line_id.order_id
        u origin (en ese orden de prioridad).

        :returns: Acción de ventana al formulario del plan de reprogramación.
        :raises UserError: si las funciones de programación están desactivadas.
        :raises AccessError: si el usuario no pertenece al grupo de Programación.
        """
        self.ensure_one()
        self._ensure_scheduling_enabled()
        if self.plan_id and self.plan_id.state not in ('applied', 'cancelled'):
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.reschedule.plan',
                'res_id': self.plan_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        mo = self.production_id
        if not mo and self.purchase_id:
            MO = self.env['mrp.production']
            mo_fields = MO._fields
            try:
                domain = [('state', 'in', ('confirmed', 'progress'))]
                or_clauses = []
                if 'purchase_order_id' in mo_fields:
                    or_clauses.append(('purchase_order_id', '=', self.purchase_id.id))
                if 'purchase_line_id' in mo_fields:
                    or_clauses.append(('purchase_line_id.order_id', '=', self.purchase_id.id))
                if or_clauses:
                    if len(or_clauses) == 2:
                        domain = domain + ['|'] + or_clauses
                    else:
                        domain = domain + or_clauses
                    mo = MO.search(domain, limit=1)
                if not mo:
                    mo = MO.search([
                        ('state', 'in', ('confirmed', 'progress')),
                        ('origin', 'ilike', self.purchase_id.name),
                    ], limit=1)
            except Exception as e:
                _logger.warning('MRP Reschedule: no se pudo buscar OF para alerta %s: %s', self.id, e)

        plan_vals = {'replan_from': fields.Datetime.now()}
        if mo:
            plan_vals['production_id'] = mo.id
            if mo.date_finished:
                plan_vals['new_finish_date'] = mo.date_finished

        plan = self.env['mrp.reschedule.plan'].create(plan_vals)
        self.plan_id = plan.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.reschedule.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }
