"""
Módulo: mrp_forecast_line.py
Modelo: mrp.forecast.line

Líneas de forecast mensual de producción por artículo y empresa.

Responsabilidades:
- Almacenar la cantidad planificada de producción para un artículo en un período mensual.
- Garantizar unicidad de la combinación artículo + período + empresa mediante constraint SQL.
- Exponer una representación legible del período en español (ej. "Jul 2025").
- Proveer un helper de conversión de cadena 'YYYY-MM' a objeto date.

Relacionado con:
- product.product: cada línea referencia un artículo vendible.
- res.company: las líneas están aisladas por empresa (multi-empresa).
- mrp.production / órdenes de venta: el forecast es insumo para el cálculo
  de brechas y recomendaciones de producción en el planificador MRP.
"""

from datetime import date

from odoo import models, fields, api

# Nombres abreviados de mes en español, indexados por (month - 1).
# Se usan en _compute_period_display para construir etiquetas como "Jul 2025".
_MONTHS_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
               'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


class MrpForecastLine(models.Model):
    _name = 'mrp.forecast.line'
    _description = 'Línea de forecast de producción'
    _rec_name = 'product_id'
    _order = 'period desc, product_id'

    _sql_constraints = [
        (
            'product_period_company_unique',
            'unique(product_id, period, company_id)',
            'Ya existe una línea de forecast para este artículo y período en esta empresa.',
        ),
    ]

    product_id = fields.Many2one(
        'product.product',
        string='Artículo',
        required=True,
        domain=[('sale_ok', '=', True)],
        ondelete='restrict',
    )
    forecast_qty = fields.Float(
        string='Cantidad forecast',
        required=True,
        digits=(16, 2),
        default=0.0,
        help='Cantidad planificada para el período. Debe ser mayor o igual a cero.',
    )
    period = fields.Date(
        string='Período',
        required=True,
        help='Primer día del mes del período (ej. 2025-07-01 = julio 2025).',
    )
    period_display = fields.Char(
        string='Mes',
        compute='_compute_period_display',
        store=False,
        help='Nombre abreviado del período (ej. "Jul 2025"). Solo para visualización.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
        help='Empresa a la que pertenece esta línea de forecast. Permite multi-empresa.',
    )
    uom_id = fields.Many2one(
        related='product_id.uom_id',
        string='Unidad',
        readonly=True,
        store=False,
        help='Unidad de medida del artículo, heredada de product.product. Solo lectura.',
    )

    @api.depends('period')
    def _compute_period_display(self):
        """
        Calcula period_display para cada registro.

        Fórmula: abreviatura del mes en español (de _MONTHS_ES) + año de cuatro dígitos.
                 Ejemplo: period = 2025-07-01  →  period_display = "Jul 2025".
        Depende de: period.
        """
        for rec in self:
            if rec.period:
                rec.period_display = f"{_MONTHS_ES[rec.period.month - 1]} {rec.period.year}"
            else:
                rec.period_display = ''
