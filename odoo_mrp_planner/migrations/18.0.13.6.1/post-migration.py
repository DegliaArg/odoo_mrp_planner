# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Post-migración 18.0.13.6.1: precarga los destinatarios del Resumen diario de
Gerencia con los contactos de los usuarios del grupo Gerencia (Lectura/Admin).

El campo management_report_partner_ids pasó a ser un único campo editable que
viene precargado con el grupo. Para las configuraciones ya existentes (creadas
antes de este cambio) el default no se aplica, así que se rellena acá sin pisar
los contactos que ya tuvieran.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    groups = env['res.groups']
    for xmlid in ('odoo_mrp_planner.group_management_read',
                  'odoo_mrp_planner.group_management'):
        grp = env.ref(xmlid, raise_if_not_found=False)
        if grp:
            groups |= grp
    partners = groups.users.partner_id
    if not partners:
        return
    for cfg in env['mrp.reschedule.config'].search([]):
        to_add = partners - cfg.management_report_partner_ids
        if to_add:
            cfg.management_report_partner_ids = [(4, p.id) for p in to_add]
