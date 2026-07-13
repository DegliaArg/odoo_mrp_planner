"""
Módulo: res_users.py
Modelo: extensión de res.users

Extiende el modelo de usuarios de Odoo para incorporar preferencias de acceso
al Planificador MRP por depósito.

Responsabilidades:
- Controlar si el usuario visualiza todos los depósitos o solo un subconjunto
- Almacenar la lista de depósitos permitidos cuando el acceso es restringido

Relacionado con:
- stock.warehouse: depósitos que el usuario tiene permitido consultar en el
  Planificador MRP
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    """Extensión de res.users con preferencias de visibilidad del Planificador MRP."""

    _inherit = 'res.users'

    mrp_scheduling_enabled = fields.Boolean(
        compute='_compute_mrp_scheduling_enabled',
        string='Programación MRP habilitada',
    )

    def _compute_mrp_scheduling_enabled(self):
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        enabled = bool(cfg.enable_scheduling) if cfg else False
        for user in self:
            user.mrp_scheduling_enabled = enabled

    @api.constrains('groups_id')
    def _check_scheduling_group_assignment(self):
        scheduling_group = self.env.ref('odoo_mrp_planner.group_scheduling', raise_if_not_found=False)
        if not scheduling_group:
            return
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        if not cfg or cfg.enable_scheduling:
            return
        for user in self:
            if scheduling_group in user.groups_id:
                raise ValidationError(
                    'No se puede asignar el permiso "Programación" porque la '
                    'programación está deshabilitada. Habilítela primero desde '
                    'Configuración → Planificador MRP → Programación y reprogramación.'
                )

    mrp_planner_all_warehouses = fields.Boolean(
        string='Todos los depósitos',
        default=True,
        help='Si está activo, el usuario puede ver datos de todos los depósitos en el Planificador MRP. '
             'Si está inactivo, solo verá los depósitos seleccionados abajo.',
    )

    mrp_planner_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'res_users_mrp_planner_wh_rel',
        'user_id',
        'warehouse_id',
        string='Depósitos permitidos',
        help='Depósitos que el usuario puede ver en el Planificador MRP '
             'cuando "Todos los depósitos" está desactivado.',
    )
