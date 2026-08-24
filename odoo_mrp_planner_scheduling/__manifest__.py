{
    'name': 'Planificador de producción — Programación y reprogramación',
    'version': '18.0.5.2.2',
    'summary': 'Programación desde demanda y reprogramación en cascada para el Planificador MRP',
    'description': """
Extensión de programación del Planificador de producción.

Planificación desde demanda
- Expansión automática de BOM con rutas, lead times y stock disponible.
- Detección de faltantes y reabastecimiento automático (min/max).
- Creación de OFs desde una solicitud de programación.

Reprogramación en cascada
- Recalcula fechas de OFs encadenadas respetando el calendario laboral.
- Soporte multi-WC con prioridad configurable: cronológico, SPT o manual.
- Planes persistentes con historial, Gantt y auditoría completa.
- Creación de planes desde las alertas del planificador.

La instalación NO habilita la función: se activa desde Ajustes del
planificador (Programación y reprogramación), donde también se controla
qué usuarios ven los menús, botones y KPIs asociados.
    """,
    'author': 'Deglia',
    'website': 'https://deglia.xyz',
    'license': 'OPL-1',
    'category': 'Manufacturing',
    'depends': ['odoo_mrp_planner'],
    'data': [
        'security/groups.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'views/mrp_production_views.xml',
        'views/mrp_reschedule_plan_views.xml',
        'views/mrp_reschedule_alert_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/mrp_planner_detail_dashboard_views.xml',
        'wizard/mrp_production_request_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_planner_scheduling/static/src/js/scheduling_toggle_widget.js',
            'odoo_mrp_planner_scheduling/static/src/xml/scheduling_toggle_widget.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
