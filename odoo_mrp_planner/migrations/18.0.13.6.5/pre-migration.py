# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Pre-migración 18.0.13.6.5: elimina la vista heredada
mrp_reschedule_config_form_view_management ANTES de cargar los XML del módulo.

Entre v13.6.0 y v13.6.4 se removieron del modelo mrp.reschedule.config varios
campos (management_report_group_recipients, management_report_excluded_partner_ids,
management_report_recipients_preview, management_report_service_excuse_days). La
versión de esa vista guardada en la base (de un build anterior que SÍ tenía los
campos) todavía los referencia.

La vista BASE (mrp_reschedule_config_form_view, en res_config_settings_views.xml)
se carga ANTES que esta vista heredada; al validarse combina el árbol con todas las
vistas heredadas que estén en la BD, incluida la versión vieja de ésta → la
validación falla con "el campo no existe" (ParseError) y revienta la carga del
registry ("Failed to load registry").

Borrando la vista heredada acá (pre-carga), la validación de la base pasa limpia y
el XML del módulo la recrea después, ya sin esos campos. Si no existe (instalación
nueva o ya migrada), no hace nada.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    view = env.ref(
        'odoo_mrp_planner.mrp_reschedule_config_form_view_management',
        raise_if_not_found=False)
    if view:
        view.unlink()
