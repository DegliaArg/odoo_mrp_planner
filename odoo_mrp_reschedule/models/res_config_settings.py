from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mrp_reschedule_priority = fields.Selection(
        selection=[
            ('chronological', 'Orden cronológico (fecha actual)'),
            ('shortest_first', 'Más cortas primero (SPT)'),
            ('manual', 'Secuencia manual en el wizard'),
        ],
        string='Criterio de prioridad al reprogramar',
        default='chronological',
        config_parameter='mrp_reschedule.priority',
        help='Define el orden en que las órdenes de fabricación se programan '
             'cuando compiten por el mismo centro de trabajo.\n\n'
             '• Cronológico: respeta el orden actual de las fechas.\n'
             '• Más cortas primero: libera los WC antes (regla SPT).\n'
             '• Manual: el usuario define el orden en el wizard.',
    )
