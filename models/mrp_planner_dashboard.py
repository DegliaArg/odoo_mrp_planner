"""
Módulo: mrp_planner_dashboard.py
Modelo: mrp.planner.dashboard

Panel de control transitorio del planificador de producción MRP.

Responsabilidades:
- Agregar y exponer contadores de alertas, OFs, OCs y programaciones para el dashboard.
- Calcular permisos de visibilidad por grupo de usuario.
- Proveer acciones de apertura para las distintas vistas del panel (producción, ventas, compras).
- Ofrecer accesos rápidos de navegación hacia alertas, OFs, OCs y programaciones filtradas.
- Exponer ubicaciones internas para el widget de quiebres de stock.

Relacionado con:
- mrp.reschedule.alert: fuente principal de alertas críticas y warnings del panel.
- mrp.production: OFs activas, atrasadas y con reprogramación pendiente.
- mrp.production.request: programaciones confirmadas y calculadas.
- purchase.order: OCs en borrador, por aprobar, activas y vencidas.
- mrp.reschedule.config: configuración de umbrales (p. ej. días críticos para OCs).
- mrp_schedule_mixin.no_subcontract_domain: helper para excluir OFs de subcontratación.
"""
import logging
import pytz
from datetime import datetime

from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

_logger = logging.getLogger(__name__)


