{
    'name': 'Planificador de producción — KPIs de cliente en CRM',
    'version': '18.0.1.3.0',
    'summary': 'Indicadores del cliente (Análisis de cliente) dentro del form de la oportunidad',
    'description': """
Extensión de CRM del Planificador de producción.

Agrega una pestaña "Análisis del cliente" al formulario de cada oportunidad
(crm.lead) que muestra los mismos indicadores que KPIs → Ventas → Análisis de
cliente, para el cliente del campo "Contacto" (partner_id):

- Resumen de KPIs (cards): pedidos, demanda, cumplimiento, monto, tasa de
  cumplimiento, precios promedio, lead time, puntualidad y días sin comprar.
- Detalle en sub-pestañas: evolución mensual, mix por categoría de venta y
  familia, lista de pedidos y top de artículos.
- Selector de período propio (presets 12 meses / año en curso).

NO recalcula nada: reúsa los métodos del módulo base
(get_customer_analysis_data y get_customer_detail de mrp.planner.dashboard).
El panel se carga al abrir la pestaña y respeta los permisos y Ajustes del
Análisis de clientes (grupo de Ventas). Multiempresa vía la empresa activa.
    """,
    'author': 'Deglia',
    'website': 'https://deglia.xyz',
    'license': 'OPL-1',
    'category': 'Sales/CRM',
    'depends': ['odoo_mrp_planner', 'crm'],
    'data': [
        'views/crm_lead_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_planner_crm/static/src/js/crm_customer_kpis_widget.js',
            'odoo_mrp_planner_crm/static/src/xml/crm_customer_kpis_widget.xml',
            'odoo_mrp_planner_crm/static/src/scss/crm_customer_kpis.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
