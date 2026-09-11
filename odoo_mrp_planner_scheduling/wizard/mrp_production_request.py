"""
Módulo: mrp_production_request.py
Modelo: mrp.production.request

Solicitud de programación de fabricación: agrupa artículos a producir, calcula
un plan de fechas considerando stock, rutas, calendarios y carga de centros de
trabajo, y finalmente crea las órdenes de fabricación (OF) confirmadas en Odoo.

Responsabilidades:
- Recibir una lista de productos con cantidades y fechas límite.
- Construir el árbol de demanda multinivel (OF, OC, subcontrato, stock) por producto.
- Programar el árbol de forma bottom-up respetando la carga existente en los WC.
- Guardar el plan calculado como líneas auditables antes de confirmar.
- Crear y confirmar las OFs madre (nivel 0); Odoo genera las hijas automáticamente.
- Planificar recursivamente las OFs hijas propagando fechas hacia atrás.

Relacionado con:
- mrp.production.request.item: artículos solicitados (1 por producto/cantidad).
- mrp.production.request.line: líneas del plan calculado (OF / OC / Stock).
- mrp.production.request.wc: resumen de carga por centro de trabajo.
- mrp.schedule.mixin: lógica compartida de scheduling (schedule_duration, etc.).
- mrp.planner.detail.dashboard: dashboard de planificación asociado.
"""
import logging
import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError

from .mrp_demand_expansion_mixin import MrpDemandExpansionMixin
from .mrp_demand_scheduling_mixin import MrpDemandSchedulingMixin
from ..models.mrp_reschedule_cascade_mixin import _search_by_origin

_logger = logging.getLogger(__name__)


