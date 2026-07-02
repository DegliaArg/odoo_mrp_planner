from odoo import fields, models


class MrpProductType(models.Model):
    _name = 'mrp.product.type'
    _description = 'Tipo de producto'
    _order = 'name'

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Ya existe un tipo de producto con ese nombre.'),
    ]

    name = fields.Char(string='Tipo de producto', required=True, translate=True)
    color = fields.Integer(string='Color')
