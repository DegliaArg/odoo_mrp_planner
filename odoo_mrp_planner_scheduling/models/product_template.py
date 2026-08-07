"""
Módulo: product_template.py (odoo_mrp_planner_scheduling)
Modelo: extensión de product.template

Expone el flag calculado que muestra u oculta la pestaña "Planificador"
(centros de trabajo compatibles) del artículo según el toggle
enable_scheduling de la configuración.
"""
from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mrp_enable_scheduling = fields.Boolean(
        compute='_compute_mrp_scheduling_flag',
        help='Indicador calculado: True si la configuración activa del planificador '
             'tiene habilitadas las funciones de programación. Se usa en la vista para '
             'mostrar u ocultar la pestaña de centros de trabajo compatibles.',
    )

    @api.depends_context('company')
    def _compute_mrp_scheduling_flag(self):
        """Propaga enable_scheduling de la config a todos los artículos del conjunto.

        Se usa en la vista para ocultar la pestaña de centros de trabajo compatibles
        (una función de programación) cuando la programación está desactivada.
        """
        # sudo(): mrp.reschedule.config puede no ser accesible para usuarios sin permisos de admin del planificador.
        config = self.env['mrp.reschedule.config'].sudo().get_config()
        enable = config.enable_scheduling if config else False
        for rec in self:
            rec.mrp_enable_scheduling = enable
