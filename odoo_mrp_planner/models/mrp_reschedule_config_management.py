# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_reschedule_config_management.py
Modelo: extensión de mrp.reschedule.config

Campos de configuración de la sección Gerencia (Resumen diario): qué
tipos de operación (stock.picking.type) alimentan cada indicador de movimiento
del panel. Son IDs específicos de cada base, por eso se configuran acá en vez
de hardcodearlos.

Además, los campos del envío automático del Resumen diario por mail
(management_report_*): activación, hora, destinatarios (contactos + emails
sueltos), empresa a reportar y el umbral de "faltante prolongado" de la tasa
de servicio del PDF. El cron ir_cron_management los consume; el botón
"Enviar ahora" permite probar el mail al instante.

Relacionado con:
- mrp.reschedule.config: modelo base que este archivo extiende vía _inherit
  (mismo patrón que mrp_reschedule_config_forecast/categories/inventory).
- mrp_planner_dashboard_management.get_management_overview: consume estos campos.
- mrp_planner_dashboard_management._cron_send_management_report / _send_management_report:
  usan los campos management_report_* para generar y enviar el PDF.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MrpRescheduleConfigManagement(models.Model):
    _inherit = 'mrp.reschedule.config'

    management_dispatch_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_dispatch_rel', 'config_id', 'picking_type_id',
        string='Despachos — Tipos de operación',
        help='Tipos de operación que se cuentan como DESPACHOS del mes en el '
             'Resumen diario (transferencias validadas / estado Hecho). '
             'La cantidad se mide en piezas movidas.',
    )
    management_packing_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_packing_rel', 'config_id', 'picking_type_id',
        string='Embalajes — Tipos de operación',
        help='Tipos de operación que se cuentan como EMBALAJES pendientes en el '
             'Resumen diario (transferencias en estado Listo/Asignado). '
             'Es una foto del pendiente actual: muestra las piezas listas para embalar ahora.',
    )
    management_picking_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_picking_rel', 'config_id', 'picking_type_id',
        string='Picking — Tipos de operación',
        help='Tipos de operación que se cuentan como PICKING pendiente en el '
             'Resumen diario (transferencias en estado Listo/Asignado). '
             'Es una foto del pendiente actual: muestra las piezas listas para pickear ahora.',
    )
    management_production_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'mrp_resched_cfg_mgmt_prod_wh_rel', 'config_id', 'warehouse_id',
        string='Producido — Depósitos',
        help='Si se indican, el indicador de PRODUCIDO del Resumen diario solo '
             'cuenta OFs cuyo depósito (el del tipo de operación de la OF) esté '
             'entre estos. Vacío = todos los depósitos.',
    )

    # ── Envío automático del Resumen diario por mail ─────────────────────────

    management_report_enabled = fields.Boolean(
        string='Enviar Resumen diario por mail',
        help='Si está activo, un cron envía todos los días el Resumen diario de '
             'Gerencia en PDF a los destinatarios, a la hora configurada.',
    )
    management_report_hour = fields.Float(
        string='Hora de envío',
        default=8.0,
        help='Hora (del día, en la zona horaria del usuario que ejecuta el cron) '
             'a la que se envía el PDF. El cron corre cada hora y dispara el envío '
             'al llegar a esta hora. Ej.: 8.0 = 08:00, 18.5 = 18:30.',
    )
    management_report_company_ids = fields.Many2many(
        'res.company',
        'mrp_resched_cfg_mgmt_report_company_rel', 'config_id', 'company_id',
        string='Empresas a reportar',
        default=lambda self: self.env.company,
        help='Empresas cuyos indicadores se consolidan en el PDF (igual que el '
             'selector multiempresa del panel). Vacío = la empresa de esta '
             'configuración.',
    )
    management_report_partner_ids = fields.Many2many(
        'res.partner',
        'mrp_resched_cfg_mgmt_report_partner_rel', 'config_id', 'partner_id',
        string='Destinatarios (contactos)',
        help='Contactos que reciben el PDF. Se usa su email. El envío es un correo '
             'directo, así que llega por mail aunque el contacto sea un usuario con '
             'notificaciones en bandeja de Odoo.',
    )
    management_report_extra_emails = fields.Char(
        string='Destinatarios (emails sueltos)',
        help='Emails adicionales separados por coma, que no necesitan ser contactos '
             'de Odoo. Se combinan con los destinatarios de contactos.',
    )
    management_report_service_excuse_days = fields.Integer(
        string='Días de faltante para excusar la tasa de servicio',
        default=5,
        help='En la tasa de servicio del PDF, se descuentan del denominador '
             '(demanda) los pedidos pendientes que llevan MÁS de estos días sin '
             'disponibilidad de stock para hacer la recolección. Así la tasa no se '
             'penaliza por demanda que físicamente no se pudo pickear por quiebre.',
    )
    management_report_last_sent_date = fields.Date(
        string='Último envío automático',
        readonly=True,
        help='Fecha del último envío automático. Evita enviar dos veces el mismo '
             'día si el cron vuelve a correr. El botón "Enviar ahora" no la toca.',
    )

    def action_send_management_report_now(self):
        """Envía el PDF del Resumen diario de inmediato a los destinatarios
        configurados (para probar en producción). No chequea la hora ni la marca
        de último envío: es un disparo manual."""
        self.ensure_one()
        if not (self.management_report_partner_ids or self.management_report_extra_emails):
            raise UserError(_('Configurá al menos un destinatario (contacto o email) '
                              'antes de enviar el Resumen diario.'))
        self.env['mrp.planner.dashboard']._send_management_report(self, manual=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Resumen diario enviado'),
                'message': _('Se envió el PDF a los destinatarios configurados.'),
                'sticky': False,
            },
        }
