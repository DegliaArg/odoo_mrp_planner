from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    planeacion = env.ref('odoo_mrp_planner.mrp_planeacion_menu', raise_if_not_found=False)
    if not planeacion:
        return
    for xmlid in ('mrp_reschedule_menu_request', 'mrp_reschedule_menu_plans'):
        menu = env.ref(f'odoo_mrp_planner_scheduling.{xmlid}', raise_if_not_found=False)
        if menu and menu.parent_id != planeacion:
            menu.parent_id = planeacion
    # Limpiar el flag noupdate para que futuros updates del módulo puedan modificar estos registros
    cr.execute("""
        UPDATE ir_model_data
        SET noupdate = false
        WHERE module = 'odoo_mrp_planner_scheduling'
          AND name IN ('mrp_reschedule_menu_request', 'mrp_reschedule_menu_plans')
    """)
