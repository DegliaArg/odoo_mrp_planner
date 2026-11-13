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
from odoo import models, fields, api, _


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

    # ── Motor de necesidades (Panel 1) ───────────────────────────────────────

    safety_factor = fields.Float(
        string='Factor de stock de seguridad',
        default=0.3,
        help='Multiplica el promedio de forecast para obtener el stock de seguridad '
             '(stock de seguridad = ROUNDUP(promedio × factor)). Valor por defecto: 0,3. Editable.',
    )
    days_per_month = fields.Float(
        string='Días promedio por mes',
        default=30.4375,
        help='Convierte el promedio de forecast mensual a demanda diaria para calcular '
             'la demanda durante el lead time. Valor por defecto: 30,4375.',
    )
    coverage_threshold = fields.Float(
        string='Umbral de cobertura con programa (meses)',
        default=7.0,
        help='Si la cobertura con programa supera este valor, el artículo se marca '
             '"Analizar cobertura" en lugar de "Programar". Valor por defecto: 7 meses.',
    )
    planning_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén de planificación',
        help='Almacén cuyo stock pronosticado (a la mano + entrante − saliente) usa el motor '
             'de necesidades como posición de stock. Si se deja vacío se consideran todos los '
             'almacenes de la empresa.',
    )
    manufacturing_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén de fabricación',
        help='Almacén (sector) de fabricación cuyo componente, dentro de la BOM del artículo '
             'final, aporta la máquina y el mínimo por turno. El motor busca en la BOM el '
             'componente cuyo almacén de fabricación es éste (vía la ruta de reabastecimiento '
             'del componente, supplier_wh_id) y lee de ahí esos datos. Si se deja vacío (o no '
             'se puede resolver), el motor usa el propio artículo final. Opcional, no bloqueante.',
    )

    def action_recompute_planning_sources(self):
        """Botón: recalcula de una vez los campos de planificación (componente
        fabricado y componente comprado) recorriendo la BOM, para que el panel no la
        explore en cada carga."""
        res = self.env['mrp.production.needs'].sudo()._recompute_planning_sources()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recálculo de planificación'),
                'message': _(
                    '%(p)s artículos procesados · %(v)s componentes fabricados y %(b)s '
                    'componentes comprados detectados/actualizados.',
                    p=res['products'], v=res['manufactured'], b=res['purchase']),
                'type': 'success',
                'sticky': False,
            },
        }

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
            sp.set_param(f'mrp_reschedule.wc_fallback.{rec.company_id.id}', rec.wc_fallback)
            sp.set_param(f'mrp_reschedule.priority.{rec.company_id.id}', rec.priority)
        return records
