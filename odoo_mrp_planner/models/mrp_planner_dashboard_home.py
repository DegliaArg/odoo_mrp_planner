# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_home.py
Modelo: extensión de mrp.planner.dashboard

Pantalla de Inicio del módulo KPIs: un mosaico de accesos a los paneles que el
usuario puede ver, para que al entrar al módulo aterrice en una bienvenida
neutral en lugar de abrir directamente el panel de Producción (o el primero
que tenga permitido).

- action_open_home: abre la vista del home (mosaico).
- get_home_panels: devuelve, según los grupos del usuario, las tarjetas de
  paneles disponibles (nombre, descripción, ícono y método de apertura). El
  widget home_launcher llama a ese método de apertura y hace doAction con la
  acción resultante.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende vía _inherit.
- static/src/js/home_launcher_widget.js: consume get_home_panels.
"""
from odoo import models, api, _


class MrpPlannerDashboardHome(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    @api.model
    def action_open_home(self):
        """Abre la pantalla de Inicio del módulo (mosaico de paneles)."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inicio'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_home_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def get_home_panels(self):
        """Paneles visibles para el usuario actual, agrupados por sección.

        :returns: list[dict] con claves section, name, desc, icon y method
            (nombre del método @api.model que devuelve la acción del panel).
        """
        u = self.env.user
        is_admin = (u.has_group('odoo_mrp_planner.group_admin')
                    or u.has_group('base.group_system'))

        def can(*xmlids):
            return is_admin or any(u.has_group(g) for g in xmlids)

        panels = []
        if can('odoo_mrp_planner.group_management_read', 'odoo_mrp_planner.group_management'):
            panels.append({
                'section': 'Gerencia', 'name': 'Resumen de dirección',
                'desc': 'Demanda, facturado, despachos y producción del mes',
                'icon': 'fa-briefcase', 'method': 'action_open_gerencia',
            })
        if can('odoo_mrp_planner.group_prod_read', 'odoo_mrp_planner.group_prod'):
            panels.append({
                'section': 'Producción', 'name': 'Panel de producción',
                'desc': 'Alertas de OFs, carga de centros y quiebres de stock',
                'icon': 'fa-industry', 'method': 'action_open',
            })
            panels.append({
                'section': 'Producción', 'name': 'Análisis de producción',
                'desc': 'OFs, cumplimiento, eficiencia y evolución',
                'icon': 'fa-bar-chart', 'method': 'action_open_production_analysis',
            })
        if can('odoo_mrp_planner.group_purchase', 'odoo_mrp_planner.group_purchase_admin'):
            panels.append({
                'section': 'Compras', 'name': 'Panel de compras',
                'desc': 'Alertas de OCs, recepciones y análisis de proveedores',
                'icon': 'fa-shopping-cart', 'method': 'action_open_compras',
            })
            panels.append({
                'section': 'Compras', 'name': 'Análisis de compras',
                'desc': 'Seguimiento semanal de OFs del sector y sus OCs',
                'icon': 'fa-search', 'method': 'action_open_purchase_analysis',
            })
        if can('odoo_mrp_planner.group_sales_read', 'odoo_mrp_planner.group_sales'):
            panels.append({
                'section': 'Ventas', 'name': 'Panel de ventas',
                'desc': 'Forecast y productos más vendidos',
                'icon': 'fa-line-chart', 'method': 'action_open_ventas',
            })
            panels.append({
                'section': 'Ventas', 'name': 'Análisis de clientes',
                'desc': 'Cumplimiento, lead time, ABC y segmentos',
                'icon': 'fa-users', 'method': 'action_open_customer_analysis',
            })
        if can('odoo_mrp_planner.group_inventory_read', 'odoo_mrp_planner.group_inventory_admin'):
            panels.append({
                'section': 'Inventario', 'name': 'Panel de inventario',
                'desc': 'Tasa de entrega s/ disponible y análisis de movimientos',
                'icon': 'fa-cubes', 'method': 'action_open_inventory',
            })
        return panels
