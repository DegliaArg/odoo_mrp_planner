"""Post-migración 18.0.13.17.0.

Se dejó de llamar "Planificador" a este módulo (son tableros/KPIs; "Planificador"
queda para odoo_mrp_planner_scheduling). La categoría de permisos y el prefijo de
crons/acciones pasan a "KPIs". Los crons y las acciones de servidor de categorías
son noupdate="1", así que el upgrade NO renombra sus registros en bases existentes:
este script lo hace por ORM (maneja bien los campos traducibles).
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Categoría del módulo (por si una base la tuviera congelada con el nombre viejo).
    cat = env.ref('odoo_mrp_planner.module_category_mrp_planner', raise_if_not_found=False)
    if cat and cat.name != 'KPIs':
        cat.name = 'KPIs'

    # Crons y acciones de servidor con el prefijo viejo "Planificador: ".
    for model in ('ir.cron', 'ir.actions.server'):
        for rec in env[model].search([('name', 'like', 'Planificador:%')]):
            rec.name = rec.name.replace('Planificador:', 'KPIs:')
