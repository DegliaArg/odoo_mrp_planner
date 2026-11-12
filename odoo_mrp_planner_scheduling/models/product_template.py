"""
Módulo: product_template.py (odoo_mrp_planner_scheduling)
Modelo: extensión de product.template

Los campos de planificación del artículo (vulcanizado, mínimo por turno, centros
de trabajo compatibles) se definen en mrp_product_workcenter.py. La pestaña
"Planificación" del formulario se muestra según el grupo "Programación" (ver la
vista product_template_views.xml), sin interruptor maestro.
"""
from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'
