{
    'name': 'Planificador de producción — Inventario y despacho',
    'version': '18.0.2.1.0',
    'summary': 'Panel de Inventario (entregas pendientes y tasa s/ disponible) y circuito de despacho',
    'description': """
Extensión de inventario y despacho del Planificador de producción.

Panel de Inventario (menú Inventario, grupos Lectura/Administrador):
- KPIs de demanda pendiente de entrega por eslabón de la cadena
  (recolección/embalaje/salida a cliente), entregado del período y atraso
  promedio de entrega — todo con datos estándar de Odoo.
- Tasa de entrega s/ disponible: snapshots diarios de disponibilidad
  (cron configurable) con consolidado mensual congelado.
- Tabla operativa de salidas pendientes con export CSV.

Movimientos pendientes (submenú del menú Inventario):
- Recepciones y transferencias pendientes — el complemento del Panel de
  Inventario: compras por recibir, transferencias internas y tramos entre
  depósitos. KPIs dinámicos, composición por depósito y tabla con export.

Circuito de despacho sobre las órdenes de entrega (opcional):
- Estado "Sin despachar" / "Despachado" en los remitos de los tipos de
  operación elegidos en Ajustes.
- Botón "Marcar despachado" disponible solo con el remito validado y para
  usuarios del grupo "Inventario: validación de despacho" (con validación
  también en el servidor); acción masiva en la lista y en el panel.
- Reversa ("Volver a Sin despachar") reservada a administradores.
- Auditoría: fecha, usuario y mensaje en el chatter de cada despacho.

La instalación NO habilita el circuito: se activa por empresa desde los
Ajustes del planificador (pestaña Inventario). Al activarlo, las salidas ya
validadas que nunca entraron al circuito se marcan como despachadas. Al
desinstalar el módulo, las órdenes de entrega quedan exactamente como
estaban (solo se pierde el historial de despacho).
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
            'odoo_mrp_planner_dispatch/static/src/js/movements_dashboard_widget.js',
            'odoo_mrp_planner_dispatch/static/src/xml/movements_dashboard_widget.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
