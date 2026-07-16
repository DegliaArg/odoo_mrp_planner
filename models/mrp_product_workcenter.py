"""
Módulo: mrp_product_workcenter.py
Modelo: mrp.product.workcenter (y extensión de product.template)

Define la tabla de centros de trabajo compatibles por producto y las reglas
de unicidad del centro preferido.

Responsabilidades:
- Registrar qué centros de trabajo pueden fabricar cada producto.
- Garantizar que solo haya un centro marcado como "preferido" por producto.
- Proveer el campo x_centros_compatibles en product.template para acceder
  a la lista desde la ficha del producto.

Relacionado con:
- mrp.workcenter: cada registro apunta a un centro de trabajo de Odoo MRP.
- product.template: One2many inverso para listar los centros compatibles del producto.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpProductWorkcenter(models.Model):
    _name = 'mrp.product.workcenter'
    _description = 'Centro de trabajo compatible con producto'
    _order = 'is_preferred desc, sequence, id'
    _rec_name = 'workcenter_id'

    product_tmpl_id = fields.Many2one(
        'product.template', required=True, ondelete='cascade', index=True,
        help='Plantilla de producto a la que pertenece este vínculo de centro de trabajo.',
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Centro de trabajo', required=True,
        help='Centro de trabajo de Odoo MRP capaz de fabricar el producto.',
    )
    is_preferred  = fields.Boolean(
        string='Preferido', default=False,
        help='Indica el centro de trabajo que se usará por defecto al planificar '
             'órdenes de producción para este producto. Solo puede haber uno por producto.',
    )
    active        = fields.Boolean(
        string='Activo', default=True,
        help='Si está desactivado, este centro no aparece en las planificaciones '
             'aunque siga siendo compatible técnicamente.',
    )
    exclusion_reason = fields.Char(
        string='Motivo de exclusión',
        help='Descripción opcional del motivo por el que este centro fue marcado '
             'como inactivo o excluido de la planificación.',
    )
    sequence      = fields.Integer(
        default=10,
        help='Orden de prioridad dentro de la lista de centros compatibles. '
             'Valores menores aparecen primero.',
    )
    company_id = fields.Many2one(
        related='workcenter_id.company_id', store=True, index=True, string='Empresa',
    )

    def write(self, vals):
        """
        Sobrescribe write para garantizar unicidad del centro preferido antes
        de que el constraint de base de datos dispare un error.

        Cuando se activa is_preferred en uno o varios registros, primero
        desactiva el flag en todos los registros hermanos del mismo producto
        y misma empresa para que _check_single_preferred no encuentre conflicto
        al validar.

        :param vals: dict con los valores a escribir
        :returns: resultado de super().write(vals)
        """
        if vals.get('is_preferred'):
            # Deseleccionar hermanos ANTES de guardar self, para que
            # el constrains no encuentre conflicto
            siblings = self.env['mrp.product.workcenter'].search([
                ('product_tmpl_id', 'in', self.mapped('product_tmpl_id').ids),
                ('id', 'not in', self.ids),
                ('is_preferred', '=', True),
                ('company_id', 'in', self.mapped('company_id').ids),
            ])
            if siblings:
                siblings.write({'is_preferred': False})
        return super().write(vals)

    @api.constrains('is_preferred')
    def _check_single_preferred(self):
        """Valida que no exista más de un centro preferido por producto y empresa."""
        for rec in self.filtered('is_preferred'):
            count = self.env['mrp.product.workcenter'].search_count([
                ('product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('company_id', '=', rec.company_id.id),
                ('is_preferred', '=', True),
                ('id', '!=', rec.id),
            ])
            if count:
                raise ValidationError(
                    'Solo puede haber un centro de trabajo preferido por producto.'
                )


class ProductTemplate(models.Model):
    """Extiende product.template añadiendo la lista de centros de trabajo compatibles."""

    _inherit = 'product.template'

    x_centros_compatibles = fields.One2many(
        'mrp.product.workcenter', 'product_tmpl_id',
        string='Centros de trabajo compatibles',
        help='Lista de centros de trabajo habilitados para fabricar este producto. '
             'El centro marcado como "Preferido" se usa por defecto al planificar.',
    )
