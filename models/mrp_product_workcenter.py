from odoo import models, fields, api
from odoo.exceptions import ValidationError


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

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_preferred'):
            siblings = self.env['mrp.product.workcenter'].search([
                ('product_tmpl_id', 'in', self.mapped('product_tmpl_id').ids),
                ('id', 'not in', self.ids),
                ('is_preferred', '=', True),
            ])
            if siblings:
                siblings.write({'is_preferred': False})
        return res

    @api.constrains('is_preferred')
    def _check_single_preferred(self):
        for rec in self.filtered('is_preferred'):
            count = self.env['mrp.product.workcenter'].search_count([
                ('product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('is_preferred', '=', True),
                ('id', '!=', rec.id),
            ])
            if count:
                raise ValidationError(
                    'Solo puede haber un centro de trabajo preferido por producto. '
                    'Desmarcá el anterior antes de elegir uno nuevo.'
                )


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_centros_compatibles = fields.One2many(
        'mrp.product.workcenter', 'product_tmpl_id',
        string='Centros de trabajo compatibles',
    )
