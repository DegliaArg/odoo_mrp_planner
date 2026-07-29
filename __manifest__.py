{
    'name': 'Planificador de producción',
    'version': '18.0.3.4.3',
    'summary': 'Planificación, control y alertas de producción en tiempo real',
    'description': """
Panel de control centralizado para la gestión operativa de producción en Odoo 18.

Planificación desde demanda
- Expansión automática de BOM con rutas, lead times y stock disponible.
- Detección de faltantes y reabastecimiento automático (min/max).
- Creación de OFs desde una solicitud de programación.

Reprogramación en cascada
- Recalcula fechas de OFs encadenadas respetando el calendario laboral.
- Soporte multi-WC con prioridad configurable: cronológico, SPT o manual.
- Planes persistentes con historial, Gantt y auditoría completa.

Alertas proactivas
- Detección automática de OFs atrasadas, OFs por vencer, OCs vencidas,
  OCs por vencer, recepciones demoradas y desvíos de cantidad.
- Severidad configurable: avisos y críticas con umbrales independientes.
- Resolución reactiva al cerrar OFs, OCs o recepciones.

Panel en tiempo real
- KPIs de OFs, OCs, centros de trabajo y quiebres de stock.
- Widgets interactivos con filtros, paginación y drill-down.
- Permisos por usuario: secciones visibles y acciones habilitadas.

Análisis de proveedores y clientes
- Scorecard de cumplimiento por proveedor: % a tiempo, lead time real, variación de precio
  (referencia configurable: costo estándar, lista de proveedor o precio anterior pagado).
- Clasificación A–E automática de proveedores por volumen, frecuencia, RFM,
  % entregas a tiempo, variación de precio, exactitud de cantidad, devoluciones
  o calidad combinada; y de clientes por volumen, frecuencia o RFM.
- Panel de ventas: gráfico de productos más vendidos y análisis de clientes con
  tasas de cumplimiento y física, ABC del período y segmentos de frecuencia.

Forecast
- Tabla mensual comparativa: forecast, OFs planificadas, entregas y stock.
- Métricas de precisión configurables: Simple, MAPE, WAPE, WMAPE y Sesgo.
- Exportación a Excel y edición directa de valores en celda.
    """,
    'author': 'Deglia',
    'website': 'https://deglia.xyz',
    'license': 'OPL-1',
    'category': 'Manufacturing',
    'depends': ['mrp', 'mrp_subcontracting', 'purchase', 'stock', 'mail', 'sale'],
    'data': [
        'security/groups.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/mrp_planner_dashboard_views.xml',
        'views/mrp_reschedule_alert_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/mrp_reschedule_plan_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_planner_detail_dashboard_views.xml',
        'views/mrp_forecast_line_views.xml',
        'views/res_users_views.xml',
        'wizard/mrp_production_request_views.xml',
        'wizard/mrp_forecast_import_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_planner/static/src/css/reschedule_gantt.css',
            'odoo_mrp_planner/static/src/js/column_manager.js',
            'odoo_mrp_planner/static/src/js/filter_persistence.js',
            'odoo_mrp_planner/static/src/js/planner_search_bar.js',
            'odoo_mrp_planner/static/src/xml/planner_search_bar.xml',
            'odoo_mrp_planner/static/src/js/po_dashboard_widget.js',
            'odoo_mrp_planner/static/src/xml/po_dashboard_widget.xml',
            'odoo_mrp_planner/static/src/js/alert_kpi_widget.js',
            'odoo_mrp_planner/static/src/xml/alert_kpi_widget.xml',
            'odoo_mrp_planner/static/src/js/mo_dashboard_widget.js',
            'odoo_mrp_planner/static/src/xml/mo_dashboard_widget.xml',
            'odoo_mrp_planner/static/src/js/stock_break_widget.js',
            'odoo_mrp_planner/static/src/xml/stock_break_widget.xml',
            'odoo_mrp_planner/static/src/js/wc_load_chart.js',
            'odoo_mrp_planner/static/src/xml/wc_load_chart.xml',
            'odoo_mrp_planner/static/src/js/forecast_formatters.js',
            'odoo_mrp_planner/static/src/js/forecast_tooltips.js',
            'odoo_mrp_planner/static/src/js/forecast_export.js',
            'odoo_mrp_planner/static/src/js/forecast_drilldown.js',
            'odoo_mrp_planner/static/src/js/forecast_filters.js',
            'odoo_mrp_planner/static/src/js/forecast_widget.js',
            'odoo_mrp_planner/static/src/xml/forecast_kpis.xml',
            'odoo_mrp_planner/static/src/xml/forecast_controls.xml',
            'odoo_mrp_planner/static/src/xml/forecast_widget.xml',
            'odoo_mrp_planner/static/src/js/supplier_analysis_widget.js',
            'odoo_mrp_planner/static/src/xml/supplier_analysis_widget.xml',
            'odoo_mrp_planner/static/src/js/sales_chart_widget.js',
            'odoo_mrp_planner/static/src/xml/sales_chart_widget.xml',
            'odoo_mrp_planner/static/src/js/customer_analysis_charts.js',
            'odoo_mrp_planner/static/src/js/customer_analysis_widget.js',
            'odoo_mrp_planner/static/src/xml/customer_analysis_widget.xml',
            'odoo_mrp_planner/static/src/xml/customer_analysis_row.xml',
            'odoo_mrp_planner/static/src/xml/customer_analysis_detail_panel.xml',
            'odoo_mrp_planner/static/src/js/sheet_selector_widget.js',
            'odoo_mrp_planner/static/src/xml/sheet_selector_widget.xml',
            'odoo_mrp_planner/static/src/js/scheduling_toggle_widget.js',
            'odoo_mrp_planner/static/src/xml/scheduling_toggle_widget.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
