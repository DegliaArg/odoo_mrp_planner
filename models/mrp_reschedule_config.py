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
- ir.config_parameter: wc_fallback y priority se replican aquí para acceso
  eficiente sin cargar el singleton completo.
"""
import logging
from datetime import date, timedelta

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

    # ── Programación / Reprogramación ────────────────────────────────────────

    enable_scheduling = fields.Boolean(
        string='Habilitar funciones de programación y reprogramación',
        default=True,
        help='Cuando está activo, los usuarios internos ven los menús de reprogramación, '
             'los botones en las OFs y las KPIs de "Para reprogramar" en el panel de producción. '
             'Al desactivar se quita a todos los usuarios del grupo de programación; '
             'los administradores del módulo siempre conservan acceso.'
    )

    wc_fallback = fields.Selection([
        ('ldm', 'Usar operaciones de la Lista de Materiales'),
        ('none', 'Sin centro de trabajo'),
    ], string='Fallback de centro de trabajo', default='ldm', required=True)

    priority = fields.Selection([
        ('chronological', 'Orden cronológico (fecha actual)'),
        ('shortest_first', 'Más cortas primero (SPT)'),
        ('manual', 'Secuencia manual en el wizard'),
    ], string='Criterio de prioridad al reprogramar', default='chronological', required=True,
       help='Orden en que se programan las OFs cuando compiten por el mismo centro de trabajo. '
            'Cronológico: respeta las fechas actuales. '
            'SPT (más cortas primero): minimiza el tiempo de espera promedio. '
            'Manual: el operador define el orden en el wizard.'
    )

    cron_interval_number = fields.Integer(string='Cada', default=30,
        help='Frecuencia con que el cron de detección revisa las OFs y OCs '
             'para generar o resolver alertas automáticamente. '
             'Valores bajos = más reactivo, mayor carga en el servidor.')
    cron_interval_type = fields.Selection([
        ('minutes', 'Minutos'),
        ('hours', 'Horas'),
    ], string='Unidad', default='minutes',
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

    forecast_default_months = fields.Integer(
        string='Meses por defecto en forecast', default=3,
        help='Cantidad de meses que se muestran por defecto al abrir la vista de forecast. '
             'El usuario puede cambiarla manualmente en la interfaz.')
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
    ], string='Criterio de OFs en comparativa y forecast', default='finish_date',
       help='Define cómo se asignan las OFs a un período en la comparativa y el forecast.\n'
            'Por fecha de cierre: solo OFs cuya fecha de fin cae dentro del período.\n'
            'Por fecha de inicio: solo OFs cuya fecha de inicio cae dentro del período.\n'
            'Por solapamiento: toda OF activa durante el período (puede aparecer en varios).\n'
            'Proporcional: distribuye las cantidades según el tiempo que solapa el período; '
            'el producido usa los movimientos reales de stock con fecha en el período.')

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
        string='Umbral amarillo (días)', default=30,
        help='Cobertura menor a este valor se muestra en amarillo (aviso). '
             'Si la unidad es meses, se convierte internamente a días (× 30).'
    )

    forecast_coverage_critical_days = fields.Integer(
        string='Umbral rojo (días)', default=15,
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
        string='Umbral amarillo (días)', default=90,
        help='Rotación mayor a este valor → amarillo.'
    )
    stock_break_rotation_critical_days = fields.Integer(
        string='Umbral rojo (días)', default=180,
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
        string='Período de análisis (meses)', default=3,
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
        help='Variación de precio aceptable: |desviación| ≤ este % respecto al costo estándar se muestra en verde.')
    sup_price_var_yellow_pct = fields.Float( string='Var. precio — amarillo (|%| ≤)', default=10.0,
        help='Variación de precio tolerable: entre el umbral verde y este % se muestra en amarillo; por encima en rojo.')
    supplier_price_var_method = fields.Selection([
        ('standard',   'Costo estándar del producto'),
        ('pricelist',  'Lista de precio del proveedor'),
    ], string='Referencia para variación de precio', default='standard',
       help='Precio de referencia para calcular la variación en el análisis de proveedores.\n'
            'Costo estándar: compara precio OC vs. standard_price del producto.\n'
            'Lista de precio del proveedor: compara precio OC vs. precio en product.supplierinfo. '
            'Si el proveedor no tiene precio configurado para ese producto, queda sin variación.')

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
    ], string='Unidad', default='weeks',
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
            'ABC por volumen: Pareto por importe total de OCs del último año '
            '(primero 20% = A, 50% = B, 80% = C, 95% = D, resto = E).\n'
            'ABC por frecuencia: igual que volumen pero por cantidad de OCs.\n'
            'ABC por RFM: scoring Recencia + Frecuencia + Monetario (1-3 pts c/u); '
            'suma 8-9 = A, 6-7 = B, 4-5 = C, 3 = D, < 3 = E.\n'
            'ABC por % de entrega a tiempo: Pareto por % de recepciones completadas '
            'antes o en la fecha planificada. Mayor % = mejor categoría.\n'
            'ABC por variación de precio: Ranking por percentil por |variación de precio vs. el precio anterior '
            'pagado del mismo producto al mismo proveedor| (tendencia de precio, no usa costo estándar). '
            'Menor variación = mejor categoría.\n'
            'ABC por calidad — diferencia de cantidad: Pareto por % de movimientos de recepción '
            'donde la cantidad recibida coincide exactamente con la pedida.\n'
            'ABC por calidad — devoluciones: Ranking por percentil por cantidad de devoluciones al proveedor. '
            'Menos devoluciones = mejor categoría.\n'
            'ABC por calidad — combinado: promedio de % entrega a tiempo y % sin diferencia de cantidad.')
    supplier_cat_cron_number = fields.Integer(string='Cada', default=1,
        help='Número de unidades de tiempo entre cada recálculo automático de las categorías de proveedor.')
    supplier_cat_cron_type   = fields.Selection([
        ('days', 'Días'), ('weeks', 'Semanas'), ('months', 'Meses'),
    ], string='Unidad', default='weeks',
       help='Unidad de tiempo para el intervalo de recálculo automático de categorías de proveedor.')
    supplier_cat_auto_cron = fields.Boolean(
        string='Actualización automática', default=False,
        help='Recalcula las categorías de proveedor automáticamente según el intervalo configurado.')
    supplier_cat_lookback_months = fields.Integer(
        string='Período de análisis (meses)', default=12,
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
    ], string='Unidad', default='weeks',
       help='Unidad de tiempo para el intervalo de recálculo automático de categorías de cliente.')
    customer_cat_auto_cron = fields.Boolean(
        string='Actualización automática', default=False,
        help='Recalcula las categorías de cliente automáticamente según el intervalo configurado.')
    customer_cat_lookback_months = fields.Integer(
        string='Período de análisis (meses)', default=12,
        help='Cantidad de meses de historial que se consideran al calcular las categorías de cliente. '
             'Afecta al botón "Calcular ahora" y al cron automático.')

    # ── Análisis de clientes ─────────────────────────────────────────────────
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
    customer_analysis_delivery_warn_pct = fields.Integer(
        string='% entrega — umbral amarillo', default=80,
        help='Por debajo de este porcentaje de entrega (qty entregada / qty pedida), '
             'la celda se muestra en amarillo en el análisis de clientes.')
    customer_analysis_delivery_crit_pct = fields.Integer(
        string='% entrega — umbral rojo', default=60,
        help='Por debajo de este porcentaje de entrega (qty entregada / qty pedida), '
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
    customer_analysis_default_period = fields.Selection([
        ('month',   'Mes actual'),
        ('quarter', 'Trimestre actual'),
        ('year',    'Año actual'),
    ], string='Período por defecto', default='quarter',
       help='Rango de fechas preseleccionado al abrir el análisis de clientes.')
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
        """Retorna la configuración de la empresa actual; None si no existe."""
        return self.search([('company_id', '=', self.env.company.id)], limit=1)

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

    def _sync_scheduling_group(self, enabled):
        """Activa/desactiva los menús y el grupo de scheduling según el toggle.

        Usa SQL directo en ir_ui_menu para garantizar que el cambio llegue a la
        base de datos incluso si env.ref() falla por caché o estado del registry.
        Invalida el caché ORM del modelo después del UPDATE para que la sesión
        actual no devuelva datos obsoletos.

        En entornos multi-empresa, solo oculta los menús si ninguna otra empresa
        tiene scheduling activo, para evitar afectar a usuarios de otras empresas.
        """
        if not enabled:
            # sudo(): necesario para verificar otros registros de config sin importar el usuario activo
            other_enabled = self.env['mrp.reschedule.config'].sudo().search([
                ('id', 'not in', self.ids),
                ('enable_scheduling', '=', True),
            ], limit=1)
            if other_enabled:
                return
        cr = self.env.cr
        menu_xmlids = [
            ('odoo_mrp_planner', 'mrp_reschedule_menu_plans'),
            ('odoo_mrp_planner', 'mrp_reschedule_menu_request'),
        ]
        for module, name in menu_xmlids:
            cr.execute(
                "SELECT res_id FROM ir_model_data WHERE module=%s AND name=%s LIMIT 1",
                (module, name),
            )
            row = cr.fetchone()
            if row:
                cr.execute("UPDATE ir_ui_menu SET active=%s WHERE id=%s", (enabled, row[0]))
        self.env['ir.ui.menu'].invalidate_model(['active'])

        group = self.env.ref('odoo_mrp_planner.group_scheduling', raise_if_not_found=False)
        if not group:
            return
        if not enabled:
            # sudo(): ir.groups pertenece al sistema; el admin del módulo no tiene acceso directo
            group.sudo().write({'users': [(5,)]})

    def write(self, vals):
        """
        Guarda los cambios y propaga la configuración a ir.config_parameter y a los ir.cron del módulo.

        Cuando se modifican wc_fallback o priority los replica en ir.config_parameter
        para que otros modelos puedan leerlos sin cargar el singleton.
        Cuando se modifican campos de intervalo de cron (cron_interval_*, sale_cat_*,
        supplier_cat_*, customer_cat_*) actualiza el registro de ir.cron correspondiente
        vía sudo() porque el usuario administrador del módulo no tiene acceso directo a ir.cron.

        :param vals: dict con los campos a actualizar.
        :returns: bool — resultado del super().write().
        """
        if not self.env.user.has_group('odoo_mrp_planner.group_admin'):
            raise AccessError(_("Solo los administradores pueden modificar la configuración"))
        res = super().write(vals)
        if 'enable_scheduling' in vals:
            self._sync_scheduling_group(vals['enable_scheduling'])
        sp = self.env['ir.config_parameter'].sudo()
        company_id = self.env.company.id
        if 'wc_fallback' in vals:
            sp.set_param(f'mrp_reschedule.wc_fallback.{company_id}', vals['wc_fallback'])
        if 'priority' in vals:
            sp.set_param(f'mrp_reschedule.priority.{company_id}', vals['priority'])
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
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """
        Crea el registro de configuración aplicando la restricción singleton.

        Lanza UserError si ya existe un registro, garantizando que solo haya una
        instancia del planificador. Tras la creación sincroniza wc_fallback, priority
        y el cron de detección de retrasos con los valores del nuevo registro.

        :param vals_list: list[dict] — lista de valores para crear.
        :returns: mrp.reschedule.config — recordset con los registros creados.
        :raises UserError: si ya existe una configuración en la base de datos.
        """
        if not self.env.user.has_group('odoo_mrp_planner.group_admin'):
            raise AccessError(_("Solo los administradores pueden crear la configuración"))
        # FIX [FASE-2]: prevenir múltiples singletons — solo puede existir un registro
        if self.search_count([]) > 0:
            raise UserError(_(
                'Solo puede existir una configuración del planificador. '
                'Editá el registro existente en lugar de crear uno nuevo.'
            ))
        records = super().create(vals_list)
        for rec in records:
            if rec.enable_scheduling:
                rec._sync_scheduling_group(True)
        sp = self.env['ir.config_parameter'].sudo()
        for rec in records:
            sp.set_param(f'mrp_reschedule.wc_fallback.{rec.company_id.id}', rec.wc_fallback)
            sp.set_param(f'mrp_reschedule.priority.{rec.company_id.id}', rec.priority)
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
        """
        Abre el formulario de configuración del planificador (singleton).

        Busca el único registro existente y retorna una acción de ventana apuntando
        a su formulario con paginador oculto (no_pager) para reforzar la experiencia
        de singleton. Si no existe ningún registro, abre el formulario en modo creación.

        :returns: dict — acción ir.actions.act_window con res_id del singleton o
                  False si aún no fue creado.
        """
        if not self.env.user.has_group('odoo_mrp_planner.group_admin'):
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
