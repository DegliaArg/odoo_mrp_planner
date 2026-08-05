"""
Módulo: mrp_reschedule_config.py
Modelo: mrp.reschedule.config

Singleton de configuración central del planificador MRP.

Responsabilidades:
- Almacenar y persistir todos los parámetros del módulo (alertas, forecast,
  categorías de venta/proveedor/cliente, umbrales ABC/Pareto).
- Sincronizar los ajustes relevantes con ir.config_parameter para que otros
  modelos puedan leerlos sin depender de este singleton.
- Actualizar los ir.cron del módulo (frecuencia de detección de retrasos y
  recálculo automático de categorías) cuando se modifican los campos
  correspondientes.
- Garantizar que solo exista un registro (patrón singleton).

Relacionado con:
- mrp.partner.category: usa las funciones _abc_thresholds, _assign_abc_pareto y
  _assign_abc_pareto_lower para aplicar la clasificación ABC a proveedores/clientes.
- ir.cron (odoo_mrp_planner.*): los campos cron_interval_* y *_cron_* controlan
  directamente los registros de cron del módulo.
- odoo_mrp_planner_scheduling: agrega a este singleton los campos de
  programación (enable_scheduling, wc_fallback, priority) por herencia.
"""
import logging
from datetime import date, datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError
from .mrp_abc_helpers import _abc_thresholds, _assign_abc_pareto, _assign_abc_pareto_lower

_logger = logging.getLogger(__name__)


