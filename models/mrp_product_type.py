from odoo import fields, models


class MrpProductType(models.Model):
    _name = 'mrp.product.type'
    _description = 'Tipo de producto'
    _order = 'name'

    # Opción A (mono-empresa, actual): mantener como está.
    # Opción B (multi-empresa): agregar company_id y cambiar el constraint:
    _sql_constraints = [
        ('name_company_unique', 'unique(name, company_id)', 'Ya existe un tipo de producto con ese nombre en esta empresa.'),
    ]

    name = fields.Char(string='Tipo de producto', required=True, translate=True)
    color = fields.Integer(
        string='Color',
        help='Índice de color para destacar el tipo en listas y kanban (0 = sin color).',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        default=lambda self: self.env.company,
        index=True,
    )
