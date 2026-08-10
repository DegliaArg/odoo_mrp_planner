"""
Módulo: mrp_reschedule_config_forecast.py
Modelo: extensión de mrp.reschedule.config

Configuración del forecast, la comparativa Producido vs Programado y la carga
de centros de trabajo: umbrales de color (brechas, precisión, cobertura,
cumplimiento, carga de CT), estados de OF incluidos, criterio temporal de la
comparativa, rotación/cobertura de inventario del forecast y fórmula de
precisión. Solo campos: la lógica de cálculo vive en
mrp_forecast_calc_mixin.py y mrp_planner_dashboard_forecast.py.

Mismo patrón de extensión por dominio que mrp_partner_category.py
(categorías) y mrp_reschedule_config_inventory.py (Panel de Inventario).
"""
from odoo import models, fields


class MrpRescheduleConfigForecast(models.Model):
    _inherit = 'mrp.reschedule.config'

    # ── Forecast ─────────────────────────────────────────────────────────────

    # Umbrales de color de brechas y precisión del forecast (antes hardcodeados)
    forecast_gap_ok_pct = fields.Integer(
        string='Brecha aceptable (%)', default=10,
        help='Brecha demanda/OF vs forecast: hasta este % (en valor absoluto) se muestra en verde.')
    forecast_gap_warn_pct = fields.Integer(
        string='Brecha de aviso (%)', default=25,
        help='Brecha demanda/OF vs forecast: hasta este % se muestra en amarillo; por encima, rojo.')
    forecast_acc_green_pct = fields.Integer(
        string='Precisión buena (%)', default=90,
        help='Precisión del forecast: desde este % se muestra en verde.')
    forecast_acc_warn_pct = fields.Integer(
        string='Precisión aceptable (%)', default=70,
        help='Precisión del forecast: desde este % (y por debajo del verde) se muestra en amarillo; menos, rojo.')

    forecast_warning_pct = fields.Integer(
        string='Cobertura mínima (aviso %)', default=70,
        help='Por debajo de este % la celda se muestra en amarillo.')
    forecast_critical_pct = fields.Integer(
        string='Cobertura mínima (crítico %)', default=50,
        help='Por debajo de este % la celda se muestra en rojo.')

    # Estados de OF a incluir en la comparativa forecast
    forecast_mo_state_draft     = fields.Boolean(string='Borrador',          default=False,
        help='Incluye OFs en borrador en el cálculo de Programado (comparativa y forecast).')
    forecast_mo_state_confirmed = fields.Boolean(string='Confirmada',        default=True,
        help='Incluye OFs confirmadas en el cálculo de Programado (comparativa y forecast).')
    forecast_mo_state_progress  = fields.Boolean(string='En progreso',       default=True,
        help='Incluye OFs en progreso en el cálculo de Programado (comparativa y forecast).')
    forecast_mo_state_to_close  = fields.Boolean(string='Por cerrar',        default=True,
        help='Incluye OFs por cerrar en el cálculo de Programado (comparativa y forecast).')
    forecast_mo_state_done      = fields.Boolean(string='Terminada',         default=False,
        help='Incluye OFs terminadas en el cálculo de Programado (comparativa y forecast).')

    comparison_date_mode = fields.Selection([
        ('finish_date',  'Por fecha de cierre'),
        ('start_date',   'Por fecha de inicio'),
        ('overlap',      'Por solapamiento completo'),
        ('proportional', 'Proporcional por duración'),
    ], string='Criterio de OFs en comparativa, forecast y carga de CT', default='finish_date',
       help='Define cómo se asignan las OFs/OTs a un período en la comparativa, el forecast y el análisis de carga de centros de trabajo.\n'
            'Por fecha de cierre: solo OFs cuya fecha de fin cae dentro del período.\n'
            'Por fecha de inicio: solo OFs cuya fecha de inicio cae dentro del período.\n'
            'Por solapamiento: toda OF activa durante el período (puede aparecer en varios).\n'
            'Proporcional: distribuye las cantidades según el tiempo que solapa el período; '
            'el producido usa los movimientos reales de stock con fecha en el período.')

    wc_load_warn_pct = fields.Integer(
        string='Carga de CT — umbral amarillo (%)', default=70,
        help='La carga de centros de trabajo (planificado ÷ disponible) se muestra en amarillo desde este %.')
    wc_load_crit_pct = fields.Integer(
        string='Carga de CT — umbral rojo (%)', default=90,
        help='La carga de centros de trabajo se muestra en rojo desde este %.')

    comparison_pct_green = fields.Integer(
        string='Cumplimiento bueno (%)', default=90,
        help='Comparativo Producido vs Programado: desde este % de cumplimiento se muestra en verde.')
    comparison_pct_warn = fields.Integer(
        string='Cumplimiento aceptable (%)', default=50,
        help='Comparativo Producido vs Programado: desde este % (y por debajo del verde) se muestra en amarillo; menos, rojo.')

    comparison_force_integer = fields.Boolean(
        string='Forzar cantidades enteras en el comparativo',
        default=False,
        help='Redondea a enteros las cantidades de Producido vs Programado en el modo '
             'Proporcional por duración, en lugar de usar la precisión de la UdM de cada '
             'producto. Es solo presentación del tablero: no modifica OFs ni movimientos.')

    comparison_weight = fields.Selection([
        ('qty',        'Cantidad (piezas)'),
        ('sale_price', 'Valor — precio de venta'),
        ('cost',       'Valor — costo'),
        ('wc_hours',   'Horas de centro de trabajo'),
    ], string='Ponderación del cumplimiento', default='cost', required=True,
       help='Cómo se pondera el KPI global de cumplimiento Producido vs Programado, '
            'para que sea representativo del mix (no lo domine el producto de mayor volumen '
            'ni se mezclen unidades de medida):\n'
            '• Cantidad: suma de piezas. Mezcla unidades de medida distintas: el total es referencial.\n'
            '• Valor — precio de venta: cantidad × precio de venta del artículo. No tiene sentido sin precio de venta cargado.\n'
            '• Valor — costo: cantidad × costo (precio estándar). No tiene sentido sin costo cargado.\n'
            '• Horas de centro de trabajo: cantidad × tiempo estándar por unidad de la ruta de la BoM. '
            'No tiene sentido sin una BoM con operaciones; los productos sin ruta se excluyen.')
    comparison_fill_cap = fields.Boolean(
        string='Cumplimiento con tope al 100% por producto', default=True,
        help='Si está activo, cada producto aporta al cumplimiento como máximo su cantidad '
             'programada: la sobreproducción de un producto NO compensa el faltante de otro '
             '(criterio de fill rate, recomendado para un mix de producción). Si está '
             'desactivado, la sobreproducción se acredita y el cumplimiento puede superar 100%.')

    forecast_rotation_unit = fields.Selection([
        ('days',   'Días'),
        ('months', 'Meses'),
    ], string='Unidad de rotación de inventario', default='days',
       help='Determina si la rotación de inventario en el widget de forecast se muestra en días o en meses.'
    )

    forecast_rotation_method = fields.Selection([
        ('units', 'Por unidades'),
        ('cogs',  'Por COGS (a costo)'),
        ('sales', 'Por ventas (a precio)'),
    ], string='Método de rotación de inventario', default='units',
       help='Fórmula base para calcular la rotación de inventario.\n'
            'Unidades: días del período × stock promedio ÷ total entregado. No requiere valorización.\n'
            'COGS: días del período × inventario promedio (a costo) ÷ costo de lo vendido. Requiere valorización de stock activa.\n'
            'Ventas: días del período × inventario promedio (a costo) ÷ ventas netas (a precio).'
    )

    forecast_coverage_unit = fields.Selection([
        ('days',   'Días'),
        ('months', 'Meses'),
    ], string='Unidad de cobertura de inventario', default='days',
       help='Determina si la cobertura de inventario en el forecast se muestra en días o en meses.'
    )

    forecast_coverage_demand_source = fields.Selection([
        ('forecast',  'Forecast planificado'),
        ('so_demand', 'Demanda real (pedidos SO)'),
        ('delivered', 'Entregado histórico'),
    ], string='Fuente de demanda para cobertura', default='forecast',
       help='Denominador para calcular cuántos días dura el stock:\n'
            'Forecast: stock ÷ (forecast ÷ días). Usa lo planeado. Ideal si el forecast es confiable.\n'
            'Demanda SO: stock ÷ (pedidos confirmados ÷ días). Usa la demanda real del período. Más conservador si la demanda supera el plan.\n'
            'Entregado: stock ÷ (entregado ÷ días). Usa el historial de entregas. Refleja la velocidad real de salida de stock.'
    )

    forecast_coverage_alerts_enabled = fields.Boolean(
        string='Mostrar alertas de cobertura', default=False,
        help='Activa colores en la columna de cobertura según los umbrales configurados. '
             'Verde: cobertura suficiente. Amarillo: cobertura ajustada. Rojo: cobertura crítica.'
    )

    forecast_coverage_warn_days = fields.Integer(
        string='Cobertura — umbral amarillo (días)', default=30,
        help='Cobertura menor a este valor se muestra en amarillo (aviso). '
             'Si la unidad es meses, se convierte internamente a días (× 30).'
    )

    forecast_coverage_critical_days = fields.Integer(
        string='Cobertura — umbral rojo (días)', default=15,
        help='Cobertura menor a este valor se muestra en rojo (crítico). '
             'Si la unidad es meses, se convierte internamente a días (× 30).'
    )

    forecast_mo_coverage_show_pct = fields.Boolean(
        string='Mostrar % de cobertura junto a las OFs', default=True,
        help='Muestra el porcentaje de cobertura (ej. "500 (83%)") al lado de las cantidades de '
             'órdenes de fabricación en la tabla del forecast.'
    )

    forecast_mo_coverage_denominator = fields.Selection([
        ('forecast',  'Forecast planificado'),
        ('so_demand', 'Demanda real (pedidos SO)'),
    ], string='Divisor del % de cobertura de OFs', default='forecast',
       help='Denominador para calcular el % que aparece junto a las OFs:\n'
            'Forecast: OFs ÷ forecast × 100. Mide si la producción cubre lo planeado.\n'
            'Demanda SO: OFs ÷ pedidos confirmados × 100. Mide si la producción cubre lo que realmente pidieron los clientes.'
    )

    forecast_mo_coverage_color_scope = fields.Selection([
        ('both',       'Celdas mensuales y total'),
        ('total_only', 'Solo columna de totales'),
    ], string='Alcance del color de cobertura', default='both',
       help='Controla en qué celdas se aplican los colores verde/amarillo/rojo de cobertura de OFs:\n'
            'Celdas mensuales y total: color en cada mes y en la columna de total del período.\n'
            'Solo columna de totales: los meses individuales se muestran sin color; el total del período sí se colorea.'
    )

    forecast_acc_formula = fields.Selection([
        ('simple', 'Simple'),
        ('mape',   'MAPE'),
        ('wape',   'WAPE'),
        ('wmape',  'WMAPE'),
        ('bias',   'Sesgo'),
    ], string='Fórmula de precisión forecast', default='simple',
       help='Simple: real ÷ forecast × 100, puede superar 100%.\n'
            'MAPE: precisión media por período (100 − |error/real|×100); sensible a períodos de bajo volumen.\n'
            'WAPE: 100 − Σ|error|/Σreal×100; pondera por volumen real, robusto ante ceros en la demanda real.\n'
            'WMAPE: 100 − Σ|error|/Σforecast×100; pondera por volumen planificado, estándar supply chain.\n'
            'Sesgo: (real − forecast)/forecast×100; positivo = sobre-demanda, negativo = déficit.'
    )
    forecast_precision_source = fields.Selection([
        ('demand',   'Demanda confirmada (órdenes de venta)'),
        ('delivery', 'Entregas completadas'),
    ], string='Fuente del "real" para precisión', default='demand',
       help='Dato usado como volumen real al calcular la precisión del forecast.\n'
            'Demanda: unidades en órdenes de venta confirmadas (state sale/done).\n'
            'Entregas: movimientos de salida completados del período.')
