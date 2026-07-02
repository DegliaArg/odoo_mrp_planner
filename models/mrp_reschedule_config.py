import logging
from datetime import date, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _abc_thresholds(config=None):
    """Returns (t_a, t_b, t_c, t_d) as fractions from the config fields (or defaults)."""
    if config:
        return (
            (config.abc_pct_a or 20) / 100.0,
            (config.abc_pct_b or 50) / 100.0,
            (config.abc_pct_c or 80) / 100.0,
            (config.abc_pct_d or 95) / 100.0,
        )
    return (0.20, 0.50, 0.80, 0.95)


def _assign_abc_pareto(partners, value_by_id, field_name, thresholds=(0.20, 0.50, 0.80, 0.95)):
    """Assigns A–E via cumulative Pareto. Higher value = A. Partners with no value → E."""
    t_a, t_b, t_c, t_d = thresholds
    total = sum(value_by_id.get(p.id, 0.0) for p in partners)
    if total <= 0:
        for p in partners:
            p[field_name] = 'E'
        return
    sorted_p = sorted(partners, key=lambda p: value_by_id.get(p.id, 0.0), reverse=True)
    cumulative = 0.0
    for p in sorted_p:
        v = value_by_id.get(p.id, 0.0)
        if v <= 0:
            p[field_name] = 'E'
            continue
        cumulative += v / total
        if   cumulative <= t_a: cat = 'A'
        elif cumulative <= t_b: cat = 'B'
        elif cumulative <= t_c: cat = 'C'
        elif cumulative <= t_d: cat = 'D'
        else:                   cat = 'E'
        p[field_name] = cat


