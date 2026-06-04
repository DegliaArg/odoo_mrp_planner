{
    'name': 'MRP Reschedule Cascade',
    'version': '18.0.1.0.0',
    'summary': 'Reprogramación en cascada de órdenes de fabricación por centro de trabajo',
    'description': """
Permite reprogramar en cascada todas las órdenes de fabricación subsecuentes
planificadas en el mismo centro de trabajo, junto con sus órdenes de compra
asociadas (subcontratación y componentes) y sus órdenes de fabricación hijas.

El desplazamiento se calcula respecto a la fecha de finalización planificada
de la orden de referencia. Se dispara manualmente mediante un botón en el
menú Acción de la vista lista de órdenes de fabricación.
    """,
    'author': 'Deglia',
    'website': 'https://www.deglia.xyz',
    'license': 'OPL-1',
    'currency': 'USD',
    'category': 'Manufacturing',
    'depends': ['mrp', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/mrp_reschedule_wizard_views.xml',
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
