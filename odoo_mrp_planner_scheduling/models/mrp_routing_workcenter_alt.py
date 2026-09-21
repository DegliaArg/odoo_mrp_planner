from odoo import models, fields


class MrpRoutingWorkcenterAlt(models.Model):
    _name = 'mrp.routing.workcenter.alt'
    _description = 'Centro de trabajo alternativo de una operación'
    _rec_name = 'workcenter_id'
    _order = 'sequence, id'

    routing_workcenter_id = fields.Many2one(
        comodel_name='mrp.routing.workcenter',
        string='Operación',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    workcenter_id = fields.Many2one(
        comodel_name='mrp.workcenter',
        string='Centro alternativo',
        required=True,
        domain="[('active', '=', True)]",
    )
    time_cycle_manual = fields.Float(
        string='Tiempo de ciclo (min)',
        digits=(16, 2),
        help=(
            "Tiempo de ciclo de esta operación cuando se ejecuta en el centro "
            "alternativo. Se precarga con el tiempo de la operación al crear la "
            "línea, pero se puede ajustar por centro."
        ),
    )

    _sql_constraints = [
        (
            'workcenter_uniq',
            'unique(routing_workcenter_id, workcenter_id)',
            'Un centro alternativo no puede repetirse en la misma operación.',
        ),
    ]
