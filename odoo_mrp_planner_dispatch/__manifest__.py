{
    'name': 'Planificador de producción — Despacho de entregas',
    'version': '18.0.1.4.0',
    'summary': 'Estado de despacho (sin despachar / despachado) en las órdenes de entrega',
    'description': """
Extensión de despacho del Planificador de producción.

Circuito de despacho sobre las órdenes de entrega (salidas):
- Estado "Sin despachar" / "Despachado" en cada remito de salida.
- Botón "Marcar despachado" disponible solo con el remito validado y para
  usuarios del grupo "Inventario: validación de despacho" (con validación
  también en el servidor).
- Reversa ("Volver a Sin despachar") reservada a administradores.
- Acción masiva en la lista para despachar varios remitos de una vez.
- Auditoría: fecha, usuario y mensaje en el chatter de cada despacho.

La instalación NO habilita la función: se activa por empresa desde los
Ajustes del planificador (Producción → Despacho de entregas). Al activarla,
las salidas ya validadas que nunca entraron al circuito se marcan como
despachadas. Al desinstalar el módulo, las órdenes de entrega quedan
exactamente como estaban (solo se pierde el historial de despacho).
    """,
    'author': 'Deglia',
    'website': 'https://deglia.xyz',
    'license': 'OPL-1',
    'category': 'Inventory',
    'depends': ['odoo_mrp_planner', 'stock'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'data/ir_cron.xml',
        'views/stock_picking_views.xml',
        'views/res_config_settings_views.xml',
        'views/mrp_inventory_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_mrp_planner_dispatch/static/src/js/inventory_dashboard_widget.js',
            'odoo_mrp_planner_dispatch/static/src/xml/inventory_dashboard_widget.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
