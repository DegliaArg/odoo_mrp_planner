"""
Migración a 18.0.6.0.0 — los paneles de Inventario y Movimientos se mudan de
odoo_mrp_planner_dispatch al módulo base.

Reasigna en ir_model_data la propiedad de todos los artefactos movidos
(modelos, campos, grupos, menús, vistas, acciones, cron, ACLs, reglas y
valores de selección) ANTES de que corra el upgrade de ambos módulos: si no,
la limpieza de datos huérfanos del módulo de despacho borraría los grupos ya
asignados a usuarios, el cron, los snapshots acumulados y los menús.

En bases donde el módulo de despacho nunca se instaló, los UPDATE no
encuentran filas y la migración es un no-op.
"""

# Artefactos con nombre exacto
MOVED_NAMES = [
    # Modelos nuevos del panel (sus campos van por patrón, abajo)
    'model_mrp_dispatch_stock_log',
    'model_mrp_planner_kpi_monthly',
    # Campos movidos de mrp.reschedule.config
    'field_mrp_reschedule_config__dispatch_stock_log_enabled',
    'field_mrp_reschedule_config__dispatch_snapshot_hour',
    'field_mrp_reschedule_config__dispatch_log_retention_months',
    'field_mrp_reschedule_config__dispatch_pending_cutoff_months',
    'field_mrp_reschedule_config__inventory_force_integer',
    # Campos movidos de stock.picking
    'field_stock_picking__x_qty_pieces',
    'field_stock_picking__x_qty_available_chain',
    'field_stock_picking__x_qty_blocked_chain',
    # Grupos
    'group_inventory_read',
    'group_inventory_admin',
    # Menús y acciones
    'mrp_inventario_menu',
    'mrp_inventario_panel_menu',
    'mrp_movimientos_menu',
    'action_mrp_inventory_dashboard_open',
    'action_mrp_movements_dashboard_open',
    # Vistas
    'mrp_inventory_dashboard_form',
    'mrp_movements_dashboard_form',
    'view_picking_list_planner_drill',
    'view_picking_list_planner_drill_pending',
    # Cron
    'ir_cron_dispatch_stock_snapshot',
    # ACLs
    'access_mrp_dispatch_stock_log_all',
    'access_mrp_dispatch_stock_log_admin',
    'access_mrp_planner_kpi_monthly_all',
    'access_mrp_planner_kpi_monthly_admin',
    'access_mrp_reschedule_config_inventory_admin',
    # Reglas multiempresa
    'rule_dispatch_stock_log_company',
    'rule_planner_kpi_monthly_company',
]

# Familias por patrón (campos/constraints de los modelos movidos y el valor
# de selección del registro de ejecuciones)
MOVED_PATTERNS = [
    'field_mrp_dispatch_stock_log__%',
    'field_mrp_planner_kpi_monthly__%',
    'constraint_mrp_planner_kpi_monthly_%',
    'selection__mrp_planner_run_log__process__dispatch_snapshot',
]


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET module = 'odoo_mrp_planner'
         WHERE module = 'odoo_mrp_planner_dispatch'
           AND name = ANY(%s)
    """, (MOVED_NAMES,))
    for pattern in MOVED_PATTERNS:
        cr.execute("""
            UPDATE ir_model_data
               SET module = 'odoo_mrp_planner'
             WHERE module = 'odoo_mrp_planner_dispatch'
               AND name LIKE %s
        """, (pattern,))
