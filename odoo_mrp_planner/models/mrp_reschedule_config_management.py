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
import re

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
        string='Hora de envío (hora local)',
        default=8.0,
        help='Hora local del día (formato 24 h, HH:MM) a la que se envía el PDF; '
             'se interpreta en la zona horaria de la empresa de esta configuración '
             '(no en UTC ni en la del cron). Elegila en el selector de hora: p. ej. '
             '08:00 = 8 de la mañana, 18:30 = 6:30 de la tarde. Se respetan los '
             'minutos: el cron corre cada 15 min y dispara el envío dentro de los '
             '~20 min posteriores a la hora:minuto elegidos.',
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
        default=lambda self: self._management_report_group_users().partner_id,
        help='Contactos que reciben el PDF. Viene precargado con los contactos de los '
             'usuarios del grupo Gerencia (Lectura/Admin) y se mantiene al día cuando '
             'se agregan o quitan usuarios de esos grupos, pero es totalmente editable: '
             'sumá o sacá los contactos que quieras. El envío es un correo directo, así '
             'que llega por mail aunque el contacto sea un usuario con notificaciones en '
             'bandeja de Odoo.',
    )
    management_report_extra_emails = fields.Char(
        string='Emails sueltos (opcional)',
        help='Emails adicionales separados por coma que no son contactos de Odoo. '
             'Se suman a los destinatarios de arriba.',
    )
    management_report_last_sent_date = fields.Date(
        string='Último envío automático',
        readonly=True,
        help='Fecha del último envío automático. Evita enviar dos veces el mismo '
             'día si el cron vuelve a correr. El botón "Enviar ahora" no la toca.',
    )

    # ── Resolución de destinatarios ──────────────────────────────────────────

    def _management_report_group_users(self):
        """Usuarios de los grupos de Gerencia (Lectura + Administrador)."""
        groups = self.env['res.groups']
        for xmlid in ('odoo_mrp_planner.group_management_read',
                      'odoo_mrp_planner.group_management'):
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                groups |= grp
        return groups.users

    def _management_report_recipient_emails(self):
        """Set de emails a los que sale el PDF: emails de los contactos del campo
        de destinatarios + emails sueltos."""
        self.ensure_one()
        emails = {p.email.strip() for p in self.management_report_partner_ids if p.email}
        for raw in re.split(r'[;,\n]+', self.management_report_extra_emails or ''):
            raw = raw.strip()
            if raw:
                emails.add(raw)
        return emails

    @api.model
    def _mgmt_report_add_partners(self, partners):
        """Agrega contactos al campo de destinatarios de todas las configs (sin pisar
        los que ya estén). Lo usa el hook de res.users al sumar usuarios al grupo."""
        partners = partners.filtered(lambda p: p)
        if not partners:
            return
        for cfg in self.sudo().search([]):
            to_add = partners - cfg.management_report_partner_ids
            if to_add:
                cfg.management_report_partner_ids = [(4, p.id) for p in to_add]

    @api.model
    def _mgmt_report_remove_partners(self, partners):
        """Quita contactos del campo de destinatarios de todas las configs. Lo usa el
        hook de res.users al quitar usuarios del grupo Gerencia."""
        if not partners:
            return
        for cfg in self.sudo().search([]):
            to_rem = partners & cfg.management_report_partner_ids
            if to_rem:
                cfg.management_report_partner_ids = [(3, p.id) for p in to_rem]

    def action_send_management_report_now(self):
        """Envía el PDF del Resumen diario de inmediato a los destinatarios
        resueltos (para probar en producción). No chequea la hora ni la marca
        de último envío: es un disparo manual."""
        self.ensure_one()
        if not self._management_report_recipient_emails():
            raise UserError(_('No hay destinatarios: activá el grupo Gerencia o '
                              'agregá al menos un contacto/email antes de enviar.'))
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
