from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    mrp_planner_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'res_users_mrp_planner_wh_rel',
        'user_id',
        'warehouse_id',
        string='Depósitos visibles (Planificador)',
        help='Depósitos que el usuario puede ver en el Planificador MRP. '
             'Dejar vacío para mostrar todos.',
    )
