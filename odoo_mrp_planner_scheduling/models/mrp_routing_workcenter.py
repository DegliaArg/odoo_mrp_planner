from odoo import models, fields


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    alternative_workcenter_ids = fields.Many2many(
        comodel_name='mrp.workcenter',
        relation='mrp_routing_wc_scheduling_alt_rel',
        column1='routing_wc_id',
        column2='workcenter_id',
        string='Centros alternativos',
        domain="[('active', '=', True)]",
        help=(
            "Centros de trabajo alternativos para esta operación. "
            "El planificador evalúa automáticamente cuál de ellos "
            "(incluyendo el primario) queda libre antes y lo asigna."
        ),
    )