class MrpRescheduleConfig(models.Model):
    _name = 'mrp.reschedule.config'
    _description = 'Configuración del planificador de producción'
    _rec_name = 'name'
    _sql_constraints = [
        ('singleton', 'UNIQUE(singleton_check, company_id)',
         'Solo puede existir una configuración del planificador por empresa.'),
    ]

    singleton_check = fields.Boolean(default=True, string='Singleton')
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    name = fields.Char(compute='_compute_name', string='Nombre')

    # ── Alertas ──────────────────────────────────────────────────────────────

    cron_interval_number = fields.Integer(string='Revisar alertas cada', default=30,
        help='Frecuencia con que el cron de detección revisa las OFs y OCs '
             'para generar o resolver alertas automáticamente. '
             'Valores bajos = más reactivo, mayor carga en el servidor.')
    cron_interval_type = fields.Selection([
        ('minutes', 'Minutos'),
        ('hours', 'Horas'),
    ], string='Unidad del intervalo de alertas', default='minutes',
       help='Unidad de tiempo para el intervalo del cron de detección de retrasos. '
            'Combinar con "Cada" para definir la frecuencia total.')

    alert_mo_critical_days      = fields.Integer(string='Días críticos OF',             default=3,
        help='OFs cuya fecha de fin planificada está a ≤ estos días generan alerta crítica (rojo).')
    alert_po_critical_days      = fields.Integer(string='Días críticos OC',             default=5,
        help='OCs cuya fecha de entrega planificada está a ≤ estos días generan alerta crítica (rojo).')
    alert_receipt_critical_days = fields.Integer(string='Días críticos recepción',      default=3,
        help='Recepciones pendientes con fecha esperada a ≤ estos días generan alerta crítica (rojo).')
    alert_mo_warning_days       = fields.Integer(string='Días por vencer OF',           default=7,
        help='OFs cuya fecha de fin planificada está a ≤ estos días (y > días críticos) generan aviso (amarillo).')
    alert_po_warning_days       = fields.Integer(string='Días por vencer OC',           default=10,
        help='OCs cuya fecha de entrega planificada está a ≤ estos días (y > días críticos) generan aviso (amarillo).')
    qty_tolerance_pct           = fields.Float(  string='Tolerancia cantidad (%)',      default=5.0,
        help='Diferencia porcentual aceptable entre cantidad pedida y recibida antes de generar alerta de desvío de cantidad.')

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

    stock_break_show_rotation = fields.Boolean(
        string='Mostrar rotación en quiebres de stock', default=False,
        help='Si está activo, se muestra la columna de rotación de inventario en el widget de quiebres de stock.'
    )
    stock_break_rotation_method = fields.Selection([
        ('units', 'Por unidades'),
        ('cogs',  'Por COGS (a costo)'),
        ('sales', 'Por ventas (a precio)'),
    ], string='Método de rotación (quiebres)', default='units',
       help='Fórmula para calcular la rotación en el widget de quiebres de stock.\n'
            'Unidades: stock promedio del período ÷ (salidas del período ÷ meses). No requiere valorización.\n'
            'COGS: días × inventario promedio (a costo) ÷ costo de lo vendido. Requiere valorización activa.\n'
            'Ventas: días × inventario promedio (a costo) ÷ ventas netas (a precio).'
    )
    stock_break_rotation_months = fields.Integer(
        string='Período de rotación (meses)', default=3,
        help='Cantidad de meses de historial a considerar para calcular la rotación en el widget de quiebres de stock.'
    )
    stock_break_rotation_alerts_enabled = fields.Boolean(
        string='Mostrar alertas de rotación', default=False,
        help='Activa colores e ícono de advertencia en la columna de rotación según los umbrales configurados.'
    )
    stock_break_rotation_warn_days = fields.Integer(
        string='Rotación — umbral amarillo (días)', default=90,
        help='Rotación mayor a este valor → amarillo.'
    )
    stock_break_rotation_critical_days = fields.Integer(
        string='Rotación — umbral rojo (días)', default=180,
        help='Rotación mayor a este valor → rojo con ícono de advertencia.'
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
            'Rotación: calcula stock promedio ÷ entregas y asigna A–E por días de cobertura. '
            'Demanda: asigna A–E por unidades demandadas (OVs confirmadas) promedio por mes. '
            'Participación: ordena por métrica y clasifica por % acumulado del total.')

    sale_cat_lookback_months = fields.Integer(
        string='Cat. de venta — período de análisis (meses)', default=3,
        help='Cantidad de meses hacia atrás que se analizan las entregas para calcular '
             'la demanda, rotación o participación. Por defecto 3 meses.')
    sale_cat_rotation_source = fields.Selection([
        ('delivery', 'Entregas completadas'),
        ('demand',   'Demanda confirmada (OVs)'),
    ], string='Fuente — denominador de rotación', default='delivery',
       help='Datos usados como denominador para calcular días de cobertura en el modo automático.\n'
            'Entregas: movimientos de salida completados del período.\n'
            'Demanda: unidades en órdenes de venta confirmadas del período.')

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

    show_po_services_tab = fields.Boolean(
        string='Mostrar pestaña de servicios en OCs',
        default=False,
        help='Muestra u oculta la pestaña "Servicios" en las órdenes de compra. '
             'Útil para empresas que no gestionan servicios desde OCs y desean '
             'simplificar la interfaz.',
    )

    exclude_service_pos = fields.Boolean(
        string='Excluir OC de servicios de los KPIs',
        default=True,
        help='Cuando está activo, las OCs cuyas líneas son todas de tipo servicio '
             '(sin recepción de mercadería) se excluyen de los contadores KPI del '
             'panel de compras. Siguen visibles en la pestaña "Servicios" si está habilitada.',
    )

    supplier_analysis_date_field = fields.Selection([
        ('date_approve', 'Fecha de aprobación'),
        ('date_order',   'Fecha de pedido'),
        ('date_planned', 'Fecha de entrega planificada'),
    ], string='Fecha para análisis de proveedores', default='date_approve',
       help='Campo de fecha utilizado como referencia temporal al calcular métricas '
            'de proveedor (entregas a tiempo, retrasos, etc.). '
            '"Aprobación" es la fecha en que la OC fue confirmada por el proveedor; '
            '"Pedido" es cuando se generó la OC en Odoo; '
            '"Entrega planificada" es la fecha comprometida de recepción.')

    # ── Umbrales análisis de proveedores ──────────────────────────────────────
    sup_on_time_green_pct   = fields.Integer(string='% A tiempo — verde (≥)',       default=90,
        help='Umbral superior de puntualidad: proveedores con % de entregas a tiempo ≥ este valor se muestran en verde.')
    sup_on_time_yellow_pct  = fields.Integer(string='% A tiempo — amarillo (≥)',    default=70,
        help='Umbral intermedio de puntualidad: entre este valor y el verde se muestra en amarillo; por debajo en rojo.')
    sup_delay_green_days    = fields.Integer(string='Retraso — verde (≤ días)',      default=1,
        help='Retraso promedio aceptable: proveedores con retraso medio ≤ este valor se muestran en verde.')
    sup_delay_yellow_days   = fields.Integer(string='Retraso — amarillo (≤ días)',  default=3,
        help='Retraso promedio tolerable: entre el umbral verde y este valor se muestra en amarillo; por encima en rojo.')
    sup_complete_green_pct  = fields.Integer(string='% Completas — verde (≥)',      default=95,
        help='Umbral de completitud: % de recepciones sin diferencia de cantidad ≥ este valor se muestra en verde.')
    sup_complete_yellow_pct = fields.Integer(string='% Completas — amarillo (≥)',   default=80,
        help='Umbral intermedio de completitud: entre este valor y el verde se muestra en amarillo; por debajo en rojo.')
    sup_price_var_green_pct  = fields.Float( string='Var. precio — verde (|%| ≤)',  default=3.0,
        help='Variación de precio aceptable: |desviación| ≤ este % respecto a la referencia configurada '
             '(costo estándar, lista de proveedor o precio anterior pagado) se muestra en verde.')
    sup_price_var_yellow_pct = fields.Float( string='Var. precio — amarillo (|%| ≤)', default=10.0,
        help='Variación de precio tolerable: entre el umbral verde y este % se muestra en amarillo; por encima en rojo.')
    supplier_price_var_method = fields.Selection([
        ('standard',   'Costo estándar del producto'),
        ('pricelist',  'Lista de precio del proveedor'),
        ('previous',   'Precio anterior pagado'),
    ], string='Referencia para variación de precio', default='previous',
       help='Precio de referencia para calcular la variación de precio, tanto en el análisis de '
            'proveedores (columna) como en la clasificación ABC por variación de precio.\n'
            'Costo estándar: compara precio OC vs. standard_price del producto.\n'
            'Lista de precio del proveedor: compara precio OC vs. precio en product.supplierinfo. '
            'Si el proveedor no tiene precio configurado para ese producto, queda sin variación.\n'
            'Precio anterior pagado: compara cada compra con el precio de la compra anterior del '
            'mismo producto al mismo proveedor (tendencia de precio; no depende del costo estándar, '
            'que puede ser muy volátil).')

    # ── Auto-actualización categoría de venta ─────────────────────────────────
    sale_cat_auto_cron   = fields.Boolean(string='Actualización automática (cat. de venta)', default=False,
        help='Recalcula las categorías de venta automáticamente según el intervalo configurado. '
             'Si está desactivado, las categorías solo se actualizan con el botón manual.')
    sale_cat_cron_number = fields.Integer(string='Cat. de venta — cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de venta.')
    sale_cat_cron_type   = fields.Selection([
        ('days',   'Días'),
        ('weeks',  'Semanas'),
        ('months', 'Meses'),
    ], string='Cat. de venta — unidad', default='weeks',
       help='Unidad de tiempo para el intervalo de recálculo automático de categorías de venta.')

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
            'ABC por volumen: Pareto por importe total de OCs según el período de análisis '
            'configurado y los umbrales Pareto configurados '
            '(defaults: primero 20% = A, 50% = B, 80% = C, 95% = D, resto = E).\n'
            'ABC por frecuencia: igual que volumen pero por cantidad de OCs.\n'
            'ABC por RFM: scoring Recencia + Frecuencia + Monetario (1-3 pts c/u); '
            'los cortes de score, recencia y frecuencia son configurables '
            '(defaults: suma 8-9 = A, 6-7 = B, 4-5 = C, 3 = D, < 3 = E).\n'
            'ABC por % de entrega a tiempo: Pareto por % de recepciones completadas '
            'antes o en la fecha planificada. Mayor % = mejor categoría.\n'
            'ABC por variación de precio: Ranking por percentil por |variación de precio vs. la referencia '
            'configurada| (costo estándar, lista de proveedor o precio anterior pagado, según "Referencia '
            'para variación de precio"). Menor variación = mejor categoría.\n'
            'ABC por calidad — diferencia de cantidad: Pareto por % de movimientos de recepción '
            'donde la cantidad recibida coincide exactamente con la pedida.\n'
            'ABC por calidad — devoluciones: Ranking por percentil por cantidad de devoluciones al proveedor. '
            'Menos devoluciones = mejor categoría.\n'
            'ABC por calidad — combinado: promedio de % entrega a tiempo y % sin diferencia de cantidad.')
    supplier_cat_cron_number = fields.Integer(string='Cat. de proveedor — cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de proveedor.')
    supplier_cat_cron_type   = fields.Selection([
        ('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'),
    ], string='Cat. de proveedor — unidad', default='weeks',
       help='Unidad de tiempo para el intervalo de recálculo automático de categorías de proveedor.')
    supplier_cat_auto_cron = fields.Boolean(
        string='Actualización automática (cat. de proveedor)', default=False,
        help='Recalcula las categorías de proveedor automáticamente según el intervalo configurado.')
    supplier_cat_lookback_months = fields.Integer(
        string='Cat. de proveedor — período de análisis (meses)', default=12,
        help='Cantidad de meses de historial que se consideran al calcular las categorías de proveedor. '
             'Afecta al botón "Calcular ahora" y al cron automático.')

    # Umbrales Pareto (aplican a todos los métodos ABC Pareto, no a RFM ni manual)
    abc_pct_a = fields.Integer(string='A ≤', default=20,
        help='Acumulado máximo (%) para categoría A. Proveedores/clientes que suman hasta este % del total = A.')
    abc_pct_b = fields.Integer(string='B ≤', default=50,
        help='Acumulado máximo (%) para categoría B.')
    abc_pct_c = fields.Integer(string='C ≤', default=80,
        help='Acumulado máximo (%) para categoría C.')
    abc_pct_d = fields.Integer(string='D ≤', default=95,
        help='Acumulado máximo (%) para categoría D. El resto queda en E.')

    # Parámetros del scoring RFM (aplican a clientes y proveedores con método "ABC por RFM").
    rfm_recency_recent_days = fields.Integer(string='Recencia reciente (días) <', default=30,
        help='Días desde la última compra por debajo de los cuales la recencia puntúa 3 (reciente).')
    rfm_recency_medium_days = fields.Integer(string='Recencia media (días) <', default=90,
        help='Días desde la última compra por debajo de los cuales la recencia puntúa 2 (media). '
             'Por encima puntúa 1.')
    rfm_freq_high = fields.Integer(string='Frecuencia alta (> pedidos)', default=10,
        help='Cantidad de pedidos por encima de la cual la frecuencia puntúa 3 (alta).')
    rfm_freq_medium = fields.Integer(string='Frecuencia media (≥ pedidos)', default=3,
        help='Cantidad de pedidos a partir de la cual la frecuencia puntúa 2 (media). Menos puntúa 1.')
    rfm_score_a = fields.Integer(string='RFM A ≥', default=8,
        help='Score total (3–9) a partir del cual la categoría es A.')
    rfm_score_b = fields.Integer(string='RFM B ≥', default=6,
        help='Score total a partir del cual la categoría es B.')
    rfm_score_c = fields.Integer(string='RFM C ≥', default=4,
        help='Score total a partir del cual la categoría es C.')
    rfm_score_d = fields.Integer(string='RFM D ≥', default=3,
        help='Score total a partir del cual la categoría es D. Por debajo queda en E.')

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
            'según el período de análisis configurado y aplica Pareto acumulado con los '
            'umbrales configurados (defaults: primero 20% del total = A, hasta 50% = B, '
            'hasta 80% = C, hasta 95% = D, resto = E).\n'
            'ABC por frecuencia: igual que volumen pero pondera por cantidad de SOs en vez del importe. '
            'Favorece clientes con alta frecuencia de pedidos.\n'
            'ABC por RFM: scoring multidimensional — '
            'Recencia (días desde el último SO, cortes configurables; defaults < 30d = 3pts, < 90d = 2pts, resto = 1pt), '
            'Frecuencia (SOs del período, cortes configurables; defaults > 10 = 3pts, ≥ 3 = 2pts, resto = 1pt), '
            'Monetario (importe relativo al percentil 33/66 del grupo: alto = 3pts, medio = 2pts, bajo = 1pt). '
            'Cortes de score configurables (defaults: suma 8-9 = A, 6-7 = B, 4-5 = C, 3 = D, < 3 = E).')
    customer_cat_cron_number = fields.Integer(string='Cat. de cliente — cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de cliente.')
    customer_cat_cron_type   = fields.Selection([
        ('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'),
    ], string='Cat. de cliente — unidad', default='weeks',
       help='Unidad de tiempo para el intervalo de recálculo automático de categorías de cliente.')
    customer_cat_auto_cron = fields.Boolean(
        string='Actualización automática (cat. de cliente)', default=False,
        help='Recalcula las categorías de cliente automáticamente según el intervalo configurado.')
    customer_cat_lookback_months = fields.Integer(
        string='Cat. de cliente — período de análisis (meses)', default=12,
        help='Cantidad de meses de historial que se consideran al calcular las categorías de cliente. '
             'Afecta al botón "Calcular ahora" y al cron automático.')

    # ── Análisis de clientes ─────────────────────────────────────────────────
    # Última corrida (manual o por cron) de cada asignación automática de
    # categorías; se muestran como registro en Ajustes → General.
    run_log_keep = fields.Integer(
        string='Ejecuciones a conservar (por proceso)', default=100,
        help='Cantidad de corridas que guarda el Registro de ejecuciones por cada '
             'proceso y empresa (categorías, chequeo de alertas, importación de '
             'forecast). Al superar el límite se borran las más antiguas.')

    sale_cat_last_run = fields.Datetime(string='Última asignación — categorías de venta', readonly=True)
    sale_cat_last_count = fields.Integer(string='Artículos actualizados (última corrida)', readonly=True)
    supplier_cat_last_run = fields.Datetime(string='Última asignación — categorías de proveedor', readonly=True)
    supplier_cat_last_count = fields.Integer(string='Proveedores actualizados (última corrida)', readonly=True)
    customer_cat_last_run = fields.Datetime(string='Última asignación — categorías de cliente', readonly=True)
    customer_cat_last_count = fields.Integer(string='Clientes actualizados (última corrida)', readonly=True)

    sales_amount_method = fields.Selection([
        ('pxq',  'PxQ a precio de lista'),
        ('real', 'Importe real de pedidos'),
    ], string='Valorización monetaria de ventas', default='pxq',
       help='Cómo se valorizan los montos del análisis de clientes.\n'
            'PxQ a precio de lista: cantidad × precio de venta ACTUAL de la ficha del '
            'artículo. Precios constantes: no lo afectan descuentos ni inflación, pero '
            'NO considera precios históricos ni cuadra con la facturación.\n'
            'Importe real: precio efectivo de cada línea de pedido (con descuentos, '
            'sin impuestos). Cuadra con los pedidos/facturación.')
    customer_analysis_exclude_services = fields.Boolean(
        string='Excluir servicios de los análisis de ventas',
        default=False,
        help='Cuando está activo, las líneas de productos de tipo Servicio no se '
             'cuentan ni en el análisis de clientes (montos, piezas, precio promedio, '
             'top de artículos) ni en el panel de ventas (Demanda real, Cumplimiento '
             'de demanda y los agregados "sin FC" que alimentan las tasas). Las '
             'entregas físicas no cambian: los servicios no generan remitos.')
    customer_unify_by_vat = fields.Boolean(
        string='Unificar clientes por CUIT',
        default=False,
        help='En el análisis de clientes, fusiona en una sola fila los contactos que '
             'comparten el mismo CUIT/NIF (razones sociales distintas del mismo cliente). '
             'Se muestran con el nombre de la razón social de mayor facturación del período. '
             'Los contactos sin CUIT no se unifican.')
    customer_analysis_ontime_method = fields.Selection([
        ('commitment_date', 'Fecha compromiso del pedido'),
        ('scheduled_date',  'Fecha programada del envío'),
        ('sla_days',        'Días desde confirmación del pedido'),
    ], string='Método "entrega a tiempo"', default='commitment_date',
       help='Define cómo se calcula si una entrega fue a tiempo.\n'
            '• Fecha compromiso: compara la fecha real de entrega con la fecha '
            'pactada con el cliente en el pedido de venta (campo commitment_date).\n'
            '• Fecha programada del envío: usa la fecha programada del picking de salida.\n'
            '• Días desde confirmación: considera a tiempo si se entregó dentro de N días '
            'desde la confirmación del pedido (configurable en "SLA en días").')
    customer_analysis_sla_days = fields.Integer(
        string='SLA en días', default=5,
        help='Solo aplica cuando el método es "Días desde confirmación". '
             'Define cuántos días tiene la empresa para entregar desde que se confirma el pedido.')
    customer_leadtime_method = fields.Selection([
        ('weighted', 'Ponderado por cantidades entregadas'),
        ('first',    'Primera entrega'),
        ('complete', 'Pedido completo'),
    ], string='Método — Lead time de entrega', default='weighted',
       help='Cómo se calcula el tiempo promedio de entrega de los pedidos con entregas '
            'parciales. Todos los métodos miden días desde la confirmación del pedido '
            'hasta la fecha efectiva de cada remito de salida.\n'
            '• Ponderado: promedia los días de cada parcial pesándolos por la cantidad '
            'entregada — cuántos días esperó la pieza promedio.\n'
            '• Primera entrega: días hasta el primer remito — velocidad de reacción.\n'
            '• Pedido completo: días hasta el remito que completó el pedido; solo cuenta '
            'pedidos totalmente entregados.\n'
            'El método elegido manda en el KPI y la columna; los otros dos se muestran '
            'como referencia secundaria y en el tooltip.')
    customer_analysis_delivery_warn_pct = fields.Integer(
        string='Tasas — umbral verde (%)', default=80,
        help='Desde este porcentaje, las tasas de entrega se muestran en verde. Aplica a las tasas del análisis de clientes y a las tasas física y de cumplimiento del panel de ventas.'
             'la celda se muestra en amarillo en el análisis de clientes.')
    customer_analysis_delivery_crit_pct = fields.Integer(
        string='Tasas — umbral amarillo (%)', default=60,
        help='Desde este porcentaje (y por debajo del verde), las tasas se muestran en amarillo; menos, rojo. Aplica al análisis de clientes y al panel de ventas.'
             'la celda se muestra en rojo en el análisis de clientes.')
    customer_analysis_ontime_warn_pct = fields.Integer(
        string='% a tiempo — umbral amarillo', default=80,
        help='Por debajo de este porcentaje de entregas a tiempo, '
             'la celda se muestra en amarillo.')
    customer_analysis_ontime_crit_pct = fields.Integer(
        string='% a tiempo — umbral rojo', default=60,
        help='Por debajo de este porcentaje de entregas a tiempo, '
             'la celda se muestra en rojo.')
    customer_analysis_risk_days = fields.Integer(
        string='Días sin comprar (riesgo)', default=90,
        help='Un cliente que no compra hace más de este número de días '
             'se clasifica como "en riesgo" en la columna de frecuencia.')
    customer_analysis_abc_a_pct = fields.Integer(
        string='Segmento A — % acumulado', default=20,
        help='Clientes que suman el primer X% del monto total del período se clasifican como A. '
             'Se ordena de mayor a menor monto antes de acumular.')
    customer_analysis_abc_b_pct = fields.Integer(
        string='Segmento B — % acumulado adicional', default=50,
        help='Del monto restante tras el segmento A, los clientes que suman el siguiente X% '
             'se clasifican como B. El resto queda en C.')

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock (quiebres)',
        domain=[('usage', '=', 'internal')],
        compute='_compute_stock_location_id',
        inverse='_set_stock_location_id',
        store=False,
        help='Ubicación interna desde la cual se lee el stock actual en el widget de quiebres de stock.',
    )

    @api.model
    def get_config(self):
        """Retorna la configuración de la empresa actual; la crea si no existe.

        En multiempresa, cada compañía tiene su propio registro. Antes se creaba de
        forma perezosa solo al abrir Ajustes, así que una empresa donde nunca se abrió
        corría con los defaults hardcodeados en TODO el módulo (umbrales, métodos,
        exclusión de servicios, etc.), dando comportamientos distintos por empresa.
        Ahora se crea al vuelo (sudo) para garantizar consistencia entre compañías.
        """
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.sudo().create({'company_id': self.env.company.id})
        return config

    @api.depends()
    def _compute_stock_location_id(self):
        """
        Calcula stock_location_id para cada registro.

        Fórmula: lee el ID entero desde ir.config_parameter y resuelve el
        registro de stock.location correspondiente. Si el parámetro está vacío,
        es inválido o la ubicación fue eliminada, devuelve False.
        Depende de: ir.config_parameter['mrp_reschedule.stock_location_id'].
        """
        param = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.stock_location_id')
        # int() puede lanzar ValueError si el parámetro fue editado manualmente
        try:
            loc_id = int(param) if param else False
        except (ValueError, TypeError):
            loc_id = False
        location = self.env['stock.location'].browse(loc_id) if loc_id else \
            self.env['stock.location']
        for rec in self:
            rec.stock_location_id = location if loc_id and location.exists() else False

    def _set_stock_location_id(self):
        """Persiste stock_location_id en ir.config_parameter como cadena del ID."""
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                'mrp_reschedule.stock_location_id',
                str(rec.stock_location_id.id) if rec.stock_location_id else '',
            )

    @api.depends()
    def _compute_name(self):
        """
        Calcula name para cada registro.

        Fórmula: valor fijo — el singleton siempre tiene el mismo nombre visible.
        Depende de: ningún campo (nombre constante).
        """
        for rec in self:
            rec.name = 'Configuración del planificador'

    def action_open_user_warehouses(self):
        """
        Abre la lista unificada de usuarios con depósitos y secciones visibles del Planificador MRP.

        :returns: dict — acción de ventana (ir.actions.act_window) que muestra
                  res.users con la vista personalizada view_users_mrp_warehouse_list,
                  filtrando solo usuarios activos no compartidos (internos).
        """
        return {
            'type':      'ir.actions.act_window',
            'name':      'Preferencias por usuario',
            'res_model': 'res.users',
            'view_mode': 'list',
            'view_id':   self.env.ref('odoo_mrp_planner.view_users_mrp_warehouse_list').id,
            'domain':    [('share', '=', False), ('active', '=', True)],
            'target':    'current',
        }

    def _user_can_edit_config(self):
        """True si el usuario actual puede editar la configuración del planificador.

        Además del Administrador del módulo, los administradores de área
        (Producción, Programación, Ventas y Compras) pueden guardar la
        configuración: son los mismos grupos con permiso de escritura en
        ir.model.access.csv y a los que el menú Configuración les muestra
        su sección editable.
        """
        u = self.env.user
        return any(u.has_group(g) for g in self._config_editor_groups())

    @api.model
    def _config_editor_groups(self):
        """Grupos con permiso para editar la configuración.

        Hook extensible: odoo_mrp_planner_scheduling agrega su grupo de
        Programación a esta lista.
        """
        return [
            'odoo_mrp_planner.group_admin',
            'odoo_mrp_planner.group_prod',
            'odoo_mrp_planner.group_sales',
            'odoo_mrp_planner.group_purchase_admin',
            'odoo_mrp_planner.group_inventory_admin',
            'base.group_system',
        ]

    @api.model
    def _scheduling_ui_enabled(self, user=None):
        """True si el usuario debe ver la UI de programación (pestañas, KPIs, botones).

        Hook del módulo de scheduling: sin odoo_mrp_planner_scheduling instalado
        no existe la función de programación, por lo que siempre es False.
        """
        return False

    @api.model
    def _user_in_scheduling_group(self, user=None):
        """True si el usuario pertenece al grupo de Programación (hook de scheduling)."""
        return False

    # ══ Panel de Inventario: registro de disponibilidad y presentación ═══════
    # (pestaña Inventario de los Ajustes; el circuito de despacho es una
    # extensión aparte en odoo_mrp_planner_dispatch)

    dispatch_stock_log_enabled = fields.Boolean(
        string='Registrar disponibilidad de stock para entregas',
        default=False,
        help='Activa el snapshot diario de las salidas pendientes (cantidad pendiente '
             'vs. reservada). Alimenta la "Tasa de entrega s/ disponible" del Panel de '
             'Inventario: sin registro no hay tasa.')
    dispatch_snapshot_hour = fields.Float(
        string='Hora del snapshot', default=20.0,
        help='Hora local (0-23.99) en que corre el snapshot diario de disponibilidad. '
             'El cron es único para toda la base: si hay varias empresas con el registro '
             'activo, rige la hora guardada más recientemente.')
    dispatch_log_retention_months = fields.Integer(
        string='Retención de snapshots (meses)', default=12,
        help='Los snapshots crudos más viejos que esta cantidad de meses se purgan, '
             'solo después de que su mes quede consolidado en el histórico mensual '
             '(que no se purga nunca).')
    dispatch_pending_cutoff_months = fields.Integer(
        string='Ignorar pendientes anteriores a (meses)', default=0,
        help='Las salidas pendientes con fecha programada más vieja que esta cantidad '
             'de meses no cuentan en el Panel de Inventario ni en los snapshots de '
             'disponibilidad (0 = sin corte).')
    inventory_force_integer = fields.Boolean(
        string='Forzar cantidades enteras',
        default=False,
        help='Redondea a enteros las cantidades en piezas del Panel de Inventario '
             'y de Movimientos (las tasas y porcentajes conservan su decimal). '
             'Es independiente del "Forzar cantidades enteras" de la comparativa '
             'del forecast (Ajustes → Producción).')

    def _dispatch_pending_cutoff_domain(self, field='scheduled_date'):
        """Dominio del corte de antigüedad de pendientes.

        Con "Ignorar pendientes anteriores a (meses)" > 0, las salidas cuya
        fecha programada es más vieja que N meses quedan fuera del Panel de
        Inventario (KPIs, tabla y drills) y de los snapshots de disponibilidad.
        Con 0 no hay corte y el dominio es vacío.

        :param field: campo de fecha sobre el que filtrar ('scheduled_date' en
                      stock.picking, 'picking_id.scheduled_date' en stock.move).
        :returns: list — dominio a sumar a la búsqueda ([] = sin filtro).
        """
        months = int(self and self[0].dispatch_pending_cutoff_months or 0)
        if months <= 0:
            return []
        cutoff = fields.Date.context_today(self) - relativedelta(months=months)
        # String (no datetime): el dominio también viaja al cliente en los
        # drills del panel y tiene que ser serializable a JSON.
        return [(field, '>=', fields.Datetime.to_string(
            datetime.combine(cutoff, datetime.min.time())))]

    def _dispatch_sync_snapshot_cron(self):
        """Reprograma el próximo disparo del cron de snapshots a la hora configurada.

        El cron es global: se toma la hora del registro que se está guardando,
        interpretada en la zona horaria del usuario que guarda.
        """
        cron = self.env.ref('odoo_mrp_planner.ir_cron_dispatch_stock_snapshot',
                            raise_if_not_found=False)
        if not cron or not self:
            return
        hour = self[0].dispatch_snapshot_hour or 20.0
        hour = min(max(hour, 0.0), 23.99)
        try:
            tz = pytz.timezone(self.env.user.tz or 'UTC')
        except Exception:
            tz = pytz.utc
        now_local = datetime.now(pytz.utc).astimezone(tz)
        target = now_local.replace(hour=int(hour), minute=int(round(hour % 1 * 60)) % 60,
                                   second=0, microsecond=0)
        if target <= now_local:
            target += timedelta(days=1)
        cron.sudo().write({
            'nextcall': target.astimezone(pytz.utc).replace(tzinfo=None),
        })

    def write(self, vals):
        """
        Guarda los cambios y propaga la configuración a los ir.cron del módulo.

        Cuando se modifican campos de intervalo de cron (cron_interval_*, sale_cat_*,
        supplier_cat_*, customer_cat_*) actualiza el registro de ir.cron correspondiente
        vía sudo() porque el usuario administrador del módulo no tiene acceso directo a ir.cron.

        :param vals: dict con los campos a actualizar.
        :returns: bool — resultado del super().write().
        """
        # Modo superusuario permitido para la carga de datos del módulo (instalación/upgrade).
        if not self.env.su and not self._user_can_edit_config():
            raise AccessError(_("Solo los administradores pueden modificar la configuración"))
        res = super().write(vals)
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
        if any(k in vals for k in ('enable_supplier_categories', 'supplier_cat_auto_cron', 'supplier_cat_cron_number', 'supplier_cat_cron_type')):
            sup_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_supplier_categories', raise_if_not_found=False)
            if sup_cron:
                sup_vals = {}
                if 'supplier_cat_auto_cron' in vals:
                    sup_vals['active'] = vals['supplier_cat_auto_cron']
                if 'enable_supplier_categories' in vals and not vals['enable_supplier_categories']:
                    sup_vals['active'] = False  # disabling the feature also disables the cron
                if 'supplier_cat_cron_number' in vals:
                    sup_vals['interval_number'] = vals['supplier_cat_cron_number']
                if 'supplier_cat_cron_type' in vals:
                    sup_vals['interval_type'] = vals['supplier_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                if sup_vals:
                    sup_cron.sudo().write(sup_vals)
        # Customer categories cron
        if any(k in vals for k in ('enable_customer_categories', 'customer_cat_auto_cron', 'customer_cat_cron_number', 'customer_cat_cron_type')):
            cust_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_customer_categories', raise_if_not_found=False)
            if cust_cron:
                cust_vals = {}
                if 'customer_cat_auto_cron' in vals:
                    cust_vals['active'] = vals['customer_cat_auto_cron']
                if 'enable_customer_categories' in vals and not vals['enable_customer_categories']:
                    cust_vals['active'] = False  # disabling the feature also disables the cron
                if 'customer_cat_cron_number' in vals:
                    cust_vals['interval_number'] = vals['customer_cat_cron_number']
                if 'customer_cat_cron_type' in vals:
                    cust_vals['interval_type'] = vals['customer_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                if cust_vals:
                    cust_cron.sudo().write(cust_vals)
        if 'dispatch_snapshot_hour' in vals or vals.get('dispatch_stock_log_enabled'):
            self._dispatch_sync_snapshot_cron()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """
        Crea el registro de configuración aplicando la restricción singleton.

        Lanza UserError si ya existe un registro, garantizando que solo haya una
        instancia del planificador. Tras la creación sincroniza el cron de
        detección de retrasos con los valores del nuevo registro.

        :param vals_list: list[dict] — lista de valores para crear.
        :returns: mrp.reschedule.config — recordset con los registros creados.
        :raises UserError: si ya existe una configuración en la base de datos.
        """
        # Se permite en modo superusuario para que la carga de datos del módulo (instalación:
        # el singleton se crea como SUPERUSER, que aún no pertenece a group_admin) no falle.
        if not self.env.su and not self.env.user.has_group('odoo_mrp_planner.group_admin'):
            raise AccessError(_("Solo los administradores pueden crear la configuración"))
        # Singleton POR EMPRESA: una configuración por compañía (no una global). La unicidad
        # real la garantiza el _sql_constraints UNIQUE(singleton_check, company_id).
        for vals in vals_list:
            cid = vals.get('company_id') or self.env.company.id
            if self.search_count([('company_id', '=', cid)]) > 0:
                raise UserError(_(
                    'Ya existe una configuración del planificador para esta empresa. '
                    'Editá el registro existente en lugar de crear uno nuevo.'
                ))
        records = super().create(vals_list)
        for rec in records:
            cron = self.env.ref('odoo_mrp_planner.ir_cron_check_delays', raise_if_not_found=False)
            if cron:
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cron.sudo().write({
                    'interval_number': rec.cron_interval_number,
                    'interval_type':   rec.cron_interval_type,
                })
        if any(v.get('dispatch_stock_log_enabled') or v.get('dispatch_snapshot_hour')
               for v in vals_list):
            records._dispatch_sync_snapshot_cron()
        return records

    @api.model
    def action_open(self):
        """
        Abre el formulario de configuración del planificador (singleton).

        Busca el único registro existente y retorna una acción de ventana apuntando
        a su formulario con paginador oculto (no_pager) para reforzar la experiencia
        de singleton. Si no existe ningún registro, abre el formulario en modo creación.

        :returns: dict — acción ir.actions.act_window con res_id del singleton o
                  False si aún no fue creado.
        """
        if not self._user_can_edit_config():
            raise AccessError(_("Solo los administradores pueden acceder a la configuración"))
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            # sudo(): la creación del singleton puede ejecutarse como cualquier usuario que abre la pantalla
            config = self.sudo().create({'company_id': self.env.company.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Configuración del planificador',
            'res_model': self._name,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_reschedule_config_form_view').id,
            'res_id': config.id,
            'target': 'current',
            'flags': {'no_pager': True},
        }
