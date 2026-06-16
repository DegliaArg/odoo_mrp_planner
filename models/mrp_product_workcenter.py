from odoo import models, fields


class MrpProductWorkcenter(models.Model):
    _name = 'mrp.product.workcenter'
    _description = 'Centro de trabajo compatible con producto'
    _order = 'is_preferred desc, sequence, id'
    _rec_name = 'workcenter_id'

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade', index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Centro de trabajo', required=True,
    )
    is_preferred  = fields.Boolean(string='Preferido', default=False)
    active        = fields.Boolean(string='Activo', default=True)
    exclusion_reason = fields.Char(string='Motivo de exclusión')
    sequence      = fields.Integer(default=10)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_centros_compatibles = fields.One2many(
        'mrp.product.workcenter', 'product_tmpl_id',
        string='Centros de trabajo compatibles',
    )