class MrpPlannerDashboard(models.TransientModel):
    _name = 'mrp.planner.dashboard'
    _description = 'Panel del planificador de producción'

    name = fields.Char(default='Panel del Planificador', help='Nombre descriptivo del panel (solo uso interno de la vista).')

    # ── Alertas — contadores ─────────────────────────────────────────────────

    alert_total           = fields.Integer(compute='_compute_alert_stats', help='Total de alertas activas (sin resolver), excluyendo OFs de subcontratación.')
    alert_critical        = fields.Integer(compute='_compute_alert_stats', help='Alertas activas con severidad crítica.')
    alert_warning         = fields.Integer(compute='_compute_alert_stats', help='Alertas activas con severidad advertencia.')
    alert_mo_delayed      = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OF atrasada (mo_delayed).')
    alert_mo_upcoming     = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OF próxima a vencer (mo_upcoming).')
    alert_po_delayed      = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OC atrasada (po_delayed).')
    alert_po_upcoming     = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OC próxima a vencer (po_upcoming).')
    alert_po_cancelled    = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OC cancelada (po_cancelled).')
    alert_receipt_delayed = fields.Integer(compute='_compute_alert_stats', help='Alertas de recepción atrasada vinculadas a una OC (no devoluciones).')
    alert_qty_mismatch    = fields.Integer(compute='_compute_alert_stats', help='Alertas de discrepancia de cantidad entre OF y recepción (qty_mismatch).')
    alert_mo_cancelled    = fields.Integer(compute='_compute_alert_stats', help='Alertas de tipo OF cancelada (mo_cancelled).')

    # ── Permisos de usuario ──────────────────────────────────────────────────

    can_see_alerts       = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ver el panel de alertas (producción o compras).')
    can_see_mo           = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ver el panel de órdenes de fabricación.')
    can_see_po           = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ver el panel de órdenes de compra.')
    can_see_stock_breaks = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ver el widget de quiebres de stock.')
    can_see_forecast     = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ver el panel de forecast de ventas.')
    can_schedule         = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede crear programaciones de producción.')
    can_reschedule       = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede ejecutar reprogramaciones en cascada.')
    can_edit_forecast    = fields.Boolean(compute='_compute_user_permissions', help='True si el usuario puede editar datos de forecast de ventas.')

    # ── Alertas — lista inline ───────────────────────────────────────────────

    urgent_alert_ids = fields.Many2many(
        'mrp.reschedule.alert',
        compute='_compute_inline_alerts',
        string='Alertas críticas',
        help='Últimas 8 alertas críticas sin resolver, ordenadas por ID descendente para el widget inline del dashboard.',
    )

    # ── OFs — contadores ─────────────────────────────────────────────────────

    mo_total             = fields.Integer(compute='_compute_mo_stats', help='Total de OFs activas (excluye done, cancel, draft y subcontratación).')
    mo_in_progress       = fields.Integer(compute='_compute_mo_stats', help='OFs en estado "en progreso" o "por cerrar".')
    mo_done              = fields.Integer(compute='_compute_mo_stats', help='OFs completadas (estado done), excluyendo subcontratación.')
    mo_delayed           = fields.Integer(compute='_compute_mo_stats', help='OFs activas cuya fecha de finalización planificada ya pasó.')
    mo_reschedule_needed = fields.Integer(compute='_compute_mo_stats', help='OFs activas marcadas con la bandera x_reschedule_needed.')

    # ── OFs — listas inline ──────────────────────────────────────────────────

    delayed_mo_ids    = fields.Many2many('mrp.production', compute='_compute_inline_mos',
                                         string='OFs atrasadas',
                                         help='Hasta 4 OFs atrasadas ordenadas por fecha de finalización ascendente, para el widget inline del dashboard.')
    reschedule_mo_ids = fields.Many2many('mrp.production', compute='_compute_inline_mos',
                                         string='OFs para reprogramar',
                                         help='Hasta 4 OFs con reprogramación pendiente ordenadas por fecha de inicio, para el widget inline del dashboard.')

    # ── OCs — contadores ─────────────────────────────────────────────────────

    po_rfq              = fields.Integer(compute='_compute_po_stats', help='OCs en estado borrador o enviadas (solicitudes de cotización).')
    po_to_approve       = fields.Integer(compute='_compute_po_stats', help='OCs pendientes de aprobación por un segundo nivel de autorización.')
    po_total            = fields.Integer(compute='_compute_po_stats', help='Total de OCs aprobadas (purchase + done) no totalmente recibidas.')
    po_pending          = fields.Integer(compute='_compute_po_stats', help='OCs aprobadas cuya fecha planificada de entrega aún no venció.')
    po_overdue          = fields.Integer(compute='_compute_po_stats', help='OCs aprobadas cuya fecha planificada de entrega ya pasó.')
    po_overdue_critical = fields.Integer(compute='_compute_po_stats', help='OCs vencidas que superan el umbral de días críticos configurado en mrp.reschedule.config.')

    # ── OCs — listas inline ──────────────────────────────────────────────────

    rfq_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='Solicitudes de cotización',
        help='Hasta 4 solicitudes de cotización (draft/sent) ordenadas por fecha planificada, para el widget inline del panel de compras.',
    )
    to_approve_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='Por aprobar',
        help='Hasta 3 OCs en estado "por aprobar" ordenadas por fecha planificada, para el widget inline del panel de compras.',
    )
    overdue_po_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='OCs vencidas',
        help='Hasta 5 OCs aprobadas con fecha de entrega vencida y recepción incompleta, ordenadas por fecha planificada ascendente.',
    )

    # ── Programaciones — contadores ──────────────────────────────────────────

    request_active            = fields.Integer(compute='_compute_request_stats', help='Programaciones en estado confirmado (OFs ya generadas).')
    request_calculated        = fields.Integer(compute='_compute_request_stats', help='Programaciones en estado calculado (pendientes de confirmación).')
    request_reschedule_needed = fields.Integer(compute='_compute_request_stats', help='Programaciones confirmadas que tienen al menos una OF con reprogramación pendiente.')
    req_mos_total             = fields.Integer(compute='_compute_request_stats', help='Total de OFs vinculadas a programaciones confirmadas.')
    req_mos_delayed           = fields.Integer(compute='_compute_request_stats', help='OFs vinculadas a programaciones confirmadas que están atrasadas.')
    req_mos_done              = fields.Integer(compute='_compute_request_stats', help='OFs vinculadas a programaciones confirmadas que ya están completadas.')

    # ── Programaciones — lista inline ────────────────────────────────────────

    active_request_ids = fields.Many2many(
        'mrp.production.request',
        compute='_compute_inline_requests',
        string='Programaciones activas',
        help='Hasta 6 programaciones en estado calculado o confirmado, ordenadas por ID descendente para el widget inline del dashboard.',
    )

    # ── Cómputos ─────────────────────────────────────────────────────────────

    @api.depends()
    def _compute_alert_stats(self):
        """
        Calcula todos los contadores de alertas para cada registro del panel.

        Fórmula: búsquedas independientes sobre mrp.reschedule.alert filtrando por
        resolved=False y tipo/severidad. Las alertas de OFs de subcontratación se
        excluyen del conteo de producción; las alertas de OCs/recepciones se filtran
        sin dominio SBC para no ocultarlas.
        Depende de: mrp.reschedule.alert (resolved, severity, alert_type,
                    production_id, picking_id.purchase_id, picking_id.return_id).
        """
        Alert = self.env['mrp.reschedule.alert']
        base = [('resolved', '=', False)]
        sc_loc_ids = self.env['stock.location'].search(
            [('is_subcontracting_location', '=', True)]
        ).ids
        sc_mo_ids = self.env['mrp.production'].search(
            [('location_src_id', 'in', sc_loc_ids)]
        ).ids if sc_loc_ids else []
        # Incluir alertas sin OF (recepciones, OCs); excluir solo las de OFs SBC
        no_sc = ['|', ('production_id', '=', False),
                 ('production_id', 'not in', sc_mo_ids)] if sc_mo_ids else []
        for rec in self:
            rec.alert_total           = Alert.search_count(base + no_sc)
            rec.alert_critical        = Alert.search_count(base + no_sc + [('severity', '=', 'critical')])
            rec.alert_warning         = Alert.search_count(base + no_sc + [('severity', '=', 'warning')])
            rec.alert_mo_delayed      = Alert.search_count(base + no_sc + [('alert_type', '=', 'mo_delayed')])
            rec.alert_mo_upcoming     = Alert.search_count(base + no_sc + [('alert_type', '=', 'mo_upcoming')])
            rec.alert_po_delayed      = Alert.search_count(base + [('alert_type', '=', 'po_delayed')])
            rec.alert_po_upcoming     = Alert.search_count(base + [('alert_type', '=', 'po_upcoming')])
            rec.alert_po_cancelled    = Alert.search_count(base + [('alert_type', '=', 'po_cancelled')])
            rec.alert_receipt_delayed = Alert.search_count(base + [
                ('alert_type', '=', 'receipt_delayed'),
                ('picking_id.purchase_id', '!=', False),
                ('picking_id.return_id', '=', False),
            ])
            rec.alert_qty_mismatch    = Alert.search_count(base + no_sc + [('alert_type', '=', 'qty_mismatch')])
            rec.alert_mo_cancelled    = Alert.search_count(base + no_sc + [('alert_type', '=', 'mo_cancelled')])

    @api.depends()
    def _compute_user_permissions(self):
        """
        Calcula los flags de visibilidad y acción para el usuario actual.

        Fórmula: evalúa los grupos del módulo (admin, prod_read, prod, purchase,
        sales_read, sales) y mapea combinaciones a cada permiso. Un usuario sin
        ningún grupo del módulo recibe acceso mínimo de lectura de producción.
        Depende de: grupos de seguridad del usuario (res.groups vía has_group).
        """
        u = self.env.user
        is_admin      = u.has_group('odoo_mrp_planner.group_admin') or u.has_group('base.group_system')
        has_prod_r    = u.has_group('odoo_mrp_planner.group_prod_read')
        has_prod      = u.has_group('odoo_mrp_planner.group_prod')
        has_pur       = u.has_group('odoo_mrp_planner.group_purchase')
        has_pur_admin = u.has_group('odoo_mrp_planner.group_purchase_admin')
        has_sales_r   = u.has_group('odoo_mrp_planner.group_sales_read')
        has_sales     = u.has_group('odoo_mrp_planner.group_sales')
        has_scheduling = u.has_group('odoo_mrp_planner.group_scheduling')
        # Sin ningún grupo del módulo → mínimo = prod lectura (no schedule, no compras, no ventas)
        no_groups = not any([is_admin, has_prod_r, has_prod, has_pur, has_pur_admin,
                             has_sales_r, has_sales, has_scheduling])
        can_prod  = is_admin or has_prod_r or has_prod or no_groups
        can_pur   = is_admin or has_pur or has_pur_admin
        can_sales = is_admin or has_sales_r or has_sales
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        scheduling_on = bool(cfg.enable_scheduling) if cfg else True
        for rec in self:
            rec.can_see_alerts       = can_prod or can_pur
            rec.can_see_mo           = can_prod
            rec.can_see_po           = can_pur
            rec.can_see_stock_breaks = can_prod
            rec.can_see_forecast     = can_sales
            rec.can_schedule         = scheduling_on and (is_admin or has_scheduling)
            rec.can_reschedule       = scheduling_on and (is_admin or has_scheduling)
            rec.can_edit_forecast    = is_admin or has_sales

    @api.depends()
    def _compute_inline_alerts(self):
        """
        Calcula la lista reducida de alertas críticas para el widget inline.

        Fórmula: últimas 8 alertas con severity='critical' y resolved=False,
        ordenadas por ID descendente (más recientes primero).
        Depende de: mrp.reschedule.alert (resolved, severity).
        """
        for rec in self:
            rec.urgent_alert_ids = self.env['mrp.reschedule.alert'].search(
                [('resolved', '=', False), ('severity', '=', 'critical')],
                order='id desc',
                limit=8,
            )

    @api.depends()
    def _compute_mo_stats(self):
        """
        Calcula los contadores de órdenes de fabricación para el panel.

        Fórmula: carga en memoria las OFs activas (no done/cancel/draft ni SBC) y
        aplica filtros en Python para in_progress y delayed; mo_done se obtiene con
        search_count para no cargar registros completos.
        Depende de: mrp.production (state, date_finished, x_reschedule_needed,
                    location_src_id.is_subcontracting_location).
        """
        MO = self.env['mrp.production']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        for rec in self:
            active = MO.search([('state', 'not in', ('done', 'cancel', 'draft'))] + no_sc)
            rec.mo_total             = len(active)
            rec.mo_in_progress       = len(active.filtered(lambda m: m.state in ('progress', 'to_close')))
            rec.mo_done              = MO.search_count([('state', '=', 'done')] + no_sc)
            rec.mo_delayed           = len(active.filtered(
                lambda m: m.date_finished and m.date_finished < now
            ))
            rec.mo_reschedule_needed = len(active.filtered(lambda m: m.x_reschedule_needed))

    @api.depends()
    def _compute_inline_mos(self):
        """
        Calcula las listas reducidas de OFs para los widgets inline del dashboard.

        Fórmula: delayed_mo_ids = hasta 4 OFs activas con date_finished < now,
        ordenadas por fecha asc; reschedule_mo_ids = hasta 4 OFs con
        x_reschedule_needed=True (no done/cancel), ordenadas por date_start asc.
        Depende de: mrp.production (state, date_finished, x_reschedule_needed,
                    location_src_id.is_subcontracting_location).
        """
        MO = self.env['mrp.production']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        for rec in self:
            rec.delayed_mo_ids = MO.search([
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc, order='date_finished asc', limit=4)
            rec.reschedule_mo_ids = MO.search([
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc, order='date_start asc', limit=4)

    @api.depends()
    def _compute_po_stats(self):
        """
        Calcula los contadores de órdenes de compra para el panel.

        Fórmula: po_rfq y po_to_approve vía search_count; las OCs activas
        (purchase/done con recepción incompleta) se cargan en memoria para
        filtrar pending y overdue en Python. po_overdue_critical usa el umbral
        alert_po_critical_days de mrp.reschedule.config (fallback: 5 días).
        Depende de: purchase.order (state, date_planned, receipt_status),
                    mrp.reschedule.config (alert_po_critical_days).
        """
        PO = self.env['purchase.order']
        now = fields.Datetime.now()
        for rec in self:
            rec.po_rfq        = PO.search_count([('state', 'in', ('draft', 'sent'))])
            rec.po_to_approve = PO.search_count([('state', '=', 'to approve')])
            # Approved (purchase + done), not fully received
            active = PO.search([('state', 'in', ('purchase', 'done')), ('receipt_status', '!=', 'full')])
            overdue = active.filtered(lambda p: p.date_planned and p.date_planned < now)
            rec.po_total            = len(active)
            rec.po_pending          = len(active.filtered(
                lambda p: not p.date_planned or p.date_planned >= now
            ))
            rec.po_overdue          = len(overdue)
            cfg = self.env['mrp.reschedule.config'].search([], limit=1)
            crit_days = cfg.alert_po_critical_days if cfg else 5
            rec.po_overdue_critical = len(overdue.filtered(
                lambda p: (now - p.date_planned).days >= crit_days
            ))

    @api.depends()
    def _compute_inline_pos(self):
        """
        Calcula las listas reducidas de OCs para los widgets inline del panel de compras.

        Fórmula: rfq_ids = hasta 4 RFQs ordenadas por fecha planificada;
        to_approve_ids = hasta 3 OCs por aprobar; overdue_po_ids = hasta 5 OCs
        vencidas con recepción incompleta, ordenadas por fecha planificada asc.
        Depende de: purchase.order (state, date_planned, receipt_status).
        """
        PO = self.env['purchase.order']
        now = fields.Datetime.now()
        for rec in self:
            rec.rfq_ids = PO.search([
                ('state', 'in', ('draft', 'sent')),
            ], order='date_planned asc', limit=4)
            rec.to_approve_ids = PO.search([
                ('state', '=', 'to approve'),
            ], order='date_planned asc', limit=3)
            rec.overdue_po_ids = PO.search([
                ('state', 'in', ('purchase', 'done')),
                ('date_planned', '<', now),
                ('receipt_status', 'not in', ['full']),
            ], order='date_planned asc', limit=5)

    @api.depends()
    def _compute_request_stats(self):
        """
        Calcula los contadores de programaciones de producción para el panel.

        Fórmula: confirmed y calculated se obtienen con search; las OFs asociadas
        se recopilan desde item_ids.production_id de las programaciones confirmadas
        y se filtran en Python para done y delayed. request_reschedule_needed
        cuenta las programaciones que tienen al menos un item con OF marcada.
        Depende de: mrp.production.request (state, item_ids),
                    mrp.production (state, date_finished, x_reschedule_needed).
        """
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()
        for rec in self:
            confirmed = Req.search([('state', '=', 'confirmed')])
            calculated = Req.search([('state', '=', 'calculated')])
            all_mos = confirmed.mapped('item_ids.production_id').filtered(lambda m: m.id)
            rec.request_active     = len(confirmed)
            rec.request_calculated = len(calculated)
            rec.request_reschedule_needed = len(confirmed.filtered(
                lambda r: any(
                    it.production_id and it.production_id.x_reschedule_needed
                    for it in r.item_ids
                )
            ))
            rec.req_mos_total   = len(all_mos)
            rec.req_mos_done    = len(all_mos.filtered(lambda m: m.state == 'done'))
            rec.req_mos_delayed = len(all_mos.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.date_finished and m.date_finished < now
            ))

    @api.depends()
    def _compute_inline_requests(self):
        """
        Calcula la lista reducida de programaciones activas para el widget inline.

        Fórmula: últimas 6 programaciones en estado calculado o confirmado,
        ordenadas por ID descendente (más recientes primero).
        Depende de: mrp.production.request (state).
        """
        for rec in self:
            rec.active_request_ids = self.env['mrp.production.request'].search([
                ('state', 'in', ('calculated', 'confirmed')),
            ], order='id desc', limit=6)

    # ── Apertura ─────────────────────────────────────────────────────────────

    @api.model
    def action_open(self):
        """
        Abre el panel principal del planificador MRP.

        Crea un registro transitorio nuevo y retorna una acción de ventana que
        lo muestra en la vista form principal (sin barra de control).

        :returns: dict — acción ir.actions.act_window apuntando a la vista
                  mrp_planner_dashboard_form con target='main'.
        """
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel del planificador'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_planner_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def action_open_ventas(self):
        """
        Abre el panel de forecast de ventas.

        Crea un registro transitorio nuevo y retorna una acción de ventana que
        lo muestra en la vista mrp_ventas_dashboard_form (sin barra de control).

        :returns: dict — acción ir.actions.act_window apuntando a la vista de ventas
                  con target='main'.
        """
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Forecast de Ventas'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_ventas_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def action_open_customer_analysis(self):
        """
        Abre el panel de análisis de clientes.
        """
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Análisis de Clientes'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_customer_analysis_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    @api.model
    def action_open_compras(self):
        """
        Abre el panel de compras.

        Crea un registro transitorio nuevo y retorna una acción de ventana que
        lo muestra en la vista mrp_compras_dashboard_form (sin barra de control).

        :returns: dict — acción ir.actions.act_window apuntando a la vista de compras
                  con target='main'.
        """
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel de Compras'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_compras_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh(self):
        """
        Recalcula las alertas de demoras y reabre el panel principal.

        Ejecuta el cron de verificación de demoras para actualizar mrp.reschedule.alert
        antes de reabrir la vista, garantizando datos frescos al usuario.

        :returns: dict — resultado de action_open() (acción de ventana del panel principal).
        """
        self.env['mrp.reschedule.alert']._cron_check_delays()
        return self.env['mrp.planner.dashboard'].action_open()

    def action_refresh_compras(self):
        """
        Recalcula las alertas de demoras y reabre el panel de compras.

        Idéntico a action_refresh pero redirige al panel de compras en lugar del principal.

        :returns: dict — resultado de action_open_compras() (acción de ventana del panel de compras).
        """
        self.env['mrp.reschedule.alert']._cron_check_delays()
        return self.env['mrp.planner.dashboard'].action_open_compras()

    # ── Accesos rápidos ──────────────────────────────────────────────────────

    def action_new_request(self):
        """
        Abre el formulario de creación de una nueva programación de producción.

        :returns: dict — acción ir.actions.act_window sobre mrp.production.request en modo form.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva programación'),
            'res_model': 'mrp.production.request',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new_plan(self):
        """
        Abre el formulario de creación de un nuevo plan de reprogramación.

        :returns: dict — acción ir.actions.act_window sobre mrp.reschedule.plan en modo form.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nuevo plan de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Navegación — alertas ─────────────────────────────────────────────────

    def _open_alerts(self, extra_domain=None):
        """Construye y retorna la acción de ventana de alertas con dominio base + filtro adicional."""
        # Alertas sin OF (recepciones, OCs) siempre se incluyen; solo se excluyen
        # las alertas de OFs de subcontratación (production_id != False y ubicación SBC)
        no_sc = ['|', ('production_id', '=', False),
                 ('production_id.location_src_id.is_subcontracting_location', '!=', True)]
        domain = [('resolved', '=', False)] + no_sc + (extra_domain or [])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_alerts(self):
        """Navega a la lista de todas las alertas activas (sin filtro de tipo/severidad)."""
        return self._open_alerts()

    def action_view_critical(self):
        """Navega a la lista de alertas activas con severidad crítica."""
        return self._open_alerts([('severity', '=', 'critical')])

    def action_view_warning(self):
        """Navega a la lista de alertas activas con severidad advertencia."""
        return self._open_alerts([('severity', '=', 'warning')])

    def action_view_mo_delayed_alerts(self):
        """Navega a las alertas de tipo 'OF atrasada' (mo_delayed)."""
        return self._open_alerts([('alert_type', '=', 'mo_delayed')])

    def action_view_po_delayed_alerts(self):
        """Navega a las alertas de tipo 'OC atrasada' (po_delayed)."""
        return self._open_alerts([('alert_type', '=', 'po_delayed')])

    def action_view_po_cancelled_alerts(self):
        """Navega a las alertas de tipo 'OC cancelada' (po_cancelled)."""
        return self._open_alerts([('alert_type', '=', 'po_cancelled')])

    def action_view_receipt_alerts(self):
        """Navega a las alertas de recepción atrasada vinculadas a OCs (excluye devoluciones)."""
        return self._open_alerts([
            ('alert_type', '=', 'receipt_delayed'),
            ('picking_id.purchase_id', '!=', False),
            ('picking_id.return_id', '=', False),
        ])

    def action_view_qty_mismatch_alerts(self):
        """Navega a las alertas de discrepancia de cantidad (qty_mismatch)."""
        return self._open_alerts([('alert_type', '=', 'qty_mismatch')])

    def action_view_mo_cancelled_alerts(self):
        """Navega a las alertas de tipo 'OF cancelada' (mo_cancelled)."""
        return self._open_alerts([('alert_type', '=', 'mo_cancelled')])

    def action_view_mo_upcoming_alerts(self):
        """Navega a las alertas de tipo 'OF próxima a vencer' (mo_upcoming)."""
        return self._open_alerts([('alert_type', '=', 'mo_upcoming')])

    def action_view_po_upcoming_alerts(self):
        """Navega a las alertas de tipo 'OC próxima a vencer' (po_upcoming)."""
        return self._open_alerts([('alert_type', '=', 'po_upcoming')])

    # ── Navegación — OFs ─────────────────────────────────────────────────────

    def _open_mos(self, domain, name):
        """Construye y retorna la acción de ventana de OFs con el dominio y nombre dados."""
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_mos(self):
        """Navega a todas las OFs activas (excluye done, cancel y subcontratación)."""
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', 'not in', ('done', 'cancel'))] + no_sc,
            _('OFs activas'),
        )

    def action_view_in_progress_mos(self):
        """Navega a las OFs en estado 'en progreso' o 'por cerrar'."""
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', 'in', ('progress', 'to_close'))] + no_sc,
            _('OFs en progreso'),
        )

    def action_view_delayed_mos(self):
        """Navega a las OFs activas cuya fecha de finalización planificada ya pasó."""
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc,
            _('OFs atrasadas'),
        )

    def action_view_reschedule_needed(self):
        """Navega a las OFs activas marcadas con reprogramación pendiente (x_reschedule_needed)."""
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc,
            _('OFs para reprogramar'),
        )

    def action_view_done_mos(self):
        """Navega a todas las OFs completadas (estado done), excluyendo subcontratación."""
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', '=', 'done')] + no_sc,
            _('OFs completadas'),
        )

    # ── Navegación — OCs ─────────────────────────────────────────────────────

    def action_view_rfqs(self):
        """Navega a la lista de solicitudes de cotización (OCs en estado draft o sent)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Solicitudes de cotización'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', 'in', ('draft', 'sent'))],
            'target': 'current',
        }

    def action_view_to_approve(self):
        """Navega a la lista de OCs pendientes de aprobación (estado 'to approve')."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Por aprobar'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'to approve')],
            'target': 'current',
        }

    def action_view_pending_pos(self):
        """Navega a las OCs aprobadas cuya fecha de entrega planificada aún no venció (o sin fecha)."""
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs a tiempo'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('purchase', 'done')),
                '|', ('date_planned', '>=', now), ('date_planned', '=', False),
            ],
            'target': 'current',
        }

    def action_view_overdue_pos(self):
        """Navega a las OCs aprobadas con fecha de entrega vencida y recepción incompleta."""
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs vencidas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', 'in', ('purchase', 'done')),
                ('date_planned', '<', now),
                ('receipt_status', 'not in', ['full']),
            ],
            'target': 'current',
        }

    def action_view_all_pos(self):
        """Navega a todas las OCs aprobadas (estado purchase o done), sin filtro de recepción."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de compra aprobadas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', 'in', ('purchase', 'done'))],
            'target': 'current',
        }

    # ── Navegación — Programaciones ──────────────────────────────────────────

    def action_view_active_requests(self):
        """Navega a las programaciones confirmadas (con OFs ya generadas)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con OFs creadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_calculated_requests(self):
        """Navega a las programaciones en estado calculado (pendientes de confirmación)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones calculadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'calculated')],
            'target': 'current',
        }

    def action_view_requests_reschedule(self):
        """Navega a las programaciones confirmadas que tienen al menos una OF con reprogramación pendiente."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con reprogramación pendiente'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'confirmed'),
                ('item_ids.production_id.x_reschedule_needed', '=', True),
            ],
            'target': 'current',
        }

    # ── Widget quiebres de stock ─────────────────────────────────────────────

    @api.model
    def get_internal_locations(self):
        """Devuelve todas las ubicaciones internas activas para el selector del widget."""
        locations = self.env['stock.location'].search(
            [('usage', '=', 'internal'), ('active', '=', True)],
            order='complete_name',
        )
        return [{'id': l.id, 'name': l.complete_name} for l in locations]

