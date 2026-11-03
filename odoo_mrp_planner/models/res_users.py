"""
Módulo: res_users.py
Modelo: extensión de res.users

Extiende el modelo de usuarios de Odoo para incorporar preferencias de acceso
y visualización del Planificador MRP.

Responsabilidades:
- Controlar si el usuario visualiza todos los depósitos o solo un subconjunto
- Almacenar la lista de depósitos permitidos cuando el acceso es restringido
- Almacenar qué secciones de cada panel son visibles para el usuario
- Validar que cada panel conserve al menos una sección visible al guardar

Relacionado con:
- stock.warehouse: depósitos que el usuario tiene permitido consultar en el
  Planificador MRP
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    """Extensión de res.users con preferencias de visibilidad del Planificador MRP."""

    _inherit = 'res.users'

    mrp_planner_all_warehouses = fields.Boolean(
        string='Todos los depósitos',
        default=True,
        help='Si está activo, el usuario puede ver datos de todos los depósitos en el Planificador MRP. '
             'Si está inactivo, solo verá los depósitos seleccionados abajo.',
    )

    mrp_planner_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'res_users_mrp_planner_wh_rel',
        'user_id',
        'warehouse_id',
        string='Depósitos permitidos',
        help='Depósitos que el usuario puede ver en el Planificador MRP '
             'cuando "Todos los depósitos" está desactivado.',
    )

    # ── Visibilidad de secciones por panel ───────────────────────────────────

    mrp_planner_show_prod_alerts = fields.Boolean(
        string='Alertas producción', default=True,
        help='Muestra la sección de alertas de OFs en el panel de producción.',
    )
    mrp_planner_show_prod_mos = fields.Boolean(
        string='OFs', default=True,
        help='Muestra el widget de órdenes de fabricación en el panel de producción.',
    )
    mrp_planner_show_prod_wc = fields.Boolean(
        string='Carga WC', default=True,
        help='Muestra el widget de carga de centros de trabajo en el panel de producción.',
    )
    mrp_planner_show_stock_breaks = fields.Boolean(
        string='Quiebres de stock', default=True,
        help='Muestra el widget de quiebres de stock en el panel de producción.',
    )
    mrp_planner_show_po_alerts = fields.Boolean(
        string='Alertas compras', default=True,
        help='Muestra la sección de alertas de OCs/recepciones en el panel de compras.',
    )
    mrp_planner_show_po_widget = fields.Boolean(
        string='OCs', default=True,
        help='Muestra el widget de órdenes de compra en el panel de compras.',
    )
    mrp_planner_show_supplier_analysis = fields.Boolean(
        string='Análisis proveedores', default=True,
        help='Muestra el widget de análisis de proveedores en el panel de compras.',
    )
    mrp_planner_show_sales_chart = fields.Boolean(
        string='Gráfico ventas', default=True,
        help='Muestra el widget de productos más vendidos en el panel de ventas.',
    )
    mrp_planner_show_forecast = fields.Boolean(
        string='Forecast', default=True,
        help='Muestra el widget de forecast en el panel de ventas.',
    )
    mrp_planner_show_customer_analysis = fields.Boolean(
        string='Análisis clientes', default=True,
        help='Muestra el widget de análisis de clientes.',
    )

    # ── Validación: al menos una sección por panel ───────────────────────────

    _PANEL_FIELDS = {
        'Producción': ['mrp_planner_show_prod_alerts', 'mrp_planner_show_prod_mos',
                       'mrp_planner_show_prod_wc', 'mrp_planner_show_stock_breaks'],
        'Compras':    ['mrp_planner_show_po_alerts', 'mrp_planner_show_po_widget',
                       'mrp_planner_show_supplier_analysis'],
        'Ventas':     ['mrp_planner_show_sales_chart', 'mrp_planner_show_forecast'],
        'Clientes':   ['mrp_planner_show_customer_analysis'],
    }

    @api.constrains(
        'mrp_planner_show_prod_alerts', 'mrp_planner_show_prod_mos',
        'mrp_planner_show_prod_wc', 'mrp_planner_show_stock_breaks',
        'mrp_planner_show_po_alerts', 'mrp_planner_show_po_widget',
        'mrp_planner_show_supplier_analysis',
        'mrp_planner_show_sales_chart', 'mrp_planner_show_forecast',
        'mrp_planner_show_customer_analysis',
    )
    def _check_panel_has_at_least_one_section(self):
        for user in self:
            for panel, fields_list in self._PANEL_FIELDS.items():
                if not any(getattr(user, f) for f in fields_list):
                    raise ValidationError(
                        f'El panel "{panel}" no puede quedar sin secciones visibles. '
                        f'Habilitá al menos una sección antes de guardar.'
                    )

    # ── Sincronización de destinatarios del Resumen diario de Gerencia ───────

    @api.model
    def _mgmt_gerencia_groups(self):
        """Grupos de Gerencia (Lectura + Administrador)."""
        groups = self.env['res.groups']
        for xmlid in ('odoo_mrp_planner.group_management_read',
                      'odoo_mrp_planner.group_management'):
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                groups |= grp
        return groups

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        grp = self._mgmt_gerencia_groups()
        if grp:
            new_members = users.filtered(lambda u: u.groups_id & grp)
            if new_members:
                self.env['mrp.reschedule.config']._mgmt_report_add_partners(
                    new_members.partner_id)
        return users

    def write(self, vals):
        # Foto de la pertenencia a Gerencia ANTES del write, para detectar altas/bajas.
        track_groups = 'groups_id' in vals
        grp = self._mgmt_gerencia_groups() if track_groups else self.env['res.groups']
        before = {u.id: bool(u.groups_id & grp) for u in self} if (track_groups and grp) else {}

        res = super().write(vals)

        if 'mrp_planner_all_warehouses' in vals or 'mrp_planner_warehouse_ids' in vals:
            # _get_allowed_wh_ids (mrp.planner.dashboard) está cacheado con ormcache:
            # sin esta invalidación el usuario seguiría viendo los depósitos viejos
            # hasta el próximo reinicio del registry.
            self.env.registry.clear_cache()

        # Alta/baja en los grupos de Gerencia → sincroniza los destinatarios del PDF.
        if track_groups and grp:
            Config = self.env['mrp.reschedule.config']
            added = self.browse([u.id for u in self
                                 if (u.groups_id & grp) and not before.get(u.id)])
            removed = self.browse([u.id for u in self
                                   if not (u.groups_id & grp) and before.get(u.id)])
            if added:
                Config._mgmt_report_add_partners(added.partner_id)
            if removed:
                Config._mgmt_report_remove_partners(removed.partner_id)
        return res