def _assign_abc_pareto_lower(partners, value_by_id, field_name, thresholds=(0.20, 0.50, 0.80, 0.95)):
    """Assigns A–E where LOWER value = A (e.g. price variance, return count).
    Partners with no value → E."""
    t_a, t_b, t_c, t_d = thresholds
    with_val = [(p, value_by_id.get(p.id)) for p in partners]
    for p, v in with_val:
        if v is None:
            p[field_name] = 'E'
    has_val = sorted([(p, v) for p, v in with_val if v is not None], key=lambda x: x[1])
    n = len(has_val)
    for i, (p, _) in enumerate(has_val):
        pct = (i + 1) / n if n > 0 else 1.0
        if   pct <= t_a: cat = 'A'
        elif pct <= t_b: cat = 'B'
        elif pct <= t_c: cat = 'C'
        elif pct <= t_d: cat = 'D'
        else:            cat = 'E'
        p[field_name] = cat


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

    cron_interval_number = fields.Integer(string='Cada', default=30,
        help='Frecuencia con que el cron de detección revisa las OFs y OCs '
             'para generar o resolver alertas automáticamente. '
             'Valores bajos = más reactivo, mayor carga en el servidor.')
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

    forecast_acc_formula = fields.Selection([
        ('simple', 'Simple'),
        ('mape',   'MAPE'),
        ('wape',   'WAPE'),
        ('wmape',  'WMAPE'),
        ('bias',   'Sesgo'),
    ], string='Fórmula de precisión forecast', default='simple',
       help='Simple: entregado ÷ forecast × 100, puede superar 100%.\n'
            'MAPE: promedio aritmético de precisiones por período (100 − |error/real|×100); sensible a períodos de bajo volumen.\n'
            'WAPE: 100 − Σ|error|/Σentregado×100; pondera por volumen real, robusto con ceros en forecast.\n'
            'WMAPE: 100 − Σ|error|/Σforecast×100; pondera por volumen planificado, estándar supply chain.\n'
            'Sesgo: (entregado − forecast)/forecast×100; positivo = sobreentrega, negativo = déficit.'
    )

    # ── Categoría de venta ────────────────────────────────────────────────────
    enable_sale_categories = fields.Boolean(
        string='Habilitar categorías de venta', default=False,
        help='Activa el campo Categoría de venta (A–E) en los productos y permite '
             'calcularlo automáticamente según el modo elegido.')

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

    supplier_analysis_date_field = fields.Selection([
        ('date_approve', 'Fecha de aprobación'),
        ('date_order',   'Fecha de pedido'),
        ('date_planned', 'Fecha de entrega planificada'),
    ], string='Fecha para análisis de proveedores', default='date_approve')

    # ── Umbrales análisis de proveedores ──────────────────────────────────────
    sup_on_time_green_pct   = fields.Integer(string='% A tiempo — verde (≥)',       default=90)
    sup_on_time_yellow_pct  = fields.Integer(string='% A tiempo — amarillo (≥)',    default=70)
    sup_delay_green_days    = fields.Integer(string='Retraso — verde (≤ días)',      default=1)
    sup_delay_yellow_days   = fields.Integer(string='Retraso — amarillo (≤ días)',  default=3)
    sup_complete_green_pct  = fields.Integer(string='% Completas — verde (≥)',      default=95)
    sup_complete_yellow_pct = fields.Integer(string='% Completas — amarillo (≥)',   default=80)
    sup_price_var_green_pct  = fields.Float( string='Var. precio — verde (|%| ≤)',  default=3.0)
    sup_price_var_yellow_pct = fields.Float( string='Var. precio — amarillo (|%| ≤)', default=10.0)

    # ── Auto-actualización categoría de venta ─────────────────────────────────
    sale_cat_auto_cron   = fields.Boolean(string='Actualización automática', default=False,
        help='Recalcula las categorías de venta automáticamente según el intervalo configurado. '
             'Si está desactivado, las categorías solo se actualizan con el botón manual.')
    sale_cat_cron_number = fields.Integer(string='Cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de venta.')
    sale_cat_cron_type   = fields.Selection([
        ('days',   'Días'),
        ('weeks',  'Semanas'),
        ('months', 'Meses'),
    ], string='Unidad', default='weeks')

    # ── Categorías de proveedor ───────────────────────────────────────────────
    enable_supplier_categories = fields.Boolean(
        string='Habilitar categorías de proveedor', default=False,
        help='Activa el campo Categoría de proveedor (A–E) en los contactos y permite '
             'calcularlo automáticamente según el método elegido.')
    supplier_cat_method = fields.Selection([
        ('manual',              'Manual'),
        ('abc_volume',          'ABC por volumen (importe OCs)'),
        ('abc_frequency',       'ABC por frecuencia (cantidad de OCs)'),
        ('abc_rfm',             'ABC por RFM'),
        ('abc_delivery_pct',    'ABC por % de entrega a tiempo'),
        ('abc_price_var',       'ABC por variación de precio'),
        ('abc_quality_qty',     'ABC por calidad — diferencia de cantidad'),
        ('abc_quality_returns', 'ABC por calidad — devoluciones'),
        ('abc_quality_combo',   'ABC por calidad — combinado (entrega + cantidad)'),
    ], string='Método proveedor', default='manual',
       help='Manual: la categoría se asigna desde la ficha de cada proveedor.\n'
            'ABC por volumen: Pareto por importe total de OCs del último año '
            '(primero 20% = A, 50% = B, 80% = C, 95% = D, resto = E).\n'
            'ABC por frecuencia: igual que volumen pero por cantidad de OCs.\n'
            'ABC por RFM: scoring Recencia + Frecuencia + Monetario (1-3 pts c/u); '
            'suma 8-9 = A, 6-7 = B, 4-5 = C, 3 = D, < 3 = E.\n'
            'ABC por % de entrega a tiempo: Pareto por % de recepciones completadas '
            'antes o en la fecha planificada. Mayor % = mejor categoría.\n'
            'ABC por variación de precio: Pareto invertido por |variación precio OC vs costo estándar|. '
            'Menor variación = mejor categoría.\n'
            'ABC por calidad — diferencia de cantidad: Pareto por % de movimientos de recepción '
            'donde la cantidad recibida coincide exactamente con la pedida.\n'
            'ABC por calidad — devoluciones: Pareto invertido por cantidad de devoluciones al proveedor. '
            'Menos devoluciones = mejor categoría.\n'
            'ABC por calidad — combinado: promedio de % entrega a tiempo y % sin diferencia de cantidad.')
    supplier_cat_cron_number = fields.Integer(string='Cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de proveedor.')
    supplier_cat_cron_type   = fields.Selection([
        ('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'),
    ], string='Unidad', default='weeks')

    # Umbrales Pareto (aplican a todos los métodos ABC Pareto, no a RFM ni manual)
    abc_pct_a = fields.Integer(string='A ≤', default=20,
        help='Acumulado máximo (%) para categoría A. Proveedores/clientes que suman hasta este % del total = A.')
    abc_pct_b = fields.Integer(string='B ≤', default=50,
        help='Acumulado máximo (%) para categoría B.')
    abc_pct_c = fields.Integer(string='C ≤', default=80,
        help='Acumulado máximo (%) para categoría C.')
    abc_pct_d = fields.Integer(string='D ≤', default=95,
        help='Acumulado máximo (%) para categoría D. El resto queda en E.')

    # ── Categorías de cliente ─────────────────────────────────────────────────
    enable_customer_categories = fields.Boolean(
        string='Habilitar categorías de cliente', default=False,
        help='Activa el campo Categoría de cliente (A–E) en los contactos y permite '
             'calcularlo automáticamente según el método elegido.')
    customer_cat_method = fields.Selection([
        ('manual',        'Manual'),
        ('abc_volume',    'ABC por volumen (importe SOs)'),
        ('abc_frequency', 'ABC por frecuencia (cantidad de SOs)'),
        ('abc_rfm',       'ABC por RFM'),
    ], string='Método cliente', default='manual',
       help='Manual: la categoría se asigna desde la ficha de cada cliente.\n'
            'ABC por volumen: ordena los clientes por importe total de SOs confirmados '
            'en los últimos 12 meses y aplica Pareto acumulado '
            '(primero 20% del total = A, hasta 50% = B, hasta 80% = C, hasta 95% = D, resto = E).\n'
            'ABC por frecuencia: igual que volumen pero pondera por cantidad de SOs en vez del importe. '
            'Favorece clientes con alta frecuencia de pedidos.\n'
            'ABC por RFM: scoring multidimensional — '
            'Recencia (días desde el último SO: < 30d = 3pts, < 90d = 2pts, resto = 1pt), '
            'Frecuencia (SOs en el año: > 10 = 3pts, ≥ 3 = 2pts, resto = 1pt), '
            'Monetario (importe relativo al percentil 33/66 del grupo: alto = 3pts, medio = 2pts, bajo = 1pt). '
            'Suma 8-9 = A, 6-7 = B, 4-5 = C, 3 = D, < 3 = E.')
    customer_cat_cron_number = fields.Integer(string='Cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de cliente.')
    customer_cat_cron_type   = fields.Selection([
        ('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'),
    ], string='Unidad', default='weeks')

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
        """Asigna categorías de venta (ABC/RFM) a todos los productos vendibles.

        Requiere permiso de Administrador: escribe en product.template.x_sale_category.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
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

    @api.model
    def _cron_auto_assign_sale_categories(self):
        _logger.info('MRP Planner cron: inicio actualización categorías de venta')
        config = self.search([], limit=1)
        if not config or not config.sale_cat_auto_cron or config.sale_cat_mode == 'manual':
            _logger.info('MRP Planner cron: categorías de venta omitidas (desactivado o modo manual)')
            return
        config.action_auto_assign_sale_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de venta')

    def action_compute_supplier_categories(self):
        """Asigna categorías de proveedor (ABC) a todos los partners activos.

        Requiere permiso de Administrador: escribe en res.partner.x_supplier_category.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
        config = self.search([], limit=1)
        if not config or config.supplier_cat_method == 'manual':
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Modo manual', 'message': 'Las categorías en modo manual se asignan desde la ficha del proveedor.', 'type': 'warning'}}

        start = date.today() - timedelta(days=365)
        suppliers = self.env['res.partner'].search([('supplier_rank', '>', 0), ('active', '=', True)])
        updated = 0

        if config.supplier_cat_method in ('abc_volume', 'abc_frequency'):
            groups = self.env['purchase.order'].read_group(
                [('state', 'in', ('purchase', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count'],
                ['partner_id'],
            )
            if config.supplier_cat_method == 'abc_volume':
                value_by_id = {g['partner_id'][0]: g['amount_total'] for g in groups}
            else:
                value_by_id = {g['partner_id'][0]: g['partner_id_count'] for g in groups}
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_rfm':
            start_dt = fields.Datetime.to_datetime(str(start))
            now_dt   = fields.Datetime.now()
            groups = self.env['purchase.order'].read_group(
                [('state', 'in', ('purchase', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count', 'date_order:max'],
                ['partner_id'],
            )
            data = {g['partner_id'][0]: {
                'M': g['amount_total'] or 0.0,
                'F': g['partner_id_count'] or 0,
                'R': (now_dt - g['date_order']).days if g.get('date_order') else 999,
            } for g in groups}

            # Score each dimension into 1–3 using simple thresholds
            for p in suppliers:
                d = data.get(p.id)
                if not d:
                    p.x_supplier_category = 'E'
                    updated += 1
                    continue
                r_score = 3 if d['R'] < 30 else (2 if d['R'] < 90 else 1)
                f_score = 3 if d['F'] > 10 else (2 if d['F'] >= 3 else 1)
                # M: score relative to median — compute after
                data[p.id]['r_score'] = r_score
                data[p.id]['f_score'] = f_score

            m_vals = sorted([d['M'] for d in data.values() if d.get('M', 0) > 0])
            m_p33 = m_vals[len(m_vals) // 3] if m_vals else 0
            m_p66 = m_vals[2 * len(m_vals) // 3] if m_vals else 0

            for p in suppliers:
                d = data.get(p.id)
                if not d or p.x_supplier_category == 'E':
                    continue
                m_score = 3 if d['M'] >= m_p66 else (2 if d['M'] >= m_p33 else 1)
                total_score = d['r_score'] + d['f_score'] + m_score
                if   total_score >= 8: cat = 'A'
                elif total_score >= 6: cat = 'B'
                elif total_score >= 4: cat = 'C'
                elif total_score >= 3: cat = 'D'
                else:                  cat = 'E'
                p.x_supplier_category = cat
                updated += 1

        elif config.supplier_cat_method == 'abc_delivery_pct':
            picks = self.env['stock.picking'].search([
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'incoming'),
                ('purchase_id.partner_id', 'in', suppliers.ids),
                ('purchase_id.date_order', '>=', str(start)),
            ])
            pct_data = {}
            for pick in picks:
                pid = pick.purchase_id.partner_id.id
                if pid not in pct_data:
                    pct_data[pid] = {'total': 0, 'on_time': 0}
                pct_data[pid]['total'] += 1
                if pick.scheduled_date and pick.date_done and pick.date_done <= pick.scheduled_date:
                    pct_data[pid]['on_time'] += 1
            value_by_id = {
                pid: (d['on_time'] / d['total'] * 100) if d['total'] > 0 else 0.0
                for pid, d in pct_data.items()
            }
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_price_var':
            po_lines = self.env['purchase.order.line'].search([
                ('order_id.state', 'in', ('purchase', 'done')),
                ('order_id.date_order', '>=', str(start)),
                ('order_id.partner_id', 'in', suppliers.ids),
                ('product_id', '!=', False),
            ])
            prod_ids = list({ln.product_id.id for ln in po_lines})
            std_map = {r['id']: r['standard_price']
                       for r in self.env['product.product'].search_read(
                           [('id', 'in', prod_ids)], ['id', 'standard_price']
                       )} if prod_ids else {}
            pvar_data = {}
            for ln in po_lines:
                pid = ln.order_id.partner_id.id
                std = std_map.get(ln.product_id.id, 0.0)
                if std > 0 and ln.price_unit > 0:
                    var = abs((ln.price_unit - std) / std * 100)
                    if pid not in pvar_data:
                        pvar_data[pid] = {'sum': 0.0, 'count': 0}
                    pvar_data[pid]['sum'] += var
                    pvar_data[pid]['count'] += 1
            avg_var_by_id = {
                pid: d['sum'] / d['count'] if d['count'] > 0 else None
                for pid, d in pvar_data.items()
            }
            _assign_abc_pareto_lower(suppliers, avg_var_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_qty':
            moves = self.env['stock.move'].search([
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('picking_id.purchase_id.partner_id', 'in', suppliers.ids),
                ('picking_id.purchase_id.date_order', '>=', str(start)),
            ])
            qty_data = {}
            for mv in moves:
                pid = mv.picking_id.purchase_id.partner_id.id
                if pid not in qty_data:
                    qty_data[pid] = {'total': 0, 'exact': 0}
                qty_data[pid]['total'] += 1
                if abs(mv.quantity - mv.product_uom_qty) < 0.001:
                    qty_data[pid]['exact'] += 1
            value_by_id = {
                pid: (d['exact'] / d['total'] * 100) if d['total'] > 0 else 0.0
                for pid, d in qty_data.items()
            }
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_returns':
            returns_by_partner = {}
            _has_return_id = 'return_id' in self.env['stock.picking']._fields
            if _has_return_id:
                ret_picks = self.env['stock.picking'].search([
                    ('state', '=', 'done'),
                    ('return_id', '!=', False),
                    ('return_id.purchase_id', '!=', False),
                    ('return_id.purchase_id.partner_id', 'in', suppliers.ids),
                    ('return_id.purchase_id.date_order', '>=', str(start)),
                ])
                for pick in ret_picks:
                    pid = pick.return_id.purchase_id.partner_id.id
                    returns_by_partner[pid] = returns_by_partner.get(pid, 0) + 1
            _assign_abc_pareto_lower(suppliers, returns_by_partner, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_combo':
            picks = self.env['stock.picking'].search([
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'incoming'),
                ('purchase_id.partner_id', 'in', suppliers.ids),
                ('purchase_id.date_order', '>=', str(start)),
            ])
            combo_data = {}
            for pick in picks:
                pid = pick.purchase_id.partner_id.id
                if pid not in combo_data:
                    combo_data[pid] = {'total': 0, 'on_time': 0}
                combo_data[pid]['total'] += 1
                if pick.scheduled_date and pick.date_done and pick.date_done <= pick.scheduled_date:
                    combo_data[pid]['on_time'] += 1
            moves = self.env['stock.move'].search([
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('picking_id.purchase_id.partner_id', 'in', suppliers.ids),
                ('picking_id.purchase_id.date_order', '>=', str(start)),
            ])
            qty_data = {}
            for mv in moves:
                pid = mv.picking_id.purchase_id.partner_id.id
                if pid not in qty_data:
                    qty_data[pid] = {'total': 0, 'exact': 0}
                qty_data[pid]['total'] += 1
                if abs(mv.quantity - mv.product_uom_qty) < 0.001:
                    qty_data[pid]['exact'] += 1
            value_by_id = {}
            for p in suppliers:
                on_t = combo_data.get(p.id, {})
                qt   = qty_data.get(p.id, {})
                on_time_pct = (on_t.get('on_time', 0) / on_t['total'] * 100) if on_t.get('total') else None
                qty_pct     = (qt.get('exact', 0) / qt['total'] * 100) if qt.get('total') else None
                scores = [s for s in [on_time_pct, qty_pct] if s is not None]
                if scores:
                    value_by_id[p.id] = sum(scores) / len(scores)
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Categorías de proveedor asignadas',
                           'message': f'{updated} proveedores actualizados.', 'type': 'success'}}

    @api.model
    def _cron_compute_supplier_categories(self):
        _logger.info('MRP Planner cron: inicio actualización categorías de proveedor')
        config = self.search([], limit=1)
        if not config or not config.enable_supplier_categories or config.supplier_cat_method == 'manual':
            _logger.info('MRP Planner cron: categorías de proveedor omitidas (desactivado o modo manual)')
            return
        config.action_compute_supplier_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de proveedor')

    def action_compute_customer_categories(self):
        """Asigna categorías de cliente (ABC/RFM) a todos los partners activos.

        Requiere permiso de Administrador: escribe en res.partner.x_customer_category.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
        config = self.search([], limit=1)
        if not config or config.customer_cat_method == 'manual':
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Modo manual', 'message': 'Las categorías en modo manual se asignan desde la ficha del cliente.', 'type': 'warning'}}

        start = date.today() - timedelta(days=365)
        customers = self.env['res.partner'].search([('customer_rank', '>', 0), ('active', '=', True)])
        updated = 0

        if config.customer_cat_method in ('abc_volume', 'abc_frequency'):
            groups = self.env['sale.order'].read_group(
                [('state', 'in', ('sale', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count'],
                ['partner_id'],
            )
            if config.customer_cat_method == 'abc_volume':
                value_by_id = {g['partner_id'][0]: g['amount_total'] for g in groups}
            else:
                value_by_id = {g['partner_id'][0]: g['partner_id_count'] for g in groups}
            _assign_abc_pareto(customers, value_by_id, 'x_customer_category', _abc_thresholds(config))
            updated = len(customers)

        elif config.customer_cat_method == 'abc_rfm':
            start_dt = fields.Datetime.to_datetime(str(start))
            now_dt   = fields.Datetime.now()
            groups = self.env['sale.order'].read_group(
                [('state', 'in', ('sale', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count', 'date_order:max'],
                ['partner_id'],
            )
            data = {g['partner_id'][0]: {
                'M': g['amount_total'] or 0.0,
                'F': g['partner_id_count'] or 0,
                'R': (now_dt - g['date_order']).days if g.get('date_order') else 999,
            } for g in groups}

            # Score each dimension into 1–3 using simple thresholds
            for p in customers:
                d = data.get(p.id)
                if not d:
                    p.x_customer_category = 'E'
                    updated += 1
                    continue
                r_score = 3 if d['R'] < 30 else (2 if d['R'] < 90 else 1)
                f_score = 3 if d['F'] > 10 else (2 if d['F'] >= 3 else 1)
                data[p.id]['r_score'] = r_score
                data[p.id]['f_score'] = f_score

            m_vals = sorted([d['M'] for d in data.values() if d.get('M', 0) > 0])
            m_p33 = m_vals[len(m_vals) // 3] if m_vals else 0
            m_p66 = m_vals[2 * len(m_vals) // 3] if m_vals else 0

            for p in customers:
                d = data.get(p.id)
                if not d or p.x_customer_category == 'E':
                    continue
                m_score = 3 if d['M'] >= m_p66 else (2 if d['M'] >= m_p33 else 1)
                total_score = d['r_score'] + d['f_score'] + m_score
                if   total_score >= 8: cat = 'A'
                elif total_score >= 6: cat = 'B'
                elif total_score >= 4: cat = 'C'
                elif total_score >= 3: cat = 'D'
                else:                  cat = 'E'
                p.x_customer_category = cat
                updated += 1

        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Categorías de cliente asignadas',
                           'message': f'{updated} clientes actualizados.', 'type': 'success'}}

    @api.model
    def _cron_compute_customer_categories(self):
        _logger.info('MRP Planner cron: inicio actualización categorías de cliente')
        config = self.search([], limit=1)
        if not config or not config.enable_customer_categories or config.customer_cat_method == 'manual':
            _logger.info('MRP Planner cron: categorías de cliente omitidas (desactivado o modo manual)')
            return
        config.action_compute_customer_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de cliente')

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
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cron.sudo().write(cron_vals)
        if 'sale_cat_auto_cron' in vals or 'sale_cat_cron_number' in vals or 'sale_cat_cron_type' in vals:
            cat_cron = self.env.ref('odoo_mrp_planner.ir_cron_auto_assign_sale_categories', raise_if_not_found=False)
            if cat_cron:
                cat_cron_vals = {}
                if 'sale_cat_auto_cron' in vals:
                    cat_cron_vals['active'] = vals['sale_cat_auto_cron']
                if 'sale_cat_cron_number' in vals:
                    cat_cron_vals['interval_number'] = vals['sale_cat_cron_number']
                if 'sale_cat_cron_type' in vals:
                    cat_cron_vals['interval_type'] = vals['sale_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cat_cron.sudo().write(cat_cron_vals)
        # Supplier categories cron
        if any(k in vals for k in ('enable_supplier_categories', 'supplier_cat_cron_number', 'supplier_cat_cron_type')):
            sup_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_supplier_categories', raise_if_not_found=False)
            if sup_cron:
                sup_vals = {}
                if 'enable_supplier_categories' in vals:
                    sup_vals['active'] = vals['enable_supplier_categories']
                if 'supplier_cat_cron_number' in vals:
                    sup_vals['interval_number'] = vals['supplier_cat_cron_number']
                if 'supplier_cat_cron_type' in vals:
                    sup_vals['interval_type'] = vals['supplier_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                sup_cron.sudo().write(sup_vals)
        # Customer categories cron
        if any(k in vals for k in ('enable_customer_categories', 'customer_cat_cron_number', 'customer_cat_cron_type')):
            cust_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_customer_categories', raise_if_not_found=False)
            if cust_cron:
                cust_vals = {}
                if 'enable_customer_categories' in vals:
                    cust_vals['active'] = vals['enable_customer_categories']
                if 'customer_cat_cron_number' in vals:
                    cust_vals['interval_number'] = vals['customer_cat_cron_number']
                if 'customer_cat_cron_type' in vals:
                    cust_vals['interval_type'] = vals['customer_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cust_cron.sudo().write(cust_vals)
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
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
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
