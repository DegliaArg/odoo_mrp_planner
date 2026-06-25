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

    user_permission_ids = fields.One2many(
        'mrp.reschedule.user.permission',
        'config_id',
        string='Permisos por usuario',
    )

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
