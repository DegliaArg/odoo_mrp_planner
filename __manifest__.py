{
    'name': 'Planificador de producción',
    'version': '18.0.46.0.0',
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
    """,
    'author': 'Deglia',
    'website': 'https://www.deglia.xyz',
    'license': 'OPL-1',
    'currency': 'USD',
    'category': 'Manufacturing',
    'depends': ['mrp', 'mrp_workorder', 'purchase', 'stock', 'mail', 'sale'],
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
            'odoo_mrp_planner/static/src/css/dashboard_kpi_tooltip.css',
            'odoo_mrp_planner/static/src/js/column_manager.js',
            'odoo_mrp_planner/static/src/js/planner_search_bar.js',
            'odoo_mrp_planner/static/src/xml/planner_search_bar.xml',
            'odoo_mrp_planner/static/src/js/mo_list_widget.js',
            'odoo_mrp_planner/static/src/xml/mo_list_widget.xml',
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
            'odoo_mrp_planner/static/src/js/forecast_widget.js',
            'odoo_mrp_planner/static/src/xml/forecast_widget.xml',
            'odoo_mrp_planner/static/src/js/supplier_analysis_widget.js',
            'odoo_mrp_planner/static/src/xml/supplier_analysis_widget.xml',
            'odoo_mrp_planner/static/src/js/sales_chart_widget.js',
            'odoo_mrp_planner/static/src/xml/sales_chart_widget.xml',
            'odoo_mrp_planner/static/src/js/customer_analysis_widget.js',
            'odoo_mrp_planner/static/src/xml/customer_analysis_widget.xml',
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
