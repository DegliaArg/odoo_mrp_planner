{
    'name': 'Planificador de producción — Despacho de entregas',
    'version': '18.0.3.0.0',
    'summary': 'Circuito de despacho (sin despachar / despachado) sobre las órdenes de entrega',
    'description': """
Extensión de despacho del Planificador de producción.

Circuito de despacho sobre las órdenes de entrega, para los tipos de
operación elegidos en Ajustes:
- Estado "Sin despachar" / "Despachado" en cada remito de salida.
- Botón "Marcar despachado" disponible solo con el remito validado y para
  usuarios del grupo "Inventario: validación de despacho" (con validación
  también en el servidor); acción masiva en la lista de remitos y en la
  tabla del Panel de Inventario (etapa "Validado s/ despachar").
- Reversa ("Volver a Sin despachar") reservada a administradores.
- Auditoría: fecha, usuario y mensaje en el chatter de cada despacho.
- KPIs físicos del panel de Ventas (Entregas físicas / Tasa física).

Los paneles de Inventario y Movimientos viven en el módulo base
(odoo_mrp_planner) y funcionan sin este módulo: acá solo se agrega la capa
operativa de despacho.

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
        'views/stock_picking_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
