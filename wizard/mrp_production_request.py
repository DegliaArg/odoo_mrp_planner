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

from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import INDENT_MAP

_logger = logging.getLogger(__name__)


class MrpProductionRequest(models.Model):
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

    # ── Helpers — rutas y demanda ─────────────────────────────────────────────

    def _get_supply_method(self, product):
        """
        Determina cómo se abastece un producto según las rutas configuradas.

        Evalúa en orden de prioridad:
        1. Subcontratación: existe LdM de tipo 'subcontract'.
        2. Fabricación: alguna regla de ruta tiene action == 'manufacture'.
        3. Compra: alguna regla de ruta tiene action == 'buy'.
        4. Fallback por BOM genérica o purchase_ok.

        :param product: product.product — producto a evaluar.
        :returns: str — 'subcontract' | 'manufacture' | 'buy' | 'stock'.
        """
        # Subcontratación: tiene una LdM de tipo subcontract (máxima prioridad)
        sub_bom = self.env['mrp.bom'].search([
            ('type', '=', 'subcontract'),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ], limit=1)
        if sub_bom:
            return 'subcontract'

        # Rutas configuradas en el producto/categoría
        # Usar rule.action (campo semántico de Odoo 18) en lugar de picking_type_id.code,
        # que no es confiable con rutas personalizadas (ej. "Mecanizado: suministrar…").
        found = set()
        routes = product.route_ids | product.categ_id.total_route_ids
        for route in routes:
            for rule in route.rule_ids.filtered('active'):
                if rule.action == 'manufacture':
                    found.add('manufacture')
                elif rule.action == 'buy':
                    found.add('buy')
        if 'manufacture' in found:
            return 'manufacture'
        if 'buy' in found:
            return 'buy'

        # Fallback
        if self._find_bom(product):
            return 'manufacture'
        if product.purchase_ok:
            return 'buy'
        return 'stock'

    def _get_purchase_lead_days(self, product):
        """Retorna el plazo de entrega en días del proveedor principal del producto.

        Usa el delay del primer seller_id (menor sequence); si no hay sellers,
        cae a purchase_delay del producto o a 7 días por defecto.

        :param product: product.product — producto a consultar.
        :returns: int — días de plazo de entrega (mínimo 1).
        """
        if product.seller_ids:
            main = product.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
            if main:
                return int(main.delay or 0) or 1
        return int(getattr(product, 'purchase_delay', 0) or 7)

    def _find_bom(self, product):
        """Busca la LdM de fabricación activa para el producto dado.

        Intenta primero con el método oficial _bom_find de Odoo (robusto pero
        puede lanzar excepciones en versiones con API inestable); si falla,
        realiza una búsqueda directa excluyendo tipos 'phantom' y 'subcontract'.

        :param product: product.product — producto para el que se busca la LdM.
        :returns: mrp.bom — primera LdM encontrada, o recordset vacío si no existe.
        """
        try:
            result = self.env['mrp.bom']._bom_find(product, company_id=self.env.company.id)
            bom = result.get(product) if isinstance(result, dict) else result
            if bom:
                return bom
        except Exception:
            pass
        return self.env['mrp.bom'].search([
            ('type', 'not in', ['phantom', 'subcontract']),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ], limit=1, order='sequence, id')

    def _get_op_duration_hours(self, op, bom_factor):
        """Calcula la duración en horas de una operación de LdM escalada por bom_factor.

        Prioriza time_cycle_manual (ajuste manual) sobre time_cycle (calculado);
        si ambos son cero usa 60 minutos como mínimo operativo.

        :param op: mrp.routing.workcenter — operación de la LdM.
        :param bom_factor: float — factor de escala (qty_solicitada / bom.product_qty).
        :returns: float — duración en horas.
        """
        dur_min = (
            getattr(op, 'time_cycle_manual', None)
            or getattr(op, 'time_cycle', None)
            or 60.0
        )
        return dur_min * bom_factor / 60.0

    def _get_supplier_calendar(self, partner):
        """Devuelve el calendario del proveedor si está configurado; None si no."""
        if not partner:
            return None
        # Odoo estándar no tiene resource_calendar en res.partner, pero sí
        # cuando se instala el módulo HR y el proveedor tiene un empleado asociado.
        if hasattr(partner, 'resource_ids') and partner.resource_ids:
            cal = partner.resource_ids[:1].calendar_id
            if cal:
                return cal
        return None

    def _forward_schedule_days(self, calendar, from_dt, lead_days):
        """Avanza lead_days días hábiles hacia adelante desde from_dt.

        Retorna el inicio del primer turno del día resultante según el calendario.
        Si no hay calendario o lead_days <= 0, suma días naturales directamente.

        :param calendar: resource.calendar | None — calendario de trabajo a usar.
        :param from_dt: datetime — fecha de partida (UTC naive).
        :param lead_days: int — cantidad de días hábiles a avanzar.
        :returns: datetime — fecha de inicio del primer turno tras lead_days días hábiles.
        """
        if not calendar or lead_days <= 0:
            return from_dt + timedelta(days=lead_days or 0)

        dt = from_dt
        days_counted = 0
        max_iter = lead_days * 7 + 30  # margen extra para calendarios con muchos días festivos

        for _ in range(max_iter):
            if days_counted >= lead_days:
                break
            dt += timedelta(days=1)
            dt_date = dt.date()
            weekday = str(dt.weekday())
            if any(
                att.dayofweek == weekday
                and (not att.date_from or att.date_from <= dt_date)
                and (not att.date_to   or att.date_to   >= dt_date)
                for att in calendar.attendance_ids
            ):
                days_counted += 1

        dt_date = dt.date()
        weekday = str(dt.weekday())
        day_atts = sorted(
            [
                a for a in calendar.attendance_ids
                if a.dayofweek == weekday
                and (not a.date_from or a.date_from <= dt_date)
                and (not a.date_to   or a.date_to   >= dt_date)
            ],
            key=lambda a: a.hour_from,
        )
        if day_atts:
            h = day_atts[0].hour_from
            return dt.replace(
                hour=int(h), minute=int(round((h % 1) * 60)), second=0, microsecond=0
            )
        return dt.replace(hour=8, minute=0, second=0, microsecond=0)

    def _backward_schedule_days(self, calendar, before_dt, lead_days):
        """Retrocede lead_days días hábiles hacia atrás desde before_dt.

        Cae en el inicio del primer turno disponible del día resultante.
        Se usa para calcular cuándo debe pedirse un componente de compra/subcontrato
        dado que debe estar listo antes de before_dt.

        :param calendar: resource.calendar | None — calendario de trabajo a usar.
        :param before_dt: datetime — fecha límite de entrega (UTC naive).
        :param lead_days: int — cantidad de días hábiles a retroceder.
        :returns: datetime — fecha de inicio del turno tras retroceder lead_days días hábiles.
        """
        if not calendar or lead_days <= 0:
            return before_dt - timedelta(days=lead_days or 0)

        dt = before_dt
        days_counted = 0
        max_iter = lead_days * 7 + 30  # margen para calendarios con muchos días libres

        for _ in range(max_iter):
            if days_counted >= lead_days:
                break
            dt -= timedelta(days=1)
            dt_date = dt.date()
            weekday = str(dt.weekday())  # '0'=lunes, igual que att.dayofweek
            if any(
                att.dayofweek == weekday
                and (not att.date_from or att.date_from <= dt_date)
                and (not att.date_to   or att.date_to   >= dt_date)
                for att in calendar.attendance_ids
            ):
                days_counted += 1

        # Posicionar al inicio del primer turno del día resultante
        dt_date = dt.date()
        weekday = str(dt.weekday())
        day_atts = sorted(
            [
                a for a in calendar.attendance_ids
                if a.dayofweek == weekday
                and (not a.date_from or a.date_from <= dt_date)
                and (not a.date_to   or a.date_to   >= dt_date)
            ],
            key=lambda a: a.hour_from,
        )
        if day_atts:
            h = day_atts[0].hour_from
            return dt.replace(
                hour=int(h), minute=int(round((h % 1) * 60)), second=0, microsecond=0
            )
        return dt.replace(hour=8, minute=0, second=0, microsecond=0)

    def _get_tree_earliest_start(self, node):
        """Retorna el scheduled_start más temprano entre todos los nodos 'manufacture' del árbol.

        :param node: dict — nodo raíz del árbol de demanda.
        :returns: datetime | None — fecha de inicio más temprana, o None si no hay nodos programados.
        """
        result = None
        if node.get('type') == 'manufacture' and node.get('scheduled_start'):
            result = node['scheduled_start']
        for child in node.get('children', []):
            child_start = self._get_tree_earliest_start(child)
            if child_start:
                result = min(result, child_start) if result else child_start
        return result

    def _apply_wc_overrides(self, node, item_id, overrides):
        """Aplica los centros de trabajo editados manualmente al árbol de demanda.

        Reemplaza las operaciones del nodo con el WC guardado en overrides para la
        combinación (item_id, product.id, level). La duración total se preserva.

        :param node: dict — nodo del árbol a procesar (se modifica en-place).
        :param item_id: int — ID del mrp.production.request.item al que pertenece el árbol.
        :param overrides: dict — {(item_id, product_id, level): workcenter} con los overrides.
        """
        if node.get('type') == 'manufacture' and node.get('operations'):
            key = (item_id, node['product'].id, node['level'])
            if key in overrides:
                wc = overrides[key]
                dur_h = sum(d for _, d in node['operations'])
                node['operations'] = [(wc, dur_h)]
        for child in node.get('children', []):
            self._apply_wc_overrides(child, item_id, overrides)

    def _get_preferred_workcenter(self, product):
        """Devuelve el WC preferido activo del producto desde x_centros_compatibles.

        Si hay varios centros compatibles, prioriza el marcado como is_preferred;
        de lo contrario, toma el primero de la lista. Retorna None si no hay centros.

        :param product: product.product — producto a consultar.
        :returns: mrp.workcenter | None — centro de trabajo preferido, o None.
        """
        centros = product.product_tmpl_id.x_centros_compatibles.filtered('active')
        if not centros:
            return None
        preferred = centros.filtered('is_preferred')
        return (preferred[:1] if preferred else centros[:1]).workcenter_id or None

    def _build_demand_tree(self, product, qty, level, visited=None):
        """
        Construye recursivamente el árbol de demanda multinivel para un producto.

        Cada nodo del árbol es un dict con las claves: type, product, qty, bom,
        level, operations, children, scheduled_start, scheduled_end.
        Los tipos de nodo posibles son:
          - 'manufacture': se debe fabricar (nodo interno, puede tener hijos).
          - 'buy' / 'subcontract': se debe comprar/subcontratar (nodo hoja).
          - 'stock': cubierto por stock existente o reorden automático (nodo hoja).

        Para cada componente de la LdM se evalúa stock disponible primero; si
        hay stock parcial se genera un nodo stock por la parte cubierta y se
        continúa con el método de abastecimiento para el remanente.

        :param product: product.product — producto raíz o componente a evaluar.
        :param qty: float — cantidad necesaria a producir/abastecer.
        :param level: int — profundidad en el árbol (0 = artículo raíz de la solicitud).
        :param visited: set | None — productos ya visitados en la rama actual (evita ciclos).
        :returns: dict | None — nodo raíz del árbol, o None si no existe LdM fabricable.
        """
        if visited is None:
            visited = set()
        if product.id in visited:
            return None
        visited = visited | {product.id}

        bom = self._find_bom(product)
        if not bom or bom.type == 'phantom':
            return None  # No se puede fabricar el artículo raíz

        # Factor de corrección: cuántas corridas de LdM se necesitan para qty unidades.
        # bom.product_qty es cuántas unidades produce una corrida de la LdM.
        bom_factor = qty / (bom.product_qty or 1.0)

        preferred_wc = self._get_preferred_workcenter(product)
        wc_fallback = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.wc_fallback', 'ldm'
        )
        operations = []
        dur_bom = (
            sum(self._get_op_duration_hours(op, bom_factor) for op in bom.operation_ids)
            if bom.operation_ids else 8.0
        )
        if preferred_wc:
            operations = [(preferred_wc, dur_bom)]
        elif bom.operation_ids and wc_fallback == 'ldm':
            for op in bom.operation_ids.sorted('sequence'):
                operations.append((op.workcenter_id, self._get_op_duration_hours(op, bom_factor)))
        else:
            operations = [(None, dur_bom)]

        node = {
            'type':     'manufacture',
            'product':  product,
            'qty':      qty,
            'bom':      bom,
            'level':    level,
            'operations': operations,
            'children': [],
            'scheduled_start': None,
            'scheduled_end':   None,
        }

        for bom_line in bom.bom_line_ids:
            comp     = bom_line.product_id
            comp_qty = bom_line.product_qty * bom_factor

            # Productos con regla de reorden automática: el sistema los repone solo.
            # Generar un único nodo stock_ok para la cantidad total y saltar.
            if self.env['stock.warehouse.orderpoint'].search([
                ('product_id', '=', comp.id),
                ('active',     '=', True),
                ('trigger',    '=', 'auto'),
            ], limit=1):
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             comp_qty,
                    'level':           level + 1,
                    'warning_type':    'stock_ok',
                    'warning_message': 'Reposición automática (mín/máx)',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                continue

            # Verificar stock disponible antes de decidir el método de abastecimiento
            stock_avail = comp.qty_available or 0.0

            if stock_avail >= comp_qty:
                # Completamente cubierto por stock existente
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             comp_qty,
                    'level':           level + 1,
                    'warning_type':    'stock_ok',
                    'warning_message': f'En stock ({stock_avail:g} disponibles)',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                continue

            remaining_qty = comp_qty
            if stock_avail > 0:
                # Stock parcial: mostrar lo disponible y producir/comprar el resto
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             stock_avail,
                    'level':           level + 1,
                    'warning_type':    'stock_partial',
                    'warning_message': f'Stock parcial: {stock_avail:g} de {comp_qty:g}',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                remaining_qty = comp_qty - stock_avail

            method = self._get_supply_method(comp)

            if method == 'manufacture':
                child = self._build_demand_tree(comp, remaining_qty, level + 1, visited)
                if child:
                    node['children'].append(child)

            elif method in ('subcontract', 'buy'):
                lead_days    = self._get_purchase_lead_days(comp)
                seller_rec   = comp.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
                supplier_cal = self._get_supplier_calendar(
                    seller_rec.partner_id if seller_rec else self.env['res.partner']
                )
                node['children'].append({
                    'type':              method,
                    'product':           comp,
                    'qty':               remaining_qty,
                    'bom':               None,
                    'level':             level + 1,
                    'lead_days':         lead_days,
                    'supplier_name':     seller_rec.partner_id.display_name if seller_rec else '',
                    'supplier_calendar': supplier_cal,
                    'warning_type':      '',
                    'warning_message':   '',
                    'operations':        [],
                    'children':          [],
                    'scheduled_start':   None,
                    'scheduled_end':     None,
                })
            # method == 'stock' y sin stock: componente sin método conocido → omitir

        return node

    def _get_wc_anchors_multi(self, start, roots):
        """Construye el diccionario de anclas de WC a partir de la carga existente en Odoo.

        Para cada WC referenciado en los árboles, busca las OFs confirmadas/en progreso
        con work orders en ese WC y calcula cuándo termina el último trabajo planificado.
        Esto permite que la programación nueva se apile correctamente detrás de la carga
        ya existente sin generar solapamientos.

        :param start: datetime — fecha mínima de referencia (no se usa directamente,
                      pero orienta el contexto temporal del cálculo).
        :param roots: list[dict] — lista de nodos raíz de los árboles de demanda.
        :returns: dict — {workcenter_id: datetime} con la fecha fin más tardía por WC.
        """
        wc_ids = set()

        def _collect(node):
            for wc, _ in node['operations']:
                if wc:
                    wc_ids.add(wc.id)
            for child in node['children']:
                _collect(child)

        for root in roots:
            _collect(root)
        if not wc_ids:
            return {}

        anchors = {}
        for mo in self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('workorder_ids.workcenter_id', 'in', list(wc_ids)),
        ]):
            for wo in mo.workorder_ids:
                wc_id = wo.workcenter_id.id
                if wc_id not in wc_ids:
                    continue
                # Preferir la fecha real del WO; si no, la del MO; si no, estimarla
                wo_end = (
                    wo.date_finished
                    or mo.date_finished
                    or (mo.date_start + timedelta(hours=(wo.duration_expected or 60) / 60)
                        if mo.date_start else None)
                )
                if wo_end:
                    anchors[wc_id] = max(anchors.get(wc_id, wo_end), wo_end)
        return anchors

    def _schedule_tree(self, node, start, wc_anchors, min_dt=None):
        """Programa los nodos OF del árbol en orden bottom-up (primero las hojas).

        Los nodos OC/Subcont./compra se resuelven en un post-paso: su fecha de
        inicio se calcula retrocediendo lead_days desde el inicio de la OF padre.
        Los nodos stock son hojas sin fechas propias.

        La fecha de inicio de cada nodo OF respeta:
        - El fin del último hijo OF ya programado (dependencia de materiales).
        - El ancla actual del WC (carga existente más trabajos anteriores en este plan).
        - min_dt: piso global (no se puede programar antes de hoy).
        - Para hijos OC/Subcont.: se pushea after_dt para que la fecha de pedido
          no caiga antes de min_dt (no se puede pedir en el pasado).

        :param node: dict — nodo del árbol de demanda (se modifica en-place).
        :param start: datetime — fecha mínima de inicio para este nodo.
        :param wc_anchors: dict — {wc_id: datetime} anclas compartidas entre artículos.
        :param min_dt: datetime | None — piso temporal global (normalmente hoy UTC midnight).
        """
        leaf_types = ('purchase', 'subcontract', 'buy', 'stock')
        if node.get('type') in leaf_types:
            return  # Se resuelve desde el padre

        children_end = start
        for child in node['children']:
            if child.get('type') not in leaf_types:
                self._schedule_tree(child, start, wc_anchors, min_dt=min_dt)
                if child['scheduled_end']:
                    children_end = max(children_end, child['scheduled_end'])

        after_dt = max(start, children_end)
        if min_dt:
            after_dt = max(after_dt, min_dt)

        company_calendar = self.env.company.resource_calendar_id

        # Si algún hijo es compra/subcont., la OF no puede empezar antes de
        # min_dt + lead_days hábiles (no podemos pedir antes de hoy).
        if min_dt:
            for child in node['children']:
                if child.get('type') in ('purchase', 'subcontract', 'buy'):
                    lead = child.get('lead_days', 7)
                    cal  = child.get('supplier_calendar') or company_calendar
                    earliest_mo_start = self._forward_schedule_days(cal, min_dt, lead)
                    after_dt = max(after_dt, earliest_mo_start)

        node_start = None
        current    = after_dt

        for wc, dur_h in node['operations']:
            wc_id    = wc.id if wc else 0
            calendar = wc.resource_calendar_id if (wc and wc.resource_calendar_id) else company_calendar
            earliest       = max(current, wc_anchors.get(wc_id, after_dt))
            wo_start, wo_end = self._schedule_duration(calendar, earliest, dur_h)
            wc_anchors[wc_id] = wo_end
            if node_start is None:
                node_start = wo_start
            current = wo_end

        node['scheduled_start'] = node_start
        node['scheduled_end']   = current

        # Backward schedule OC/Subcont./compra desde el inicio de la OF.
        # Gracias al push forward de after_dt, la fecha de pedido siempre cae >= min_dt.
        for child in node['children']:
            if child.get('type') in ('purchase', 'subcontract', 'buy') and node_start:
                lead = child.get('lead_days', 7)
                cal  = child.get('supplier_calendar') or company_calendar
                child['scheduled_end']   = node_start
                raw_start = self._backward_schedule_days(cal, node_start, lead)
                child['scheduled_start'] = max(raw_start, min_dt) if min_dt else raw_start

    def _collect_lines(self, node, lines_vals, seq, item_id=None):
        """Convierte el árbol de demanda programado en una lista de dicts para crear líneas.

        Recorre el árbol en pre-orden (padre antes que hijos) y agrega un dict por
        nodo a lines_vals. Los nodos OC/stock son hojas (no tienen hijos que procesar).
        Los nodos OF continúan la recursión para agregar sus componentes.

        :param node: dict — nodo del árbol de demanda ya programado.
        :param lines_vals: list[dict] — lista acumuladora de valores para crear líneas.
        :param seq: list[int] — lista de un elemento usado como contador de secuencia
                    mutable (trick para pasar por referencia en recursión).
        :param item_id: int | None — ID del mrp.production.request.item al que pertenece.
        """
        indent    = INDENT_MAP.get(node['level'], ' ' * 9 + '└─ ')
        product   = node['product']
        node_type = node.get('type', 'manufacture')

        if node_type in ('purchase', 'subcontract', 'buy'):
            lines_vals.append({
                'sequence':          seq[0],
                'level':             node['level'],
                'item_id':           item_id,
                'record_type':       'purchase',
                'product_id':        product.id,
                'bom_id':            False,
                'product_qty':       node['qty'],
                'duration_hours':    0.0,
                'new_date_start':    node['scheduled_start'],
                'new_date_finish':   node['scheduled_end'],
                'workcenter_label':  node.get('supplier_name', ''),
                'description_label': f'{indent}{product.display_name}',
                'type_label':        'Subcont.' if node_type == 'subcontract' else 'OC',
                'warning_type':      node.get('warning_type', ''),
                'warning_message':   node.get('warning_message', ''),
            })
            seq[0] += 10
            return  # Nodo hoja

        if node_type == 'stock':
            wt = node.get('warning_type', 'stock_ok')
            lines_vals.append({
                'sequence':          seq[0],
                'level':             node['level'],
                'item_id':           item_id,
                'record_type':       'stock',
                'product_id':        product.id,
                'bom_id':            False,
                'product_qty':       node['qty'],
                'duration_hours':    0.0,
                'new_date_start':    None,
                'new_date_finish':   None,
                'workcenter_label':  '',
                'description_label': f'{indent}{product.display_name}',
                'type_label':        'Stock',
                'warning_type':      wt,
                'warning_message':   node.get('warning_message', ''),
                'is_auto_reorder':   wt == 'stock_ok',
            })
            seq[0] += 10
            return  # Nodo hoja

        # Nodo OF
        ops      = node['operations']
        wcs      = [wc for wc, _ in ops if wc]
        wc_label = ' › '.join(wc.name for wc in wcs) if wcs else ''
        dur_h    = sum(d for _, d in ops)

        lines_vals.append({
            'sequence':          seq[0],
            'level':             node['level'],
            'item_id':           item_id,
            'record_type':       'mrp',
            'product_id':        product.id,
            'bom_id':            node['bom'].id if node.get('bom') else False,
            'product_qty':       node['qty'],
            'duration_hours':    round(dur_h, 2),
            'new_date_start':    node['scheduled_start'],
            'new_date_finish':   node['scheduled_end'],
            'workcenter_id':     wcs[0].id if wcs else False,
            'workcenter_chain':  wc_label if len(wcs) > 1 else '',
            'workcenter_label':  '',
            'description_label': f'{indent}{product.display_name}',
            'type_label':        'OF' if node['level'] == 0 else 'OF hija',
            'warning_type':      '',
            'warning_message':   '',
        })
        seq[0] += 10

        for child in node['children']:
            self._collect_lines(child, lines_vals, seq, item_id=item_id)
