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
- mrp.reschedule.config: determina si la programación está habilitada para
  validar la asignación del grupo group_scheduling
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    """Extensión de res.users con preferencias de visibilidad del Planificador MRP."""

    _inherit = 'res.users'

    mrp_scheduling_enabled = fields.Boolean(
        compute='_compute_mrp_scheduling_enabled',
        string='Programación MRP habilitada',
    )

    def _compute_mrp_scheduling_enabled(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        enabled = bool(cfg.enable_scheduling) if cfg else False
        for user in self:
            user.mrp_scheduling_enabled = enabled

    @api.constrains('groups_id')
    def _check_scheduling_group_assignment(self):
        scheduling_group = self.env.ref('odoo_mrp_planner.group_scheduling', raise_if_not_found=False)
        if not scheduling_group:
            return
        cfg = self.env['mrp.reschedule.config'].get_config()
        if not cfg or cfg.enable_scheduling:
            return
        for user in self:
            if scheduling_group in user.groups_id:
                raise ValidationError(
                    'No se puede asignar el permiso "Programación" porque la '
                    'programación está deshabilitada. Habilítela primero desde '
                    'Configuración → Planificador MRP → Programación y reprogramación.'
                )

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
