{
    'name': 'Planificador de producción',
    'version': '18.0.38.0.0',
    'summary': 'Planificación y reprogramación inteligente de órdenes de fabricación',
    'description': """
Planificador de producción para Odoo 18 con programación desde demanda,
reprogramación en cascada y sistema de alertas proactivo.

Características:
- Nueva programación desde demanda: expansión de BOM, rutas, lead times y stock.
- Reprogramación en cascada multi-WC con algoritmo calendario-aware.
- Sistema de alertas: OF atrasadas, OCs vencidas, recepciones demoradas.
- Detección automática de desvíos con cron diario.
- Triggers en OCs y recepciones para marcar MOs afectadas.
- Planes persistentes con historial, Gantt y auditoría completa.
- Prioridad configurable: cronológico / más cortas primero / manual.
    """,
    'author': 'Deglia',
    'website': 'https://www.deglia.xyz',
    'license': 'OPL-1',
    'currency': 'USD',
    'category': 'Manufacturing',
    'depends': ['mrp', 'mrp_workorder', 'purchase', 'stock', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/mrp_reschedule_alert_views.xml',
        'views/res_config_settings_views.xml',
        'views/mrp_planner_dashboard_views.xml',
        'views/mrp_reschedule_plan_views.xml',
        'views/mrp_production_views.xml',
        'views/mrp_planner_detail_dashboard_views.xml',
        'views/purchase_order_views.xml',
        'wizard/mrp_production_request_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_reschedule/static/src/css/reschedule_gantt.css',
            'odoo_mrp_reschedule/static/src/js/wc_load_chart.js',
            'odoo_mrp_reschedule/static/src/xml/wc_load_chart.xml',
            'odoo_mrp_reschedule/static/src/js/mo_list_widget.js',
            'odoo_mrp_reschedule/static/src/xml/mo_list_widget.xml',
            'odoo_mrp_reschedule/static/src/js/po_dashboard_widget.js',
            'odoo_mrp_reschedule/static/src/xml/po_dashboard_widget.xml',
            'odoo_mrp_reschedule/static/src/js/mo_dashboard_widget.js',
            'odoo_mrp_reschedule/static/src/xml/mo_dashboard_widget.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
