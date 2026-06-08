{
    'name': 'MRP Reschedule Cascade',
    'version': '18.0.2.0.0',
    'summary': 'Reprogramación en cascada multi-WC de órdenes de fabricación',
    'description': """
Reprograma en cascada las órdenes de fabricación subsecuentes en los mismos
centros de trabajo, respetando el calendario laboral de cada WC y programando
WO a WO para MOs con operaciones encadenadas en múltiples WCs.

Características:
- Algoritmo multi-WC con anchors independientes por centro de trabajo.
- MOs en progreso tratadas como puntos fijos configurables.
- Prioridad configurable: cronológico / más cortas primero / manual.
- Detección semi-automática: botón sugerido al cancelar/completar MOs.
- Vínculo tipado OF madre (x_parent_mo_id) como alternativa al campo Origen.
- Gantt interactivo en el wizard con toggle antes/después.
- Advertencias para OCs ya confirmadas y MOs hijas con ajuste de calendario.
    """,
    'author': 'Deglia',
    'website': 'https://www.deglia.xyz',
    'license': 'OPL-1',
    'currency': 'USD',
    'category': 'Manufacturing',
    'depends': ['mrp', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'wizard/mrp_reschedule_wizard_views.xml',
        'views/mrp_production_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_reschedule/static/src/js/mrp_reschedule_gantt.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
