"""
Módulo: mrp_reschedule_config.py (odoo_mrp_planner_scheduling)
Modelo: extensión de mrp.reschedule.config

Agrega al singleton de configuración del planificador los parámetros de
programación y reprogramación:
- enable_scheduling: interruptor maestro de la función (default False —
  instalar el módulo NO enciende la programación; se activa desde Ajustes).
- wc_fallback y priority: comportamiento del motor de reprogramación,
  replicados en ir.config_parameter para lectura eficiente.

También implementa los hooks que el módulo base expone
(_scheduling_ui_enabled, _user_in_scheduling_group, _config_editor_groups)
para que los paneles muestren u oculten la UI de programación.
"""
from odoo import models, fields, api


class MrpRescheduleConfig(models.Model):
    _inherit = 'mrp.reschedule.config'

    # ── Programación / Reprogramación ────────────────────────────────────────

    enable_scheduling = fields.Boolean(
        string='Habilitar funciones de programación y reprogramación',
        default=False,
        help='Cuando está activo, los usuarios internos ven los menús de reprogramación, '
             'los botones en las OFs y las KPIs de "Para reprogramar" en el panel de producción. '
             'Al desactivar se quita a todos los usuarios del grupo de programación; '
             'los administradores del módulo siempre conservan acceso.'
    )

    wc_fallback = fields.Selection([
        ('ldm', 'Usar operaciones de la Lista de Materiales'),
        ('none', 'Sin centro de trabajo'),
    ], string='Fallback de centro de trabajo', default='ldm', required=True)

    priority = fields.Selection([
        ('chronological', 'Orden cronológico (fecha actual)'),
        ('shortest_first', 'Más cortas primero (SPT)'),
        ('manual', 'Secuencia manual en el wizard'),
    ], string='Criterio de prioridad al reprogramar', default='chronological', required=True,
       help='Orden en que se programan las OFs cuando compiten por el mismo centro de trabajo. '
            'Cronológico: respeta las fechas actuales. '
            'SPT (más cortas primero): minimiza el tiempo de espera promedio. '
            'Manual: el operador define el orden en el wizard.'
    )


    include_wc_heuristic = fields.Boolean(
        string='Heurística por centro de trabajo',
        default=False,
        help='Cuando está activo, la reprogramación en cascada incluye como dependientes '
             'las OFs que comparten centros de trabajo con el pivot y comienzan después. '
             'Puede generar reprogramaciones masivas en instalaciones con alta carga de CTs.',
    )

    default_scheduling_tag_id = fields.Many2one(
        'mrp.workcenter.tag',
        string='Sector predeterminado del tablero de programación',
        help='Sector que se preselecciona automáticamente al abrir el tablero de programación de producción.',
    )

    def _sync_scheduling_group(self, enabled):
        """Activa/desactiva los menús y el grupo de scheduling según el toggle.

        Usa SQL directo en ir_ui_menu para garantizar que el cambio llegue a la
        base de datos incluso si env.ref() falla por caché o estado del registry.
        Invalida el caché ORM del modelo después del UPDATE para que la sesión
        actual no devuelva datos obsoletos.

        En entornos multi-empresa, solo oculta los menús si ninguna otra empresa
        tiene scheduling activo, para evitar afectar a usuarios de otras empresas.
        """
        if not enabled:
            # sudo(): necesario para verificar otros registros de config sin importar el usuario activo
            other_enabled = self.env['mrp.reschedule.config'].sudo().search([
                ('id', 'not in', self.ids),
                ('enable_scheduling', '=', True),
            ], limit=1)
            if other_enabled:
                return
        cr = self.env.cr
        menu_xmlids = [
            ('odoo_mrp_planner_scheduling', 'mrp_reschedule_menu_plans'),
            ('odoo_mrp_planner_scheduling', 'mrp_reschedule_menu_request'),
        ]
        for module, name in menu_xmlids:
            cr.execute(
                "SELECT res_id FROM ir_model_data WHERE module=%s AND name=%s LIMIT 1",
                (module, name),
            )
            row = cr.fetchone()
            if row:
                cr.execute("UPDATE ir_ui_menu SET active=%s WHERE id=%s", (enabled, row[0]))
        self.env['ir.ui.menu'].invalidate_model(['active'])

        group = self.env.ref('odoo_mrp_planner_scheduling.group_scheduling', raise_if_not_found=False)
        if not group:
            return
        if not enabled:
            # sudo(): ir.groups pertenece al sistema; el admin del módulo no tiene acceso directo
            group.sudo().write({'users': [(5,)]})

    @api.model
    def _config_editor_groups(self):
        return super()._config_editor_groups() + ['odoo_mrp_planner_scheduling.group_scheduling']

    @api.model
    def _user_in_scheduling_group(self, user=None):
        u = user or self.env.user
        return (
            u.has_group('odoo_mrp_planner_scheduling.group_scheduling')
            or u.has_group('odoo_mrp_planner.group_admin')
            or u.has_group('base.group_system')
        )

    @api.model
    def _scheduling_ui_enabled(self, user=None):
        """UI de programación visible: toggle activo en la config de la empresa
        y usuario con grupo de Programación (o administrador)."""
        cfg = self.get_config()
        enabled = bool(cfg.enable_scheduling) if cfg else False
        return enabled and self._user_in_scheduling_group(user)

    def write(self, vals):
        res = super().write(vals)
        if 'enable_scheduling' in vals:
            self._sync_scheduling_group(vals['enable_scheduling'])
        sp = self.env['ir.config_parameter'].sudo()
        company_id = self.env.company.id
        if 'wc_fallback' in vals:
            sp.set_param(f'mrp_reschedule.wc_fallback.{company_id}', vals['wc_fallback'])
        if 'priority' in vals:
            sp.set_param(f'mrp_reschedule.priority.{company_id}', vals['priority'])
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        sp = self.env['ir.config_parameter'].sudo()
        for rec in records:
            if rec.enable_scheduling:
                rec._sync_scheduling_group(True)
            sp.set_param(f'mrp_reschedule.wc_fallback.{rec.company_id.id}', rec.wc_fallback)
            sp.set_param(f'mrp_reschedule.priority.{rec.company_id.id}', rec.priority)
        return records
