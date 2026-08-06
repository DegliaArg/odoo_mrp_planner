"""
Módulo: mrp_reschedule_config_categories.py
Modelo: extensión de mrp.reschedule.config

Configuración de las categorías A–E automáticas: de venta (product.template),
de proveedor y de cliente (res.partner) — métodos de asignación, períodos de
análisis, umbrales por rotación/demanda/participación, umbrales Pareto
compartidos, parámetros del scoring RFM, crons de recálculo y el registro de
la última corrida de cada asignación.

Solo campos: la lógica de clasificación vive en mrp_partner_category.py
(que también extiende mrp.reschedule.config) y mrp_abc_helpers.py.
"""
from odoo import models, fields


class MrpRescheduleConfigCategories(models.Model):
    _inherit = 'mrp.reschedule.config'

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

    # ── Registro de la última corrida de cada asignación automática ──────────
    # (se muestran en Ajustes → General)
    sale_cat_last_run = fields.Datetime(string='Última asignación — categorías de venta', readonly=True)
    sale_cat_last_count = fields.Integer(string='Artículos actualizados (última corrida)', readonly=True)
    supplier_cat_last_run = fields.Datetime(string='Última asignación — categorías de proveedor', readonly=True)
    supplier_cat_last_count = fields.Integer(string='Proveedores actualizados (última corrida)', readonly=True)
    customer_cat_last_run = fields.Datetime(string='Última asignación — categorías de cliente', readonly=True)
    customer_cat_last_count = fields.Integer(string='Clientes actualizados (última corrida)', readonly=True)
