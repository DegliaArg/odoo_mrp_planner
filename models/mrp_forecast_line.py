from odoo import models, fields, api

_MONTHS_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
               'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


class MrpForecastLine(models.Model):
    _name = 'mrp.forecast.line'
    _description = 'Línea de forecast de producción'
    _rec_name = 'product_id'
    _order = 'period desc, product_id'

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
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Depósito',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
    )
    uom_id = fields.Many2one(
        related='product_id.uom_id',
        string='Unidad',
        readonly=True,
    )

    @api.depends('period')
    def _compute_period_display(self):
        for rec in self:
            if rec.period:
                rec.period_display = f"{_MONTHS_ES[rec.period.month - 1]} {rec.period.year}"
            else:
                rec.period_display = ''

    @api.model
    def _period_from_str(self, period_str):
        """Convierte 'YYYY-MM' a un objeto date (primer día del mes)."""
        from datetime import date
        parts = period_str.split('-')
        if len(parts) != 2:
            return None
        try:
            return date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, TypeError):
            return None
