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
from odoo.exceptions import UserError

from .mrp_demand_expansion_mixin import MrpDemandExpansionMixin
from .mrp_demand_scheduling_mixin import MrpDemandSchedulingMixin

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
        domain=[('code', '=', 'mrp_operation')],
        required=True,
        # FIX [FASE-3]: el ID 518 era específico de la instancia de desarrollo; buscar por código
        default=lambda self: self.env['stock.picking.type'].search(
            [('code', '=', 'mrp_operation'), ('company_id', '=', self.env.company.id)], limit=1
        ),
        help='Tipo de operación de fabricación con el que se crearán las OFs.',
    )
    workorder_count = fields.Integer(
        compute='_compute_workorder_count', string='OTs',
        help='Cantidad total de órdenes de trabajo (work orders) de las OFs vinculadas.',
    )
    wc_load_ids     = fields.One2many('mrp.production.request.wc', 'request_id', string='Carga WC')

    @api.depends('item_ids.feasible', 'item_ids.earliest_end')
    def _compute_summary(self):
        """
        Calcula all_feasible y feasibility_summary para cada solicitud.

        Fórmula: cuenta artículos con earliest_end calculado y cuántos de ellos
        son feasible; construye un texto resumen del estado global.
        Depende de: item_ids.feasible, item_ids.earliest_end.
        """
        for rec in self:
            done = rec.item_ids.filtered('earliest_end')
            if not done:
                rec.all_feasible = False
                rec.feasibility_summary = _('Sin datos calculados')
                continue
            ok    = sum(1 for i in done if i.feasible)
            total = len(done)
            rec.all_feasible = ok == total
            rec.feasibility_summary = (
                _('Todos los artículos cumplen el plazo (%d/%d)') % (ok, total)
                if ok == total
                else _('%d de %d artículos no cumplen el plazo') % (total - ok, total)
            )

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

    def action_calculate(self):
        """
        Calcula el plan de fabricación para todos los artículos de la solicitud.

        Pasos:
        1. Preserva overrides de WC editados manualmente y limpia líneas anteriores.
        2. Determina el piso temporal (max entre start_from y hoy UTC).
        3. Construye el árbol de demanda multinivel para cada artículo.
        4. Obtiene los anclas de WC (carga existente en OFs confirmadas).
        5. Programa el árbol bottom-up compartiendo anclas entre artículos.
        6. Crea las líneas del plan y el resumen de carga por WC.
        7. Transiciona el estado a 'calculated'.

        :returns: dict — acción de ventana que recarga el formulario actual.
        :raises UserError: si no hay artículos o si algún artículo no tiene LdM.
        """
        self.ensure_one()
        if not self.item_ids:
            raise UserError(_('Agregue al menos un artículo.'))

        # Preservar WC editados manualmente antes de limpiar las líneas
        wc_overrides = {
            (l.item_id.id, l.product_id.id, l.level): l.workcenter_id
            for l in self.line_ids
            if l.workcenter_id and l.record_type == 'mrp'
        }
        self.line_ids.unlink()
        self.wc_load_ids.unlink()
        self.item_ids.write({'projected_end': False, 'projected_start': False})

        start = self.start_from or fields.Datetime.now()
        if hasattr(start, 'tzinfo') and start.tzinfo:
            start = start.astimezone(pytz.utc).replace(tzinfo=None)

        # Piso temporal: nada puede programarse antes de hoy (UTC midnight)
        today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        min_dt = max(start, today_utc)

        # Construir árbol de demanda para cada artículo (en orden de secuencia)
        missing = []
        item_trees = []
        for item in self.item_ids.sorted(lambda i: (i.sequence, i.id)):
            root = self._build_demand_tree(item.product_id, item.product_qty, level=0)
            if not root:
                missing.append(item.product_id.display_name)
            else:
                item_trees.append((item, root))

        if missing:
            raise UserError(_('Sin lista de materiales para: %s') % ', '.join(missing))

        # Aplicar WC editados manualmente en el cálculo anterior
        if wc_overrides:
            for item, root in item_trees:
                self._apply_wc_overrides(root, item.id, wc_overrides)

        # Anclas de WC: carga existente en la instancia
        all_roots  = [r for _, r in item_trees]
        wc_anchors = self._get_wc_anchors_multi(min_dt, all_roots)

        # Programar todos los artículos compartiendo los mismos anclas
        lines_vals = []
        seq = [10]
        for item, root in item_trees:
            self._schedule_tree(root, min_dt, wc_anchors, min_dt=min_dt)
            self._collect_lines(root, lines_vals, seq, item_id=item.id)
            earliest = root.get('scheduled_end')
            proj_start = self._get_tree_earliest_start(root)
            proj_end = item.date_deadline
            if earliest and proj_end and earliest > proj_end:
                proj_end = earliest
            item.write({
                'earliest_end':    earliest,
                'projected_start': proj_start,
                'projected_end':   proj_end,
            })

        for vals in lines_vals:
            vals['request_id'] = self.id
        if lines_vals:
            self.env['mrp.production.request.line'].create(lines_vals)

        # Resumen de carga por WC
        wc_data = {}
        for vals in lines_vals:
            wc_id = vals.get('workcenter_id')
            if not wc_id or vals.get('record_type') != 'mrp':
                continue
            if wc_id not in wc_data:
                wc_data[wc_id] = {'hours': 0.0, 'start': None, 'end': None}
            wc_data[wc_id]['hours'] += vals.get('duration_hours', 0.0)
            s = vals.get('new_date_start')
            e = vals.get('new_date_finish')
            if s:
                wc_data[wc_id]['start'] = min(wc_data[wc_id]['start'], s) if wc_data[wc_id]['start'] else s
            if e:
                wc_data[wc_id]['end'] = max(wc_data[wc_id]['end'], e) if wc_data[wc_id]['end'] else e
        if wc_data:
            self.env['mrp.production.request.wc'].create([
                {
                    'request_id':    self.id,
                    'workcenter_id': wc_id,
                    'total_hours':   round(data['hours'], 2),
                    'date_start':    data['start'],
                    'date_end':      data['end'],
                }
                for wc_id, data in sorted(
                    wc_data.items(),
                    key=lambda x: x[1]['start'] or datetime.min,
                )
            ])

        self.state = 'calculated'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new(self):
        """Vuelve a la lista para crear una nueva programación."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'list,form',
            'target': 'current',
        }

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
        """
        self.ensure_one()
        if self.state != 'calculated':
            raise UserError(_('Calcule primero el plan.'))

        created_ids = []
        mother_mos = self.env['mrp.production']

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
                    'product_id':    line.product_id.id,
                    'product_qty':   line.product_qty,
                    'date_start':    date_start,
                    'date_finished': target_finish,
                }
                if line.bom_id:
                    mo_vals['bom_id'] = line.bom_id.id
                if self.picking_type_id:
                    mo_vals['picking_type_id'] = self.picking_type_id.id

                mo = self.env['mrp.production'].create(mo_vals)
                mo.action_confirm()
                if mo.workorder_ids:
                    try:
                        mo.button_plan()
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: no se pudo planificar WOs de %s: %s',
                            mo.name, e,
                        )
                # button_plan() puede sobreescribir date_finished; restauramos.
                if target_finish:
                    mo.write({'date_finished': target_finish})
                item.write({'production_id': mo.id})
                created_ids.append(mo.id)
                mother_mos |= mo

        if not created_ids:
            raise UserError(_('No se pudo crear ninguna orden de fabricación.'))

        # Planificar recursivamente todas las OFs hijas generadas por Odoo
        planned = set(created_ids)
        for mo in mother_mos:
            self._plan_child_mos(mo, planned)

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

        # Estrategia 2: búsqueda por campo origin
        via_origin = self.env['mrp.production'].search([
            ('origin', 'ilike', mo.name),
            ('id', '!=', mo.id),
            ('id', 'not in', list(planned)),
            ('state', 'not in', ('done', 'cancel')),
        ])

        return (via_moves | via_origin).filtered(
            lambda m: m.state not in ('done', 'cancel')
        )

    def _plan_child_mos(self, mo, planned, depth=0):
        """Navega recursivamente el árbol de OFs hijas y planifica cada una.

        Llama button_plan() en cada OF hija y propaga las fechas hacia atrás:
        la hija debe terminar cuando la madre necesita empezar (mo.date_start).
        El parámetro `planned` evita bucles y trabajo doble en árboles con
        referencias cruzadas o reutilización de componentes.

        :param mo: mrp.production — OF padre desde la que se navega hacia abajo.
        :param planned: set[int] — IDs ya procesados; se modifica en-place.
        :param depth: int — profundidad actual de recursión (protección ante ciclos).
        """
        if depth > 15:  # Límite de seguridad ante árboles de LdM extraordinariamente profundos
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
                    continue

            if child.workorder_ids:
                try:
                    # Primera pasada: obtener duración real del scheduling
                    child.button_plan()

                    if (parent_deadline and child.date_start and child.date_finished
                            and child.date_finished < parent_deadline):
                        # Hay margen: desplazar para que la hija termine justo
                        # cuando la madre la necesita
                        duration = child.date_finished - child.date_start
                        target_finish = parent_deadline
                        target_start  = target_finish - duration
                        child.write({'date_start': target_start,
                                     'date_finished': target_finish})
                        # Segunda pasada: replanificar OTs desde el nuevo inicio
                        child.button_plan()
                        # button_plan puede volver a pisar date_finished; restaurar
                        child.write({'date_finished': target_finish})

                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: no se pudo planificar WOs de OF hija %s: %s',
                        child.name, e,
                    )

            self._plan_child_mos(child, planned, depth + 1)

    def action_plan_all_mos(self):
        """Botón 'Planificar OFs': llama button_plan() en todas las OFs del árbol
        (madres e hijas de todos los niveles). Útil para corregir OFs existentes
        o reforzar la planificación luego de cambios.
        """
        self.ensure_one()
        mother_mos = self.item_ids.mapped('production_id').filtered(
            lambda m: m and m.state not in ('done', 'cancel')
        )
        if not mother_mos:
            return

        planned = set()
        for mo in mother_mos:
            planned.add(mo.id)
            if mo.workorder_ids:
                try:
                    mo.button_plan()
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: no se pudo planificar %s: %s', mo.name, e,
                    )
            self._plan_child_mos(mo, planned)
