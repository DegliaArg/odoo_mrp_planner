from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mrp_reschedule_wc_fallback = fields.Selection(
        selection=[
            ('ldm', 'Usar operaciones de la Lista de Materiales'),
            ('none', 'Sin centro de trabajo'),
        ],
        string='Fallback de centro de trabajo',
        default='ldm',
        config_parameter='mrp_reschedule.wc_fallback',
        help='Comportamiento del planificador cuando un producto no tiene centros de '
             'trabajo configurados en "Centros de trabajo compatibles".\n\n'
             '• Usar LdM: usa los centros de trabajo definidos en las operaciones de la LdM.\n'
             '• Sin centro de trabajo: planifica sin asignar máquina.',
    )

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
