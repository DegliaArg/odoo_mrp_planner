# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import models, fields


class MrpPlannerShift(models.Model):
    _name = 'mrp.planner.shift'
    _description = 'Turno de producción'
    _order = 'hour_from'

    name = fields.Char(string='Turno', required=True)
    hour_from = fields.Float(string='Hora inicio', required=True, default=6.0)
    hour_to = fields.Float(string='Hora fin', required=True, default=14.0)
    config_id = fields.Many2one(
        'mrp.reschedule.config', string='Configuración',
        required=True, ondelete='cascade')
    company_id = fields.Many2one(related='config_id.company_id', store=True)
