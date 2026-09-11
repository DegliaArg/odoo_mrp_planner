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

    default_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de operación predeterminado',
        domain="[('code', '=', 'mrp_operation'), ('company_id', '=', company_id)]",
        help='Tipo de operación de fabricación que se preselecciona al crear una nueva Programación de fabricación.',
    )

    scheduling_direction = fields.Selection([
        ('alap', 'Ajustada al plazo (ALAP)'),
        ('asap', 'Lo antes posible (ASAP)'),
    ], string='Dirección de programación por defecto', default='alap', required=True,
        help='Política con que el motor calza cada operación en la agenda del centro. '
             'ALAP: hueco más tardío que cumpla la fecha deseada (no adelanta producción). '
             'ASAP: primer hueco disponible (empaqueta temprano). Es solo el valor por '
             'defecto de cada nueva solicitud; se puede cambiar en la solicitud misma.',
    )

    # ── Criterios de optimización (cascada lexicográfica configurable) ──────────
    # El proposer y el preview de impacto rankean las alternativas comparando el
    # plan por estos criterios EN ORDEN (1º manda; a igualdad decide el 2º; etc.).
    # Cada selector elige un criterio o 'No usar' para desactivarlo. El orden de
    # los tres campos ES la jerarquía. Default = comportamiento histórico.
    _OPT_CRITERION_SELECTION = [
        ('lateness', 'Cumplir plazos (menos atraso)'),
        ('makespan', 'Terminar antes (tiempo total)'),
        ('peak',     'Equilibrar carga de centros'),
        ('none',     'No usar'),
    ]

    opt_criterion_1 = fields.Selection(
        _OPT_CRITERION_SELECTION, string='1er criterio de optimización',
        default='lateness', required=True,
        help='Criterio de mayor prioridad al comparar alternativas del plan.')
    opt_criterion_2 = fields.Selection(
        _OPT_CRITERION_SELECTION, string='2do criterio de optimización',
        default='makespan', required=True,
        help='Desempata cuando el 1er criterio da igual. "No usar" para ignorarlo.')
    opt_criterion_3 = fields.Selection(
        _OPT_CRITERION_SELECTION, string='3er criterio de optimización',
        default='peak', required=True,
        help='Desempata cuando los dos primeros dan igual. "No usar" para ignorarlo.')

    @api.model
    def optimization_criteria(self):
        """Orden de criterios ACTIVOS para la cascada de optimización.

        Lee los 3 selectores de config, saltea 'No usar' y duplicados, y
        preserva el orden (= jerarquía). Si quedara vacío (todo 'No usar'),
        cae al default histórico atraso→makespan→carga para no dejar sin
        criterio a la comparación.

        :returns: list[str] — subconjunto ordenado de ['lateness','makespan','peak'].
        """
        cfg = self.get_config()
        order = []
        if cfg:
            for fname in ('opt_criterion_1', 'opt_criterion_2', 'opt_criterion_3'):
                val = cfg[fname]
                if val and val != 'none' and val not in order:
                    order.append(val)
        return order or ['lateness', 'makespan', 'peak']

    # ── Comportamiento cuando un artículo NO llega al plazo (infeasible) ────────
    # Cuando el deadline es inalcanzable, el motor no puede pegar al plazo (ALAP)
    # y debe elegir entre dos filosofías. 'asap' (actual): empaqueta lo antes
    # posible → termina cuanto antes, minimiza el atraso, pero más WIP (componentes
    # fabricados mucho antes de consumirse). 'jit': mantiene cada componente lo más
    # cerca posible de su consumo → menos WIP, aceptando la misma fecha tardía.
    infeasible_policy = fields.Selection([
        ('asap', 'Minimizar atraso (empaquetar temprano)'),
        ('jit',  'Minimizar WIP (JIT, aunque llegue tarde)'),
    ], string='Cuando no llega al plazo', default='asap', required=True,
        help='Qué prioriza el motor cuando un artículo no puede cumplir su fecha '
             'deseada. "Minimizar atraso" termina lo antes posible (más inventario '
             'en proceso). "Minimizar WIP" mantiene los componentes pegados a su '
             'consumo (menos inventario en proceso), con la misma fecha final.')

    @api.model
    def infeasible_policy_value(self):
        """Política de infeasibilidad vigente ('asap' | 'jit'). Default 'asap'."""
        cfg = self.get_config()
        return (cfg.infeasible_policy or 'asap') if cfg else 'asap'

    default_of_hours = fields.Float(
        string='Horas por OF sin ruta', default=8.0,
        help='Duración estimada (horas) que asume el motor para una OF cuya LdM no '
             'define operaciones/ruta. 0 usa el valor por defecto (8 h).',
    )
    default_op_minutes = fields.Float(
        string='Minutos por operación sin tiempo', default=60.0,
        help='Duración mínima (minutos) que asume el motor para una operación de LdM '
             'sin tiempo de ciclo ni setup configurados. 0 usa el valor por defecto (60 min).',
    )

    board_hidden_weekdays = fields.Char(
        string='Días ocultos del tablero',
        default='5,6',
        help='Días de la semana que el tablero colapsa cuando el toggle "Ocultar '
             'fines de semana" está activo, como lista separada por comas con la '
             'convención de Python (lunes=0 … domingo=6). Por defecto 5,6 '
             '(sábado y domingo). No puede ser fijo: hay CTs que trabajan sábado.',
    )

    @api.model
    def _board_hidden_weekdays_list(self):
        """Días ocultos del tablero como lista de int (lunes=0 … domingo=6)."""
        cfg = self.get_config()
        raw = (cfg.board_hidden_weekdays or '') if cfg else ''
        out = []
        for tok in raw.split(','):
            tok = tok.strip()
            if tok.isdigit() and 0 <= int(tok) <= 6:
                out.append(int(tok))
        return out

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
        # Cada config pertenece a su propia empresa: se escribe el parámetro con el
        # sufijo de rec.company_id (no de la empresa activa), igual que create().
        for rec in self:
            if 'wc_fallback' in vals:
                sp.set_param(f'mrp_reschedule.wc_fallback.{rec.company_id.id}', vals['wc_fallback'])
            if 'priority' in vals:
                sp.set_param(f'mrp_reschedule.priority.{rec.company_id.id}', vals['priority'])
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
