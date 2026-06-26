from datetime import date, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MrpRescheduleConfig(models.Model):
    _name = 'mrp.reschedule.config'
    _description = 'Configuración del planificador de producción'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name', string='Nombre')
    wc_fallback = fields.Selection([
        ('ldm', 'Usar operaciones de la Lista de Materiales'),
        ('none', 'Sin centro de trabajo'),
    ], string='Fallback de centro de trabajo', default='ldm', required=True)

    priority = fields.Selection([
        ('chronological', 'Orden cronológico (fecha actual)'),
        ('shortest_first', 'Más cortas primero (SPT)'),
        ('manual', 'Secuencia manual en el wizard'),
    ], string='Criterio de prioridad al reprogramar', default='chronological', required=True)

    cron_interval_number = fields.Integer(string='Cada', default=30)
    cron_interval_type = fields.Selection([
        ('minutes', 'Minutos'),
        ('hours', 'Horas'),
    ], string='Unidad', default='minutes')

    alert_mo_critical_days      = fields.Integer(string='Días críticos OF',             default=3)
    alert_po_critical_days      = fields.Integer(string='Días críticos OC',             default=5)
    alert_receipt_critical_days = fields.Integer(string='Días críticos recepción',      default=3)
    alert_mo_warning_days       = fields.Integer(string='Días por vencer OF',           default=7)
    alert_po_warning_days       = fields.Integer(string='Días por vencer OC',           default=10)
    qty_tolerance_pct           = fields.Float(  string='Tolerancia cantidad (%)',      default=5.0)

    # ── Forecast ─────────────────────────────────────────────────────────────

    forecast_default_months = fields.Integer(
        string='Meses por defecto en forecast', default=3)
    forecast_warning_pct = fields.Integer(
        string='Cobertura mínima (aviso %)', default=70,
        help='Por debajo de este % la celda se muestra en amarillo.')
    forecast_critical_pct = fields.Integer(
        string='Cobertura mínima (crítico %)', default=50,
        help='Por debajo de este % la celda se muestra en rojo.')

    # Estados de OF a incluir en la comparativa forecast
    forecast_mo_state_draft     = fields.Boolean(string='Borrador',          default=False)
    forecast_mo_state_confirmed = fields.Boolean(string='Confirmada',        default=True)
    forecast_mo_state_progress  = fields.Boolean(string='En progreso',       default=True)
    forecast_mo_state_to_close  = fields.Boolean(string='Por cerrar',        default=True)
    forecast_mo_state_done      = fields.Boolean(string='Terminada',         default=False)

    forecast_rotation_unit = fields.Selection([
        ('days',   'Días'),
        ('months', 'Meses'),
    ], string='Unidad de rotación de inventario', default='days',
       help='Determina si la rotación de inventario en el widget de forecast se muestra en días o en meses.'
    )

    # ── Categoría de venta ────────────────────────────────────────────────────
    sale_cat_mode = fields.Selection([
        ('manual',    'Manual (desde la ficha del artículo)'),
        ('automatic', 'Automática por rotación de inventario'),
    ], string='Modo de asignación', default='manual',
       help='Manual: cada artículo se categoriza desde su ficha. '
            'Automático: el sistema calcula la rotación de los últimos 3 meses '
            'y asigna A–E según los umbrales definidos abajo.')

    sale_cat_a_days = fields.Integer(
        string='A — rotación máx. (días)', default=30,
        help='Artículos con rotación ≤ este valor reciben categoría A (alta rotación).')
    sale_cat_b_days = fields.Integer(
        string='B — rotación máx. (días)', default=60,
        help='Artículos con rotación entre A y este valor reciben categoría B.')
    sale_cat_c_days = fields.Integer(
        string='C — rotación máx. (días)', default=90,
        help='Artículos con rotación entre B y este valor reciben categoría C.')
    sale_cat_d_days = fields.Integer(
        string='D — rotación máx. (días)', default=180,
        help='Artículos con rotación entre C y este valor reciben D. Por encima → E.')

    include_wc_heuristic = fields.Boolean(
        string='Heurística por centro de trabajo',
        default=False,
        help='Cuando está activo, la reprogramación en cascada incluye como dependientes '
             'las OFs que comparten centros de trabajo con el pivot y comienzan después. '
             'Puede generar reprogramaciones masivas en instalaciones con alta carga de CTs.',
    )

    show_po_services_tab = fields.Boolean(
        string='Mostrar pestaña de servicios en OCs',
        default=False,
    )

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock (quiebres)',
        domain=[('usage', '=', 'internal')],
        compute='_compute_stock_location_id',
        inverse='_set_stock_location_id',
        store=False,
        help='Ubicación interna desde la cual se lee el stock actual en el widget de quiebres de stock.',
    )

    @api.depends()
    def _compute_stock_location_id(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.stock_location_id')
        # FIX [FASE-3]: int() puede lanzar ValueError si el parámetro fue editado manualmente
        try:
            loc_id = int(param) if param else False
        except (ValueError, TypeError):
            loc_id = False
        location = self.env['stock.location'].browse(loc_id) if loc_id else \
            self.env['stock.location']
        for rec in self:
            rec.stock_location_id = location if loc_id and location.exists() else False

    def _set_stock_location_id(self):
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                'mrp_reschedule.stock_location_id',
                str(rec.stock_location_id.id) if rec.stock_location_id else '',
            )

    @api.depends()
    def _compute_name(self):
        for rec in self:
            rec.name = 'Configuración del planificador'

    def action_auto_assign_sale_categories(self):
        config = self.search([], limit=1)
        if not config:
            return
        a_d = config.sale_cat_a_days
        b_d = config.sale_cat_b_days
        c_d = config.sale_cat_c_days
        d_d = config.sale_cat_d_days

        end   = date.today()
        start = end - timedelta(days=90)

        moves = self.env['stock.move.line'].search([
            ('state', '=', 'done'),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('date', '>=', fields.Datetime.to_datetime(str(start))),
            ('date', '<=', fields.Datetime.to_datetime(str(end))),
            ('product_id', '!=', False),
        ])
        del_by_tmpl = {}
        for ml in moves:
            tid = ml.product_id.product_tmpl_id.id
            del_by_tmpl[tid] = del_by_tmpl.get(tid, 0.0) + ml.qty_done

        quants = self.env['stock.quant'].read_group(
            [('location_id.usage', '=', 'internal'), ('product_id', '!=', False)],
            ['product_id', 'quantity:sum'],
            ['product_id'],
        )
        stock_by_pid = {g['product_id'][0]: g['quantity'] for g in quants}

        templates = self.env['product.template'].search([('sale_ok', '=', True)])
        updated = 0
        for tmpl in templates:
            stock     = sum(stock_by_pid.get(v.id, 0.0) for v in tmpl.product_variant_ids)
            delivered = del_by_tmpl.get(tmpl.id, 0.0)
            avg_monthly = delivered / 3.0
            if avg_monthly <= 0:
                cat = 'E'
            else:
                rot = round(stock / avg_monthly * 30)
                if   rot <= a_d: cat = 'A'
                elif rot <= b_d: cat = 'B'
                elif rot <= c_d: cat = 'C'
                elif rot <= d_d: cat = 'D'
                else:            cat = 'E'
            tmpl.x_sale_category = cat
            updated += 1

        return {
            'type':   'ir.actions.client',
            'tag':    'display_notification',
            'params': {
                'title':   'Categorías asignadas',
                'message': f'{updated} artículos actualizados.',
                'type':    'success',
            },
        }

    def write(self, vals):
        res = super().write(vals)
        sp = self.env['ir.config_parameter'].sudo()
        if 'wc_fallback' in vals:
            sp.set_param('mrp_reschedule.wc_fallback', vals['wc_fallback'])
        if 'priority' in vals:
            sp.set_param('mrp_reschedule.priority', vals['priority'])
        if 'cron_interval_number' in vals or 'cron_interval_type' in vals:
            cron = self.env.ref('odoo_mrp_planner.ir_cron_check_delays', raise_if_not_found=False)
            if cron:
                cron_vals = {}
                if 'cron_interval_number' in vals:
                    cron_vals['interval_number'] = vals['cron_interval_number']
                if 'cron_interval_type' in vals:
                    cron_vals['interval_type'] = vals['cron_interval_type']
                cron.sudo().write(cron_vals)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # FIX [FASE-2]: prevenir múltiples singletons — solo puede existir un registro
        if self.search_count([]) > 0:
            raise UserError(_(
                'Solo puede existir una configuración del planificador. '
                'Editá el registro existente en lugar de crear uno nuevo.'
            ))
        records = super().create(vals_list)
        sp = self.env['ir.config_parameter'].sudo()
        for rec in records:
            sp.set_param('mrp_reschedule.wc_fallback', rec.wc_fallback)
            sp.set_param('mrp_reschedule.priority', rec.priority)
            cron = self.env.ref('odoo_mrp_planner.ir_cron_check_delays', raise_if_not_found=False)
            if cron:
                cron.sudo().write({
                    'interval_number': rec.cron_interval_number,
                    'interval_type':   rec.cron_interval_type,
                })
        return records

    @api.model
    def action_open(self):
        config = self.search([], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Configuración del planificador',
            'res_model': self._name,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_reschedule_config_form_view').id,
            'res_id': config.id if config else False,
            'target': 'current',
            'flags': {'no_pager': True},
        }
