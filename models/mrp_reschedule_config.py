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
        ('demand',    'Automática por demanda (volumen de ventas)'),
        ('share',     'Automática por participación acumulada (Pareto)'),
    ], string='Modo de asignación', default='manual',
       help='Manual: cada artículo se categoriza desde su ficha. '
            'Rotación: calcula stock ÷ ventas y asigna A–E por días de cobertura. '
            'Demanda: asigna A–E por unidades vendidas promedio por mes. '
            'Participación: ordena por métrica y clasifica por % acumulado del total.')

    sale_cat_lookback_months = fields.Integer(
        string='Período de análisis (meses)', default=3,
        help='Cantidad de meses hacia atrás que se analizan las entregas para calcular '
             'la demanda, rotación o participación. Por defecto 3 meses.')

    # ── Umbrales por rotación (modo automatic) ────────────────────────────────
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

    # ── Umbrales por demanda (modo demand) ────────────────────────────────────
    sale_cat_demand_a_qty = fields.Integer(
        string='A — demanda mín. (u./mes)', default=100,
        help='Artículos con promedio mensual ≥ este valor reciben categoría A.')
    sale_cat_demand_b_qty = fields.Integer(
        string='B — demanda mín. (u./mes)', default=50,
        help='Artículos con promedio mensual ≥ este valor (y < A) reciben categoría B.')
    sale_cat_demand_c_qty = fields.Integer(
        string='C — demanda mín. (u./mes)', default=20,
        help='Artículos con promedio mensual ≥ este valor (y < B) reciben categoría C.')
    sale_cat_demand_d_qty = fields.Integer(
        string='D — demanda mín. (u./mes)', default=5,
        help='Artículos con promedio mensual ≥ este valor (y < C) reciben D. Por debajo → E.')

    # ── Umbrales por participación acumulada (modo share) ─────────────────────
    sale_cat_share_metric = fields.Selection([
        ('units',  'Unidades entregadas'),
        ('pxq',    'Importe (precio de lista × cantidad)'),
    ], string='Métrica de participación', default='units',
       help='Valor por el que se ordena y pondera cada artículo al calcular la participación.')
    sale_cat_share_a_pct = fields.Float(
        string='A — hasta % acumulado', default=50.0,
        help='Los artículos que juntos representan hasta este % del total reciben categoría A.')
    sale_cat_share_b_pct = fields.Float(
        string='B — hasta % acumulado', default=80.0,
        help='Los artículos que llevan el acumulado de A hasta este % reciben categoría B.')
    sale_cat_share_c_pct = fields.Float(
        string='C — hasta % acumulado', default=95.0,
        help='Los artículos que llevan el acumulado de B hasta este % reciben categoría C.')
    sale_cat_share_d_pct = fields.Float(
        string='D — hasta % acumulado', default=99.0,
        help='Los artículos que llevan el acumulado de C hasta este % reciben D. El resto → E.')

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

        months = config.sale_cat_lookback_months or 3
        end    = date.today()
        start  = end - timedelta(days=months * 30)

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
            del_by_tmpl[tid] = del_by_tmpl.get(tid, 0.0) + ml.quantity

        templates = self.env['product.template'].search([('sale_ok', '=', True)])
        updated = 0

        if config.sale_cat_mode == 'demand':
            a_q = config.sale_cat_demand_a_qty
            b_q = config.sale_cat_demand_b_qty
            c_q = config.sale_cat_demand_c_qty
            d_q = config.sale_cat_demand_d_qty
            for tmpl in templates:
                avg_monthly = del_by_tmpl.get(tmpl.id, 0.0) / months
                if   avg_monthly >= a_q: cat = 'A'
                elif avg_monthly >= b_q: cat = 'B'
                elif avg_monthly >= c_q: cat = 'C'
                elif avg_monthly >= d_q: cat = 'D'
                else:                    cat = 'E'
                tmpl.x_sale_category = cat
                updated += 1

        elif config.sale_cat_mode == 'share':
            metric = config.sale_cat_share_metric or 'units'
            a_pct  = (config.sale_cat_share_a_pct or 50.0) / 100.0
            b_pct  = (config.sale_cat_share_b_pct or 80.0) / 100.0
            c_pct  = (config.sale_cat_share_c_pct or 95.0) / 100.0
            d_pct  = (config.sale_cat_share_d_pct or 99.0) / 100.0

            tmpl_value = {}
            for tmpl in templates:
                qty = del_by_tmpl.get(tmpl.id, 0.0)
                tmpl_value[tmpl.id] = qty * (tmpl.list_price or 0.0) if metric == 'pxq' else qty

            total = sum(tmpl_value.values())
            if total <= 0:
                for tmpl in templates:
                    tmpl.x_sale_category = 'E'
                    updated += 1
            else:
                sorted_tmpls = sorted(templates, key=lambda t: tmpl_value.get(t.id, 0.0), reverse=True)
                cumulative = 0.0
                for tmpl in sorted_tmpls:
                    cumulative += tmpl_value.get(tmpl.id, 0.0) / total
                    if   cumulative <= a_pct: cat = 'A'
                    elif cumulative <= b_pct: cat = 'B'
                    elif cumulative <= c_pct: cat = 'C'
                    elif cumulative <= d_pct: cat = 'D'
                    else:                     cat = 'E'
                    tmpl.x_sale_category = cat
                    updated += 1

        else:  # automatic (rotation)
            a_d = config.sale_cat_a_days
            b_d = config.sale_cat_b_days
            c_d = config.sale_cat_c_days
            d_d = config.sale_cat_d_days
            quants = self.env['stock.quant'].read_group(
                [('location_id.usage', '=', 'internal'), ('product_id', '!=', False)],
                ['product_id', 'quantity:sum'],
                ['product_id'],
            )
            stock_by_pid = {g['product_id'][0]: g['quantity'] for g in quants}
            for tmpl in templates:
                stock       = sum(stock_by_pid.get(v.id, 0.0) for v in tmpl.product_variant_ids)
                avg_monthly = del_by_tmpl.get(tmpl.id, 0.0) / months
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

    def action_open_user_warehouses(self):
        return {
            'type':      'ir.actions.act_window',
            'name':      'Depósitos por usuario',
            'res_model': 'res.users',
            'view_mode': 'list',
            'view_id':   self.env.ref('odoo_mrp_planner.view_users_mrp_warehouse_list').id,
            'domain':    [('share', '=', False), ('active', '=', True)],
            'target':    'current',
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