class MrpProductionRequest(MrpDemandExpansionMixin, MrpDemandSchedulingMixin, models.Model):
    _name = 'mrp.production.request'
    _description = 'Solicitud de programación de fabricación'
    _inherit = ['mrp.schedule.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Referencia', readonly=True, default='Nuevo', copy=False,
        help='Número de secuencia autogenerado al guardar (ej. MRP/2024/0001).',
    )
    active = fields.Boolean(
        default=True,
        help='Desactivar oculta la solicitud sin eliminarla (archivado).',
    )
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True,
        default=lambda self: self.env.company, index=True,
    )

    start_from = fields.Datetime(
        string='Disponible desde', default=fields.Datetime.now,
        help='Fecha mínima de inicio para todos los artículos.',
    )
    item_ids = fields.One2many('mrp.production.request.item', 'request_id', string='Artículos')
    line_ids      = fields.One2many('mrp.production.request.line', 'request_id', string='Plan calculado')
    line_ids_plan = fields.One2many(
        'mrp.production.request.line', 'request_id',
        domain=[('is_auto_reorder', '=', False)],
        string='Plan calculado (sin automáticos)',
    )
    line_ids_suggestions = fields.One2many(
        'mrp.production.request.line', 'request_id',
        domain=[('suggestion_state', '=', 'pending')],
        string='Sugerencias de CT pendientes',
    )
    state    = fields.Selection([
        ('draft',      'Borrador'),
        ('calculated', 'Calculado'),
        ('confirmed',  'OFs creadas'),
    ], default='draft', tracking=True,
        help='Ciclo de vida: Borrador → Calculado (plan listo) → OFs creadas (confirmado).',
    )

    all_feasible        = fields.Boolean(compute='_compute_summary', store=False)
    feasibility_summary = fields.Char(compute='_compute_summary', store=False)

    hide_auto_reorder = fields.Boolean(
        string='Ocultar reab. automático',
        default=True,
        help='Si está activo, oculta en la vista las líneas de reabastecimiento automático (min/max).',
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de operación',
        domain="[('code', '=', 'mrp_operation'), ('company_id', '=', company_id)]",
        required=True,
        default=lambda self: self._default_picking_type(),
        help='Tipo de operación de fabricación con el que se crearán las OFs.',
    )

    @api.model
    def _default_picking_type(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        if cfg and cfg.default_picking_type_id:
            return cfg.default_picking_type_id
        return self.env['stock.picking.type'].search(
            [('code', '=', 'mrp_operation'), ('company_id', '=', self.env.company.id)], limit=1
        )

    scheduling_direction = fields.Selection([
        ('alap', 'Ajustada al plazo (ALAP)'),
        ('asap', 'Lo antes posible (ASAP)'),
    ], string='Dirección de programación', required=True,
        default=lambda self: self._default_scheduling_direction(),
        help='ALAP: cada operación se calza en el hueco más tardío que cumpla la fecha '
             'deseada, sin adelantar producción (menos WIP parado). ASAP: se calza en el '
             'primer hueco disponible, empaquetando temprano y liberando capacidad futura. '
             'Cambiá la dirección y recalculá para comparar cómo queda el calce.',
    )

    @api.model
    def _default_scheduling_direction(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        return (cfg.scheduling_direction if cfg and cfg.scheduling_direction else 'alap')
    workorder_count = fields.Integer(
        compute='_compute_workorder_count', string='OTs',
        help='Cantidad total de órdenes de trabajo (work orders) de las OFs vinculadas.',
    )
    wc_load_ids        = fields.One2many('mrp.production.request.wc', 'request_id', string='Carga WC')
    has_ct_suggestions = fields.Boolean(
        compute='_compute_has_ct_suggestions',
        help='True si hay líneas con sugerencias de CT alternativo pendientes de revisar.',
    )

    @api.depends('line_ids.suggestion_state')
    def _compute_has_ct_suggestions(self):
        for rec in self:
            rec.has_ct_suggestions = any(
                l.suggestion_state == 'pending' for l in rec.line_ids
            )

    def action_accept_all_suggestions(self):
        """Acepta todas las sugerencias de CT alternativo pendientes."""
        self.ensure_one()
        self.line_ids.filtered(
            lambda l: l.suggestion_state == 'pending'
        ).action_accept_ct_suggestion()

    def action_reject_all_suggestions(self):
        """Revierte todas las sugerencias pendientes al CT primario de cada operación."""
        self.ensure_one()
        self.line_ids.filtered(
            lambda l: l.suggestion_state == 'pending'
        ).action_reject_ct_suggestion()

    def reassign_line_workcenter(self, line_id, wc_id):
        """Fase 2 (jugar con alternativos): fija la línea-OF `line_id` al centro
        `wc_id` y recalcula el plan (pin & re-solve).

        Reutiliza el mecanismo de overrides de action_calculate: al fijar el
        workcenter_id de la línea, el recálculo preserva esa elección (se pinnean
        las operaciones que tengan ese CT como candidato) y reprograma el resto
        alrededor. Se invoca desde el tablero de propuesta al reasignar una barra.

        :param line_id: int — ID de la mrp.production.request.line a reasignar.
        :param wc_id: int — ID del centro de trabajo elegido.
        :returns: bool — True al terminar (el tablero recarga la propuesta).
        :raises UserError: si la línea no pertenece a la solicitud o el CT no existe.
        :raises AccessError: si el usuario no tiene el grupo de Programación.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        line = self.env['mrp.production.request.line'].browse(int(line_id))
        if not line.exists() or line.request_id.id != self.id:
            raise UserError(_('La línea no pertenece a esta solicitud.'))
        wc = self.env['mrp.workcenter'].browse(int(wc_id))
        if not wc.exists():
            raise UserError(_('El centro de trabajo elegido no existe.'))
        # Fijar el CT como override y recalcular. action_calculate preserva el
        # workcenter_id de las líneas 'mrp' con node_key como wc_overrides.
        line.write({
            'workcenter_id':    wc.id,
            'used_alternative': False,
            'suggestion_state': 'accepted',
        })
        self.action_calculate()
        return True

    @api.depends('item_ids.feasible', 'item_ids.earliest_end')
    def _compute_summary(self):
        """
        Calcula all_feasible y feasibility_summary para cada solicitud.

        Fórmula: cuenta artículos con earliest_end calculado y cuántos de ellos
        son feasible; construye un texto resumen del estado global.
        Depende de: item_ids.feasible, item_ids.earliest_end.
        """
        for rec in self:
            items     = rec.item_ids
            scheduled = items.filtered('earliest_end')
            if not scheduled:
                rec.all_feasible = False
                rec.feasibility_summary = _('Sin datos calculados')
                continue
            # Contar sobre TODOS los artículos, no solo los que dieron fecha (fix M4):
            # un item sin earliest_end (no se pudo calcular) cuenta como "no cumple",
            # así el banner no dice "todos cumplen" escondiendo a los sin fecha.
            total   = len(items)
            ok      = sum(1 for i in scheduled if i.feasible)
            no_date = total - len(scheduled)
            rec.all_feasible = ok == total
            if ok == total:
                rec.feasibility_summary = _('Todos los artículos cumplen el plazo (%d/%d)') % (ok, total)
            else:
                msg = _('%d de %d artículos no cumplen el plazo') % (total - ok, total)
                if no_date:
                    msg += _(' (%d sin fecha calculable)') % no_date
                rec.feasibility_summary = msg

    @api.depends('item_ids.production_id')
    def _compute_workorder_count(self):
        """
        Calcula workorder_count para cada solicitud.

        Fórmula: suma los work orders de todas las OFs vinculadas a los items.
        Depende de: item_ids.production_id.
        """
        for rec in self:
            mo_ids = rec.item_ids.mapped('production_id').ids
            rec.workorder_count = self.env['mrp.workorder'].search_count([
                ('production_id', 'in', mo_ids),
            ]) if mo_ids else 0

    def action_open_planner_dashboard(self):
        """
        Abre el dashboard del planificador filtrado por la categoría 'requests'.

        :returns: dict — acción de ventana al dashboard de planificación.
        """
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('requests')

    def action_view_workorders(self):
        """
        Abre la vista lista/form/gantt de todas las OTs vinculadas a la solicitud.

        :returns: dict — acción de ventana con dominio filtrado por las OFs del plan.
        """
        self.ensure_one()
        mo_ids = self.item_ids.mapped('production_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de trabajo'),
            'res_model': 'mrp.workorder',
            'view_mode': 'list,form,gantt',
            'domain': [('production_id', 'in', mo_ids)],
            'target': 'current',
        }

    # ── Migración ─────────────────────────────────────────────────────────────

    def _auto_init(self):
        super()._auto_init()
        self.env.cr.execute("SAVEPOINT fill_request_company_id")
        try:
            self.env.cr.execute("""
                UPDATE mrp_production_request req
                   SET company_id = COALESCE(
                           (SELECT spt.company_id
                              FROM stock_picking_type spt
                             WHERE spt.id = req.picking_type_id
                             LIMIT 1),
                           (SELECT id FROM res_company ORDER BY id LIMIT 1)
                       )
                 WHERE company_id IS NULL
            """)
            self.env.cr.execute("RELEASE SAVEPOINT fill_request_company_id")
        except Exception:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT fill_request_company_id")

    # ── Creación ─────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """
        Crea solicitudes de programación asignando número de secuencia automático.

        Reemplaza el valor por defecto 'Nuevo' con el siguiente número de la
        secuencia 'mrp.production.request' antes de delegar a super().

        :param vals_list: list[dict] — valores de los registros a crear.
        :returns: mrp.production.request — recordset de los registros creados.
        """
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mrp.production.request')
                    or 'Nuevo'
                )
        return super().create(vals_list)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def _ensure_scheduling_group(self):
        """Guard de servidor para las acciones de programación.

        El flag can_schedule solo oculta los botones en la UI: sin este guard,
        cualquier usuario con permisos MRP estándar podía calcular/confirmar
        por RPC sin pertenecer al grupo de Programación.
        """
        u = self.env.user
        if not (u.has_group('odoo_mrp_planner_scheduling.group_scheduling')
                or u.has_group('odoo_mrp_planner.group_admin')
                or u.has_group('base.group_system')):
            raise AccessError(_('Solo los usuarios del grupo Programación pueden ejecutar esta acción.'))

    # ── Núcleo de cálculo (compartido por cálculo real y simulación) ─────────

    def _current_wc_overrides(self):
        """Overrides de CT vigentes: {node_key: workcenter} de las líneas-OF con
        centro fijado. Es el "pin" que preserva las elecciones manuales entre
        recálculos, y la base sobre la que la simulación aplica cambios hipotéticos.
        """
        return {
            l.node_key: l.workcenter_id
            for l in self.line_ids
            if l.workcenter_id and l.record_type == 'mrp' and l.node_key
        }

    def _plan_min_dt(self):
        """Piso temporal del plan: max(start_from, hoy UTC midnight). Nada se
        programa antes de hoy."""
        start = self.start_from or fields.Datetime.now()
        if hasattr(start, 'tzinfo') and start.tzinfo:
            start = start.astimezone(pytz.utc).replace(tzinfo=None)
        today_utc = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return max(start, today_utc)

    def _build_and_schedule(self, overrides=None):
        """Núcleo de cálculo PURO (sin escribir en la base): construye el árbol de
        demanda de cada artículo, aplica los overrides de CT, obtiene la agenda de
        cada centro y programa todo compartiendo esa agenda.

        Lo usan tanto action_calculate (que además persiste) como la simulación y el
        proposer (que solo miran los resultados). NO toca líneas, ítems ni estado.

        :param overrides: dict | None — {node_key: workcenter} pines de CT a aplicar.
        :returns: tuple — (item_trees, wc_collector, item_results, min_dt) donde
            item_trees = [(item, root)], wc_collector = {wc_id: {hours,start,end}},
            item_results = {item.id: {earliest_end, projected_start, projected_end,
            feasible, deadline}}.
        :raises UserError: si algún artículo no tiene LdM fabricable.
        """
        min_dt = self._plan_min_dt()

        # Construir árbol de demanda por artículo (cachés compartidos, evita N+1).
        missing, item_trees = [], []
        caches = self._new_caches()
        for item in self.item_ids.sorted(lambda i: (i.sequence, i.id)):
            root = self._build_demand_tree(item.product_id, item.product_qty,
                                           level=0, caches=caches)
            if not root:
                missing.append(item.product_id.display_name)
            else:
                item_trees.append((item, root))
        if missing:
            raise UserError(_('Sin lista de materiales para: %s') % ', '.join(missing))

        if overrides:
            for item, root in item_trees:
                self._apply_wc_overrides(root, item.id, overrides)

        all_roots = [r for _, r in item_trees]
        wc_busy   = self._get_wc_busy_multi(min_dt, all_roots)

        wc_collector = {}
        item_results = {}
        direction = self.scheduling_direction or 'alap'
        for item, root in item_trees:
            self._schedule_tree(root, min_dt, wc_busy, min_dt=min_dt,
                                target_end=item.date_deadline, wc_collector=wc_collector,
                                direction=direction)
            earliest   = root.get('scheduled_end')
            proj_start = self._get_tree_earliest_start(root)
            proj_end   = item.date_deadline
            if earliest and proj_end and earliest > proj_end:
                proj_end = earliest
            item_results[item.id] = {
                'earliest_end':    earliest,
                'projected_start': proj_start,
                'projected_end':   proj_end,
                'deadline':        item.date_deadline,
                'feasible':        bool(earliest and item.date_deadline
                                        and earliest <= item.date_deadline),
            }
        return item_trees, wc_collector, item_results, min_dt

    def _wc_occupancy(self, wc_collector, min_dt):
        """Ocupación por CT a partir del wc_collector: horas planificadas vs horas
        disponibles del centro en el horizonte global del plan. Compartido por el
        resumen persistido (wc_load_ids) y por la simulación.

        :returns: dict — {wc_id: {total_hours, available_hours, occupancy_pct,
            date_start, date_end}}.
        """
        out = {}
        if not wc_collector:
            return out
        starts = [d['start'] for d in wc_collector.values() if d['start']]
        ends   = [d['end']   for d in wc_collector.values() if d['end']]
        horizon_start = min(starts) if starts else min_dt
        horizon_end   = max(ends)   if ends   else min_dt
        avail_cache = {}
        company_cal = self.env.company.resource_calendar_id
        for wc_id, data in wc_collector.items():
            avail_h = 0.0
            if horizon_end > horizon_start:
                cal = (self.env['mrp.workcenter'].browse(wc_id).resource_calendar_id
                       or company_cal)
                if cal:
                    avail_h = cal._planner_available_hours(
                        horizon_start, horizon_end, cache=avail_cache) or 0.0
            planned_h = round(data['hours'], 2)
            occ = round(planned_h / avail_h * 100) if avail_h > 0 else (999 if planned_h > 0 else 0)
            out[wc_id] = {
                'total_hours':     planned_h,
                'available_hours': round(avail_h, 2),
                'occupancy_pct':   occ,
                'date_start':      data['start'],
                'date_end':        data['end'],
            }
        return out

    def action_calculate(self):
        """
        Calcula el plan de fabricación para todos los artículos de la solicitud.

        Preserva los overrides de CT, corre el núcleo `_build_and_schedule` y
        persiste el resultado: líneas del plan, operaciones, fechas por artículo y
        resumen de carga por CT. Transiciona el estado a 'calculated'.

        :returns: dict — acción de ventana que recarga el formulario actual.
        :raises UserError: si no hay artículos o si algún artículo no tiene LdM.
        :raises AccessError: si el usuario no tiene el grupo de Programación.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        if not self.item_ids:
            raise UserError(_('Agregue al menos un artículo.'))

        # Preservar los pines de CT ANTES de borrar las líneas (se keyean por
        # node_key para no aplicarse a la rama equivocada).
        overrides = self._current_wc_overrides()
        # Preservar las DECISIONES de sugerencias de CT: un alternativo que el
        # usuario ya aceptó (o eligió manualmente) NO debe reaparecer como
        # 'pendiente' tras recalcular. Se keyea por node_key (estable entre
        # recálculos). Los 'rejected' volvieron al primario → dejan de ser
        # alternativos solos, no hace falta preservarlos.
        prior_sugg = {
            l.node_key: l.suggestion_state
            for l in self.line_ids
            if l.node_key and l.record_type == 'mrp'
            and l.suggestion_state == 'accepted'
        }
        self.line_ids.unlink()
        self.wc_load_ids.unlink()
        self.item_ids.write({'projected_end': False, 'projected_start': False})

        item_trees, wc_collector, item_results, min_dt = self._build_and_schedule(overrides)

        # Escribir fechas por artículo y recolectar las líneas del plan.
        lines_vals = []
        seq = [10]
        for item, root in item_trees:
            self._collect_lines(root, lines_vals, seq, item_id=item.id)
            r = item_results[item.id]
            item.write({
                'earliest_end':    r['earliest_end'],
                'projected_start': r['projected_start'],
                'projected_end':   r['projected_end'],
            })

        # Crear las líneas. Se extraen las claves transitorias (_parent_key, _ops)
        # que NO son campos del modelo, y se post-procesan tras el create para
        # setear parent_line_id (necesita los IDs ya creados) y las operaciones.
        parent_keys = []
        ops_lists   = []
        for vals in lines_vals:
            vals['request_id'] = self.id
            parent_keys.append(vals.pop('_parent_key', None))
            ops_lists.append(vals.pop('_ops', None))

        if lines_vals:
            lines = self.env['mrp.production.request.line'].create(lines_vals)

            # Mapa node_key → línea creada. node_key es único por solicitud (item +
            # path completo), así que no colisiona entre artículos ni ramas.
            key_to_line = {l.node_key: l for l in lines if l.node_key}

            # Vincular padres e insertar operaciones (una line.op por barra del Gantt).
            op_vals = []
            for line, parent_key, ops in zip(lines, parent_keys, ops_lists):
                if parent_key and parent_key in key_to_line:
                    line.parent_line_id = key_to_line[parent_key].id
                for op in (ops or []):
                    op_vals.append(dict(op, line_id=line.id))
            if op_vals:
                self.env['mrp.production.request.line.op'].create(op_vals)

            # Restaurar las decisiones previas: los alternativos ya aceptados
            # vuelven a 'accepted' (el motor los recreó como 'pending'), así no
            # reaparecen en la tabla de sugerencias pendientes tras recalcular.
            if prior_sugg:
                for line in lines:
                    if (line.record_type == 'mrp' and line.used_alternative
                            and prior_sugg.get(line.node_key) == 'accepted'):
                        line.suggestion_state = 'accepted'

        # Resumen de carga por WC — desde la ocupación calculada sobre el collector.
        occ = self._wc_occupancy(wc_collector, min_dt)
        if occ:
            wc_vals = [
                dict(data, request_id=self.id, workcenter_id=wc_id)
                for wc_id, data in sorted(
                    occ.items(),
                    key=lambda x: x[1]['date_start'] or datetime.min,
                )
            ]
            self.env['mrp.production.request.wc'].create(wc_vals)

        self.state = 'calculated'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Simulación y propuestas de optimización ──────────────────────────────

    @staticmethod
    def _fmt_secs(secs):
        """Formatea una duración en segundos como 'Xd Yh' / 'Yh Zm' / 'Zm'."""
        secs = abs(int(secs))
        d, h, m = secs // 86400, (secs % 86400) // 3600, (secs % 3600) // 60
        if d:
            return f'{d}d {h}h' if h else f'{d}d'
        if h:
            return f'{h}h {m}m' if m else f'{h}h'
        return f'{m}m'

    def _opt_criterion_meta(self):
        """Metadatos de cada criterio de optimización: etiqueta, umbral de cambio
        significativo, formateo de un valor y frase de delta para la línea
        compacta. Menor es mejor en todos."""
        return {
            'lateness': {
                'label': 'Atraso total', 'thr': 60,
                'fmt':   lambda v: self._fmt_secs(v) if v >= 60 else 'a tiempo',
                'delta': lambda d: ('atraso −%s' if d < 0 else 'atraso +%s') % self._fmt_secs(d),
            },
            'makespan': {
                'label': 'Duración del plan', 'thr': 60,
                'fmt':   lambda v: self._fmt_secs(v),
                'delta': lambda d: (self._fmt_secs(d) + ' antes') if d < 0
                                   else (self._fmt_secs(d) + ' después'),
            },
            'peak': {
                'label': 'Pico de carga', 'thr': 0.5,
                'fmt':   lambda v: '%.0f h' % v,
                'delta': lambda d: 'pico %s%.0fh' % ('−' if d < 0 else '+', abs(d)),
            },
        }

    def _plan_metrics(self, item_results, wc_collector, min_dt):
        """Métricas CRUDAS del plan (menor es mejor en cada una). El orden y cuáles
        pesan en la comparación lo define la config (ver _metric_key).

        :returns: dict — {'lateness': seg, 'makespan': seg, 'peak': hs}.
        """
        lateness = 0.0
        makespan_end = None
        for r in item_results.values():
            ee, dl = r['earliest_end'], r['deadline']
            if ee and dl and ee > dl:
                lateness += (ee - dl).total_seconds()
            if ee and (makespan_end is None or ee > makespan_end):
                makespan_end = ee
        makespan = (makespan_end - min_dt).total_seconds() if makespan_end else 0.0
        max_hours = max((d['hours'] for d in wc_collector.values()), default=0.0)
        return {'lateness': round(lateness, 1),
                'makespan': round(makespan, 1),
                'peak':     round(max_hours, 3)}

    def _metric_key(self, metrics):
        """Clave de comparación lexicográfica según los criterios ACTIVOS y su
        orden de prioridad (configurable). `metrics` es un dict de _plan_metrics.
        Menor es mejor."""
        order = self.env['mrp.reschedule.config'].optimization_criteria()
        return tuple(metrics[k] for k in order)

    def _delta_label(self, base, trial):
        """Describe `trial` vs `base` (dicts de _plan_metrics) en una línea
        compacta, solo con los criterios activos y en su orden de prioridad."""
        meta = self._opt_criterion_meta()
        parts = []
        for k in self.env['mrp.reschedule.config'].optimization_criteria():
            d = trial[k] - base[k]
            if abs(d) >= meta[k]['thr']:
                parts.append(meta[k]['delta'](d))
        return ' · '.join(parts) or 'sin cambios netos'

    def _impact_effects(self, base, trial):
        """Detalle ANTES→DESPUÉS por criterio ACTIVO que cambia de verdad, en el
        orden de prioridad configurado.

        :returns: list[dict] — [{k, before, after, better}] por criterio.
        """
        meta = self._opt_criterion_meta()
        effects = []
        for k in self.env['mrp.reschedule.config'].optimization_criteria():
            if abs(trial[k] - base[k]) >= meta[k]['thr']:
                effects.append({
                    'k':      meta[k]['label'],
                    'before': meta[k]['fmt'](base[k]),
                    'after':  meta[k]['fmt'](trial[k]),
                    'better': trial[k] < base[k],
                })
        return effects

    def _line_alt_workcenters(self, line):
        """CTs alternativos válidos para reasignar una línea-OF: la unión de los
        candidatos de sus operaciones, activos, distintos del centro actual."""
        return line.op_ids.mapped('candidate_workcenter_ids').filtered(
            lambda w: w.active and w.id != line.workcenter_id.id
        )

    def simulate_reassign_options(self, line_id):
        """Preview del impacto de reasignar una línea-OF a cada CT alternativo, SIN
        persistir. Para cada alternativa corre el núcleo de cálculo en memoria y
        compara las métricas con el plan actual.

        :param line_id: int — línea-OF a evaluar.
        :returns: list[dict] — [{wc_id, wc_name, label, better}] por alternativa.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        line = self.env['mrp.production.request.line'].browse(int(line_id))
        if not line.exists() or line.request_id.id != self.id or not line.node_key:
            return []
        base_overrides = self._current_wc_overrides()
        _, base_coll, base_res, base_min = self._build_and_schedule(base_overrides)
        base_metric = self._plan_metrics(base_res, base_coll, base_min)
        base_key = self._metric_key(base_metric)

        out = []
        for wc in self._line_alt_workcenters(line)[:6]:
            trial = dict(base_overrides)
            trial[line.node_key] = wc
            try:
                _, coll, res, mn = self._build_and_schedule(trial)
            except Exception:
                continue
            metric = self._plan_metrics(res, coll, mn)
            trial_key = self._metric_key(metric)
            out.append({
                'wc_id':   wc.id,
                'wc_name': wc.display_name,
                'label':   self._delta_label(base_metric, metric),
                'effects': self._impact_effects(base_metric, metric),
                'better':  trial_key < base_key,
                'worse':   trial_key > base_key,
            })
        return out

    def propose_optimizations(self):
        """El programador propone reasignaciones que mejoran el plan, según la
        cascada de prioridad (atraso → makespan → carga). Enfoca la búsqueda en lo
        que importa —artículos que no cumplen y el CT cuello de botella— y evalúa
        cada alternativa con el simulador, quedándose con las que mejoran
        estrictamente (comparación lexicográfica de las métricas).

        Es un proposer greedy de un solo movimiento: cada sugerencia se mide contra
        el plan actual. Tras aplicar una, se puede volver a proponer para la siguiente.

        :returns: dict — {suggestions: [...], capped: bool}.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        MAX_TRIALS = 20

        base_overrides = self._current_wc_overrides()
        _, base_coll, base_res, base_min = self._build_and_schedule(base_overrides)
        base_metric = self._plan_metrics(base_res, base_coll, base_min)
        base_key = self._metric_key(base_metric)

        late_item_ids = {iid for iid, r in base_res.items() if not r['feasible']}
        bottleneck_wc = max(base_coll, key=lambda w: base_coll[w]['hours'], default=None)

        suggestions, trials, capped = [], 0, False
        for line in self.line_ids.filtered(lambda l: l.record_type == 'mrp' and l.node_key):
            touches_bottleneck = bool(bottleneck_wc) and bottleneck_wc in line.op_ids.mapped('workcenter_id').ids
            if line.item_id.id not in late_item_ids and not touches_bottleneck:
                continue
            for wc in self._line_alt_workcenters(line):
                if trials >= MAX_TRIALS:
                    capped = True
                    break
                trials += 1
                trial = dict(base_overrides)
                trial[line.node_key] = wc
                try:
                    _, coll, res, mn = self._build_and_schedule(trial)
                except Exception:
                    continue
                metric = self._plan_metrics(res, coll, mn)
                trial_key = self._metric_key(metric)
                if trial_key < base_key:
                    suggestions.append({
                        'line_id':  line.id,
                        'product':  line.product_id.display_name,
                        'from_wc':  line.workcenter_id.display_name,
                        'to_wc_id': wc.id,
                        'to_wc':    wc.display_name,
                        'label':    self._delta_label(base_metric, metric),
                        'effects':  self._impact_effects(base_metric, metric),
                        '_key':     trial_key,
                    })
            if capped:
                break

        suggestions.sort(key=lambda s: s['_key'])
        for s in suggestions:
            s.pop('_key', None)
        return {'suggestions': suggestions[:8], 'capped': capped}

    def action_confirm(self):
        """
        Crea y confirma las OFs madre (nivel 0) del plan calculado.

        Odoo genera automáticamente las órdenes hijas (OFs y OCs) a través
        de las reglas de abastecimiento configuradas en cada producto.
        Luego se planifican recursivamente todas las OFs hijas propagando
        fechas hacia atrás desde la OF madre.

        :returns: dict — acción de ventana con la lista de OFs creadas.
        :raises UserError: si el estado no es 'calculated' o si no se pudo
                           crear ninguna OF.
        :raises AccessError: si el usuario no tiene el grupo de Programación.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        if self.state != 'calculated':
            raise UserError(_('Calcule primero el plan.'))

        created_ids = []
        mother_mos = self.env['mrp.production']
        plan_failures = []  # nombres de OFs que no se pudieron planificar (fix #8)

        for item in self.item_ids.sorted(lambda i: (i.sequence, i.id)):
            root_lines = self.line_ids.filtered(
                lambda l: l.item_id.id == item.id
                and l.level == 0
                and l.record_type == 'mrp'
            )
            for line in root_lines:
                target_finish = item.projected_end or line.new_date_finish

                # Si el usuario eligió una fecha fin posterior a la calculada,
                # desplazamos el inicio por el mismo delta para mantener coherencia
                # entre date_start, date_finished y los work orders.
                date_start = line.new_date_start
                if (target_finish and line.new_date_finish
                        and target_finish > line.new_date_finish):
                    delta = target_finish - line.new_date_finish
                    date_start = line.new_date_start + delta

                mo_vals = {
                    # Propagar la empresa de la solicitud (fix #4): sin esto la OF
                    # nace en la empresa activa del usuario y, en multicompañía, las
                    # hijas y movimientos salen en ubicaciones equivocadas.
                    'company_id':    self.company_id.id,
                    'origin':        self.name,  # trazabilidad y detección de hijas
                    'product_id':    line.product_id.id,
                    'product_qty':   line.product_qty,
                    'date_start':    date_start,
                    # date_deadline = compromiso comercial (fin deseado). date_finished
                    # lo deriva Odoo desde las OTs tras button_plan; no lo pisamos a
                    # mano para no descolgar la OF de sus OTs (fix #7).
                    'date_deadline': target_finish,
                }
                if line.bom_id:
                    mo_vals['bom_id'] = line.bom_id.id
                if self.picking_type_id:
                    mo_vals['picking_type_id'] = self.picking_type_id.id

                mo = self.env['mrp.production'].with_company(self.company_id).create(mo_vals)
                mo.action_confirm()
                if mo.workorder_ids:
                    try:
                        mo.button_plan()
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: no se pudo planificar WOs de %s: %s',
                            mo.name, e,
                        )
                        plan_failures.append(mo.name or line.product_id.display_name)
                elif target_finish:
                    # Sin ruta/OTs no hay plan de OT que respetar: fijamos el fin
                    # deseado directamente (no hay incoherencia posible).
                    mo.write({'date_finished': target_finish})
                item.write({'production_id': mo.id})
                created_ids.append(mo.id)
                mother_mos |= mo

        if not created_ids:
            raise UserError(_('No se pudo crear ninguna orden de fabricación.'))

        # Planificar recursivamente todas las OFs hijas generadas por Odoo
        planned = set(created_ids)
        for mo in mother_mos:
            self._plan_child_mos(mo, planned, failures=plan_failures)

        # Avisar en el chatter si alguna OF quedó confirmada pero sin planificar,
        # en vez de solo loguear un warning que el usuario no ve (fix #8).
        if plan_failures:
            self.message_post(body=_(
                'Se crearon las OFs, pero las siguientes quedaron confirmadas SIN '
                'planificar (revisar carga/calendarios de sus centros de trabajo):'
            ) + '<br/>' + '<br/>'.join('• %s' % n for n in plan_failures))

        self.state = 'confirmed'

        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de fabricación creadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_ids)],
            'target': 'current',
        }

    # ── Helpers — planificación de OFs hijas ─────────────────────────────────

    def _find_child_mos(self, mo, planned):
        """Devuelve las OFs hijas directas de `mo` no procesadas aún.

        Usa dos estrategias combinadas para mayor robustez:
        1. Vínculo por movimientos: move_raw_ids → move_orig_ids → production_id.
        2. Campo origin de la OF hija (Odoo siempre lo setea con el nombre de la madre).

        :param mo: mrp.production — OF madre a inspeccionar.
        :param planned: set[int] — IDs de OFs ya procesadas (se excluyen del resultado).
        :returns: mrp.production — recordset de OFs hijas activas no procesadas.
        """
        # Estrategia 1: vínculo por movimientos de stock
        via_moves = mo.move_raw_ids.mapped('move_orig_ids').filtered(
            lambda m: m.production_id and m.production_id.id not in planned
        ).mapped('production_id')

        # Estrategia 2: búsqueda por campo origin (matcheo por token exacto,
        # mismo criterio que el cascade mixin: soporta origin compuesto y evita
        # falsos positivos de substring como MO/001 dentro de MO/0011).
        via_origin = self.env['mrp.production']
        if mo.name:
            matches = _search_by_origin(
                self.env, 'mrp.production', [mo.name],
                [('id', '!=', mo.id),
                 ('id', 'not in', list(planned)),
                 # Acotar a la empresa de la madre (fix #4): sin este filtro el
                 # match por origin podía cruzar OFs de otras solicitudes/empresas
                 # con el mismo nombre y pisarles fechas o confirmarlas.
                 ('company_id', '=', mo.company_id.id),
                 ('state', 'not in', ('done', 'cancel'))],
            )
            via_origin = matches.get(mo.name, self.env['mrp.production'])

        return (via_moves | via_origin).filtered(
            lambda m: m.state not in ('done', 'cancel')
        )

    def _plan_child_mos(self, mo, planned, depth=0, failures=None):
        """Navega recursivamente el árbol de OFs hijas y planifica cada una.

        Llama button_plan() en cada OF hija y propaga las fechas hacia atrás:
        la hija debe terminar cuando la madre necesita empezar (mo.date_start).
        El parámetro `planned` evita bucles y trabajo doble en árboles con
        referencias cruzadas o reutilización de componentes.

        :param mo: mrp.production — OF padre desde la que se navega hacia abajo.
        :param planned: set[int] — IDs ya procesados; se modifica en-place.
        :param depth: int — profundidad actual de recursión (protección ante ciclos).
        :param failures: list | None — acumulador de nombres de OFs que no se
                         pudieron confirmar/planificar, para reportarlas (fix #8).
        """
        # Límite de seguridad ante árboles de LdM extraordinariamente profundos. Se
        # avisa en vez de cortar en silencio: el plan sí muestra esos niveles y una
        # hija sin planificar es un dato relevante para el usuario (fix M7).
        if depth > 30:
            _logger.warning(
                'MRP Reschedule: profundidad %s excedida en %s; hijas más profundas sin planificar',
                depth, mo.name,
            )
            if failures is not None:
                failures.append(_('%s (árbol demasiado profundo)') % (mo.name or ''))
            return

        child_mos = self._find_child_mos(mo, planned)
        # La hija debe terminar antes o cuando la madre empieza a consumir el componente
        parent_deadline = mo.date_start

        for child in child_mos:
            planned.add(child.id)

            if child.state == 'draft':
                try:
                    child.action_confirm()
                    child.invalidate_recordset()
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: no se pudo confirmar OF hija %s: %s',
                        child.name, e,
                    )
                    if failures is not None:
                        failures.append(child.name or child.product_id.display_name)
                    continue

            if child.workorder_ids:
                try:
                    # ALAP en tiempo hábil: ubicar el inicio para que la hija termine
                    # ~cuando la madre la consume (parent_deadline), a partir de la
                    # duración esperada de las OTs y el calendario del CT. Antes se
                    # hacían DOS button_plan (uno solo para medir la duración real);
                    # ahora la duración se estima sin planificar y se hace un único
                    # button_plan (fix M3). date_finished lo deriva Odoo de las OTs,
                    # sin pisarlo a mano (fix #7).
                    if parent_deadline:
                        dur_min = sum(child.workorder_ids.mapped('duration_expected')) or 0.0
                        if dur_min:
                            wc  = child.workorder_ids[:1].workcenter_id
                            cal = wc.resource_calendar_id or self.env.company.resource_calendar_id
                            target_start, _dummy = self._schedule_duration_backward(
                                cal, parent_deadline, dur_min / 60.0)
                            # No programar en el pasado si el deadline no es alcanzable.
                            target_start = max(target_start, fields.Datetime.now())
                            child.write({'date_start':    target_start,
                                         'date_deadline': parent_deadline})
                    child.button_plan()

                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: no se pudo planificar WOs de OF hija %s: %s',
                        child.name, e,
                    )
                    if failures is not None:
                        failures.append(child.name or child.product_id.display_name)

            self._plan_child_mos(child, planned, depth + 1, failures=failures)

    def action_plan_all_mos(self):
        """Botón 'Planificar OFs': llama button_plan() en todas las OFs del árbol
        (madres e hijas de todos los niveles). Útil para corregir OFs existentes
        o reforzar la planificación luego de cambios.
        """
        self.ensure_one()
        self._ensure_scheduling_group()
        mother_mos = self.item_ids.mapped('production_id').filtered(
            lambda m: m and m.state not in ('done', 'cancel')
        )
        if not mother_mos:
            return

        planned = set()
        plan_failures = []
        for mo in mother_mos:
            planned.add(mo.id)
            if mo.workorder_ids:
                try:
                    mo.button_plan()
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: no se pudo planificar %s: %s', mo.name, e,
                    )
                    plan_failures.append(mo.name or mo.product_id.display_name)
            self._plan_child_mos(mo, planned, failures=plan_failures)

        if plan_failures:
            self.message_post(body=_(
                'Replanificación: las siguientes OFs no se pudieron planificar '
                '(revisar carga/calendarios de sus centros de trabajo):'
            ) + '<br/>' + '<br/>'.join('• %s' % n for n in plan_failures))
