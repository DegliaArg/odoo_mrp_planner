from odoo import models, fields


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    alternative_workcenter_ids = fields.One2many(
        comodel_name='mrp.routing.workcenter.alt',
        inverse_name='routing_workcenter_id',
        string='Centros alternativos',
        help=(
            "Centros de trabajo alternativos para esta operación, cada uno con su "
            "propio tiempo de ciclo. El planificador evalúa automáticamente cuál de "
            "ellos (incluyendo el primario) queda libre antes y lo asigna."
        ),
    )
