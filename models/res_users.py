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
from odoo import models, fields


class ResUsers(models.Model):
    """Extensión de res.users con preferencias de visibilidad del Planificador MRP."""

    _inherit = 'res.users'

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
