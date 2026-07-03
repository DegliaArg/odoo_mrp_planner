"""
Módulo: mrp_product_type.py
Modelo: mrp.product.type

Catálogo de tipos de producto para el planificador MRP.

Responsabilidades:
- Definir categorías personalizadas de producto usadas en el módulo MRP Planner.
- Permitir agrupar y filtrar productos por tipo en vistas kanban y listas.
- Soportar multi-empresa mediante el campo company_id en el constraint de unicidad.

Relacionado con:
- mrp.production: los órdenes de producción pueden referenciar el tipo de producto
  para filtrar y priorizar la planificación.
- product.template / product.product: los productos pueden clasificarse con este tipo
  para segmentar análisis y dashboards.
"""

from odoo import fields, models


class MrpProductType(models.Model):
    """
    Catálogo de tipos de producto del planificador MRP.

    Cada registro representa una categoría personalizada (p. ej. "Materia Prima",
    "Semielaborado", "Producto Terminado") que puede asignarse a productos para
    segmentar vistas, filtros y análisis dentro del módulo MRP Planner.

    El par (name, company_id) debe ser único para evitar duplicados por empresa
    en entornos multi-empresa.
    """

    _name = 'mrp.product.type'
    _description = 'Tipo de producto'
    _order = 'name'

    # Opción A (mono-empresa, actual): mantener como está.
    # Opción B (multi-empresa): agregar company_id y cambiar el constraint:
    # El constraint incluye company_id para que cada empresa pueda tener sus propios tipos
    # sin colisionar con los de otras empresas en una instalación multi-empresa.
    _sql_constraints = [
        ('name_company_unique', 'unique(name, company_id)', 'Ya existe un tipo de producto con ese nombre en esta empresa.'),
    ]

    name = fields.Char(
        string='Tipo de producto',
        required=True,
        translate=True,
        help='Nombre del tipo de producto (p. ej. Materia Prima, Semielaborado, Producto Terminado).',
    )
    color = fields.Integer(
        string='Color',
        help='Índice de color para destacar el tipo en listas y kanban (0 = sin color).',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        default=lambda self: self.env.company,
        index=True,
        help='Empresa a la que pertenece este tipo de producto. Permite tener catálogos independientes por empresa.',
    )
