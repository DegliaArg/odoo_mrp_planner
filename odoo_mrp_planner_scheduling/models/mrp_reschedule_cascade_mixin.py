"""
Mixin: MrpRescheduleCascadeMixin

Motor de cálculo de la cascada de reprogramación.

Responsabilidades:
- Calcular el delta de desplazamiento entre la fecha nueva y la planificada.
- Obtener las MOs dependientes (en cascada) de una orden pivot o todas las activas.
- Buscar las POs vinculadas a una MO.
- Recorrer el árbol de hijas directas de una MO.
- Estimar duración y resolver calendario de una MO.
- Programar un bloque de MO respetando la disponibilidad de cada centro de trabajo.
- Ordenar MOs por estrategia de prioridad (cronológica, más corta, manual).
- Construir en batch las líneas MrpReschedulePlanLine y MrpReschedulePlanWcLine.
"""

import logging
import pytz
from collections import deque
from datetime import datetime, timedelta

from odoo import models, fields, _


_logger = logging.getLogger(__name__)

# Límite de profundidad del árbol de cascada para evitar bucles infinitos en
# estructuras de producto con referencias circulares o jerarquías muy profundas.
MAX_DEPTH = 30


def _get_old_code(mo):
    """
    Devuelve x_studio_cdigo_viejo (campo Studio en product.template) para una
    mrp.production.  La delegación de herencia de Odoo no propaga el campo al
    _fields de product.product, por eso buscamos en product_tmpl_id._fields.
    Retorna '' si el campo no existe en la instancia.
    """
    # 1. Directo en la orden de fabricación (por si Studio lo puso ahí)
    if 'x_studio_cdigo_viejo' in mo._fields:
        return mo.x_studio_cdigo_viejo or ''
    # 2. En product.template vía product_id.product_tmpl_id
    product = getattr(mo, 'product_id', None)
    if product:
        tmpl = getattr(product, 'product_tmpl_id', None)
        if tmpl and 'x_studio_cdigo_viejo' in tmpl._fields:
            return tmpl.x_studio_cdigo_viejo or ''
    return ''


# Traducciones de estados técnicos de mrp.production para mostrar en la vista.
MRP_STATES = {
    'draft': 'Borrador', 'confirmed': 'Confirmado', 'progress': 'En proceso',
    'to_close': 'Por cerrar', 'done': 'Hecho', 'cancel': 'Cancelado',
}
# Traducciones de estados técnicos de purchase.order para mostrar en la vista.
PO_STATES = {
    'draft': 'Presupuesto', 'sent': 'Enviado', 'to approve': 'Por aprobar',
    'purchase': 'OC confirmada', 'done': 'Bloqueado', 'cancel': 'Cancelado',
}


class MrpRescheduleCascadeMixin(models.AbstractModel):
    _name = 'mrp.reschedule.cascade.mixin'
    _description = 'Mixin de cálculo de cascada de reprogramación'

    # ── Helpers — consultas ──────────────────────────────────────────────────

    def _get_delta(self):
        """Retorna el timedelta entre new_finish_date y la fecha_finished actual del pivot."""
        self.ensure_one()
        planned = self.production_id.date_finished
        if not planned or not self.new_finish_date:
            return timedelta(0)
        return self.new_finish_date - planned

    def _get_subsequent_mos(self):
        """
        Obtiene todas las MOs dependientes de la orden pivot en modo pivot.

        Busca en tres niveles:
        - Nivel 1: MOs con x_parent_mo_id apuntando al pivot (hijas directas).
        - Nivel 2: MOs que consumen el producto del pivot como materia prima y
          tienen fecha de inicio igual o posterior al pivot.
        - Nivel 3: MOs que comparten centros de trabajo con el pivot y tienen
          fecha de inicio igual o posterior (solo si include_wc_heuristic=True).

        :returns: recordset de mrp.production ordenado por date_start, id.
        """
        pivot = self.production_id
        if not pivot:
            return self.env['mrp.production']

        result = self.env['mrp.production']

        # Level 1: OFs with x_parent_mo_id pointing to pivot
        level1 = self.env['mrp.production'].search([
            ('x_parent_mo_id', '=', pivot.id),
            ('state', 'not in', ['done', 'cancel']),
        ])
        result |= level1

        # Level 2: OFs that consume pivot's product as a raw component
        if pivot.product_id:
            if pivot.date_start:
                level2 = self.env['mrp.production'].search([
                    ('id', '!=', pivot.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('move_raw_ids.product_id', '=', pivot.product_id.id),
                    ('date_start', '!=', False),
                    ('date_start', '>=', pivot.date_start),
                ])
            else:
                level2 = self.env['mrp.production'].search([
                    ('id', '!=', pivot.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('move_raw_ids.product_id', '=', pivot.product_id.id),
                ])
            result |= level2

        # Level 3: WC-shared (only if config.include_wc_heuristic = True)
        cfg = self.env['mrp.reschedule.config'].get_config()
        if cfg and cfg.include_wc_heuristic:
            wc_ids = pivot.workorder_ids.mapped('workcenter_id').ids
            if wc_ids and pivot.date_start:
                level3 = self.env['mrp.production'].search([
                    ('id', '!=', pivot.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('date_start', '!=', False),
                    ('date_start', '>=', pivot.date_start),
                    ('workorder_ids.workcenter_id', 'in', wc_ids),
                ])
                result |= level3

        # Filter out the pivot itself and return sorted
        result = result.filtered(lambda m: m.id != pivot.id)
        return result.sorted(key=lambda m: (m.date_start or fields.Datetime.now(), m.id))

    def _get_all_active_mos(self):
        """Modo global: solo MOs confirmadas (pendientes de iniciar) con fecha de inicio."""
        return self.env['mrp.production'].search([
            ('state', '=', 'confirmed'),
            ('date_start', '!=', False),
        ], order='date_start, id')

    def _get_pos_for_mo(self, mo):
        """
        Busca las órdenes de compra no finalizadas vinculadas a una MO.

        Busca en tres fuentes complementarias:
        - Campo purchase_order_id directamente en la MO (si existe).
        - Campo purchase_line_id en la MO (si existe).
        - Campo origin de purchase.order que contenga el nombre de la MO.

        :param mo: mrp.production — orden de fabricación de referencia.
        :returns: recordset de purchase.order con estado distinto de done/cancel.
        """
        pos = self.env['purchase.order']
        mo_fields = mo._fields
        if 'purchase_order_id' in mo_fields:
            po = mo.purchase_order_id
            if po and po.state not in ('done', 'cancel'):
                pos |= po
        if 'purchase_line_id' in mo_fields:
            line = mo.purchase_line_id
            if line and line.order_id and line.order_id.state not in ('done', 'cancel'):
                pos |= line.order_id
        if mo.name:
            pos |= self.env['purchase.order'].search([
                ('origin', 'ilike', mo.name),
                ('state', 'not in', ('done', 'cancel')),
            ])
        return pos

    def _get_child_mos(self, mo):
        """
        Retorna las MOs hijas directas de una MO padre.

        Busca por x_parent_mo_id y también por origin (para MOs generadas
        automáticamente desde el módulo de planificación sin campo Studio).

        :param mo: mrp.production — orden padre.
        :returns: recordset de mrp.production activas (excluye done/cancel).
        """
        children = self.env['mrp.production'].search([
            ('x_parent_mo_id', '=', mo.id),
            ('state', 'not in', ['done', 'cancel']),
        ])
        if mo.name:
            children |= self.env['mrp.production'].search([
                ('origin', '=', mo.name),
                ('x_parent_mo_id', '=', False),
                ('state', 'not in', ['done', 'cancel']),
            ])
        return children

    def _preload_child_mos_batch(self, parent_ids, visited_mo_ids=None):
        """
        Carga en una sola query todas las MOs hijas para un conjunto de IDs padre.

        Equivalente a llamar _get_child_mos() para cada ID individualmente,
        pero en batch para minimizar el número de queries SQL durante el BFS.

        :param parent_ids: colección de IDs de mrp.production padre.
        :param visited_mo_ids: set opcional de IDs ya visitados — se excluyen
            del resultado para evitar re-encolar nodos ya procesados.
        :returns: dict {parent_id: [mrp.production recordsets]} (lista de registros).
        """
        parent_ids = list(parent_ids)
        if not parent_ids:
            return {}
        visited = visited_mo_ids or set()
        result = {}

        # Hijas por x_parent_mo_id (campo Studio)
        by_parent = self.env['mrp.production'].search([
            ('x_parent_mo_id', 'in', parent_ids),
            ('state', 'not in', ['done', 'cancel']),
        ])
        for child in by_parent:
            if child.id not in visited:
                pid = child.x_parent_mo_id.id
                result.setdefault(pid, self.env['mrp.production'])
                result[pid] |= child

        # Hijas por origin = mo.name (MOs generadas sin campo Studio)
        # Necesitamos el mapa id->name de los padres
        parent_recs = self.env['mrp.production'].browse(parent_ids)
        name_to_parent_id = {
            mo.name: mo.id for mo in parent_recs if mo.name
        }
        if name_to_parent_id:
            by_origin = self.env['mrp.production'].search([
                ('origin', 'in', list(name_to_parent_id.keys())),
                ('x_parent_mo_id', '=', False),
                ('state', 'not in', ['done', 'cancel']),
            ])
            for child in by_origin:
                if child.id not in visited and child.origin in name_to_parent_id:
                    pid = name_to_parent_id[child.origin]
                    result.setdefault(pid, self.env['mrp.production'])
                    result[pid] |= child

        return result

    def _preload_pos_batch(self, mo_list):
        """
        Carga en una sola query todas las POs vinculadas a un conjunto de MOs.

        Equivalente a llamar _get_pos_for_mo() para cada MO individualmente,
        pero en batch. Usa la misma lógica de tres fuentes que _get_pos_for_mo.

        :param mo_list: iterable de mrp.production.
        :returns: dict {mo_id: purchase.order recordset}.
        """
        result = {}
        if not mo_list:
            return result

        mo_ids = [mo.id for mo in mo_list]
        mo_by_id = {mo.id: mo for mo in mo_list}

        # Fuente 1: purchase_order_id directo en la MO
        if mo_list and 'purchase_order_id' in next(iter(mo_list))._fields:
            for mo in mo_list:
                po = mo.purchase_order_id
                if po and po.state not in ('done', 'cancel'):
                    result.setdefault(mo.id, self.env['purchase.order'])
                    result[mo.id] |= po

        # Fuente 2: purchase_line_id en la MO
        if mo_list and 'purchase_line_id' in next(iter(mo_list))._fields:
            for mo in mo_list:
                line = mo.purchase_line_id
                if line and line.order_id and line.order_id.state not in ('done', 'cancel'):
                    result.setdefault(mo.id, self.env['purchase.order'])
                    result[mo.id] |= line.order_id

        # Fuente 3: purchase.order cuyo origin contiene el nombre de la MO (batch)
        mo_names = [mo.name for mo in mo_list if mo.name]
        name_to_mo_ids = {}
        for mo in mo_list:
            if mo.name:
                name_to_mo_ids.setdefault(mo.name, []).append(mo.id)

        if mo_names:
            pos_by_origin = self.env['purchase.order'].search([
                ('origin', 'in', mo_names),
                ('state', 'not in', ('done', 'cancel')),
            ])
            for po in pos_by_origin:
                for mo_id in name_to_mo_ids.get(po.origin, []):
                    result.setdefault(mo_id, self.env['purchase.order'])
                    result[mo_id] |= po

        return result

    # ── Helpers — calendario ─────────────────────────────────────────────────

    def _get_mo_duration_hours(self, mo):
        """
        Estima la duración en horas de una MO para usarla como bloque en el calendario.

        Prioridad: suma de duration_expected de WOs (en minutos → horas) >
        diferencia real entre date_start y date_finished > valor por defecto de 8h.

        :param mo: mrp.production — orden a evaluar.
        :returns: float con la duración estimada en horas.
        """
        if mo.workorder_ids:
            total = sum(wo.duration_expected or 0.0 for wo in mo.workorder_ids)
            if total > 0:
                return total / 60.0
        if mo.date_start and mo.date_finished and mo.date_finished > mo.date_start:
            return (mo.date_finished - mo.date_start).total_seconds() / 3600.0
        return 8.0  # Fallback: jornada laboral estándar cuando no hay datos de duración

    def _get_mo_calendar(self, mo, pivot_wc_ids=None):
        """
        Resuelve el calendario de recursos más apropiado para programar una MO.

        Prioridad: WC compartido con el pivot que tenga calendario propio >
        primer WC de la MO (por secuencia) con calendario propio >
        calendario de la compañía como fallback.

        :param mo: mrp.production — orden a evaluar.
        :param pivot_wc_ids: set de IDs de workcenters del pivot para preferencia.
        :returns: resource.calendar vinculado al workcenter o a la compañía.
        """
        pivot_wc_ids = set(pivot_wc_ids or [])
        if mo.workorder_ids:
            if pivot_wc_ids:
                shared = mo.workorder_ids.mapped('workcenter_id').filtered(
                    lambda wc: wc.id in pivot_wc_ids and wc.resource_calendar_id
                )
                if shared:
                    return shared[0].resource_calendar_id
            for wo in mo.workorder_ids.sorted('sequence'):
                if wo.workcenter_id.resource_calendar_id:
                    return wo.workcenter_id.resource_calendar_id
        return self.env.company.resource_calendar_id

    def _schedule_mo_block(self, mo, wc_anchors, base_dt, duration_override=None, wc_collector=None):
        """
        Programa un bloque de MO respetando la disponibilidad de cada centro de trabajo.

        Si la MO no tiene WOs, la trata como un bloque único usando el calendario de
        la compañía. Si tiene WOs, las programa en secuencia escalando las duraciones
        proporcionalmente si se especifica duration_override.

        Actualiza wc_anchors in-place para que el próximo bloque en ese WC empiece
        después de que este termine.

        :param mo: mrp.production — orden a programar.
        :param wc_anchors: dict {workcenter_id: datetime} con el último fin ocupado por WC.
        :param base_dt: datetime — fecha mínima de inicio para esta MO.
        :param duration_override: float opcional — duración total en horas que reemplaza
            la suma de WOs (se redistribuye proporcionalmente entre ellas).
        :param wc_collector: list opcional — si se pasa, se agregan dicts con los rangos
            de cada WO para crear MrpReschedulePlanWcLine.
        :returns: tuple (new_date_start, new_date_finish) como datetimes UTC naive.
        """
        wos = mo.workorder_ids.sorted('sequence')
        total_wo_dur = sum(wo.duration_expected or 0.0 for wo in wos)

        if not wos or total_wo_dur <= 0:
            calendar = self._get_mo_calendar(mo)
            duration_h = duration_override or self._get_mo_duration_hours(mo)
            wc_times = [wc_anchors.get(wc.id, base_dt)
                        for wc in mo.workorder_ids.mapped('workcenter_id')]
            start_from = max([base_dt] + wc_times)
            wo_start, wo_end = self._schedule_duration(calendar, start_from, duration_h)
            for wc in mo.workorder_ids.mapped('workcenter_id'):
                wc_anchors[wc.id] = max(wc_anchors.get(wc.id, wo_end), wo_end)
            return (wo_start, wo_end)

        mo_start = None
        wo_prev_end = base_dt
        scale = (duration_override / (total_wo_dur / 60.0)
                 if duration_override and total_wo_dur > 0 else None)

        for wo in wos:
            wc = wo.workcenter_id
            wc_id = wc.id if wc else 0
            calendar = (
                wc.resource_calendar_id if wc and wc.resource_calendar_id
                else self.env.company.resource_calendar_id
            )
            wo_dur_h = (wo.duration_expected or 60.0) / 60.0
            if scale is not None:
                wo_dur_h *= scale
            earliest = max(wo_prev_end, wc_anchors.get(wc_id, base_dt), base_dt)
            wo_start, wo_end = self._schedule_duration(calendar, earliest, wo_dur_h)
            wc_anchors[wc_id] = wo_end
            if wc_collector is not None and wc_id and wo_start and wo_end:
                wc_collector.append({
                    'production_id': mo.id,
                    'workorder_id':  wo.id,
                    'workcenter_id': wc_id,
                    'new_date_start':  wo_start,
                    'new_date_finish': wo_end,
                })
            if mo_start is None:
                mo_start = wo_start
            wo_prev_end = wo_end

        return (mo_start, wo_prev_end)

    def _sort_mos_by_priority(self, mos, sequence_overrides=None):
        """
        Ordena una lista de MOs según la estrategia de prioridad configurada en el sistema.

        Estrategias soportadas:
        - 'chronological' (default): por date_start ASC, luego id ASC.
        - 'shortest_first': por duración estimada ASC, luego date_start ASC.
        - 'manual': por secuencia en sequence_overrides, luego date_start ASC.

        :param mos: iterable de mrp.production.
        :param sequence_overrides: dict {production_id: int} con orden manual opcional.
        :returns: lista de mrp.production ordenada.
        """
        company_id = self.env.company.id
        # sudo(): ir.config_parameter requiere admin; se lee aquí desde el mixin de cascada sin usuario admin
        priority = (
            self.env['ir.config_parameter'].sudo().get_param(
                f'mrp_reschedule.priority.{company_id}'
            )
            or self.env['ir.config_parameter'].sudo().get_param(
                'mrp_reschedule.priority', 'chronological'
            )
        )
        seq_map = sequence_overrides or {}
        dt_max = datetime(9999, 12, 31)  # Centinela para MOs sin fecha de inicio (van al final)
        if priority == 'shortest_first':
            return sorted(mos, key=lambda m: (
                self._get_mo_duration_hours(m), m.date_start or dt_max,
            ))
        elif priority == 'manual' and seq_map:
            return sorted(mos, key=lambda m: (
                seq_map.get(m.id, 9999), m.date_start or dt_max,
            ))
        return sorted(mos, key=lambda m: (m.date_start or dt_max, m.id))

    # ── Construcción de líneas ────────────────────────────────────────────────

    def _build_lines(self):
        """
        Construye todas las líneas del plan (MrpReschedulePlanLine y MrpReschedulePlanWcLine).

        Algoritmo iterativo BFS (usando deque) que recorre el árbol de MOs en cascada:
        1. Recoge overrides existentes en las líneas previas (duración, ancla, secuencia,
           inicio forzado) para que el recálculo los respete.
        2. Elimina líneas y líneas WC anteriores.
        3. Inicializa wc_anchors con los WCs del pivot (modo pivot) o vacío (modo global).
        4. Pre-carga en wc_anchors las MOs en estado 'progress' para respetar la
           capacidad ya comprometida.
        5. Procesa cada MO de la cola:
           - Anclas: mantienen sus fechas actuales (o aplican inicio forzado con calendario).
           - Nivel 0: se programan desde base_dt usando _schedule_mo_block.
           - Nivel > 0: se desplazan según el delta del padre y se ajustan al calendario.
        6. Para cada MO procesada, agrega las POs vinculadas con el mismo desplazamiento.
        7. Encola las MOs hijas para procesamiento en profundidad.
        8. Crea los registros en batch al final para minimizar queries.

        Optimización de queries (preload por nivel):
        - En lugar de llamar _get_child_mos() y _get_pos_for_mo() por cada nodo
          individualmente (N+1 queries), se usan _preload_child_mos_batch() y
          _preload_pos_batch() para cargar todos los datos del nivel actual en
          una sola query antes de procesar sus nodos.
        - Las POs se precargan para el nivel raíz al inicio y luego, cuando se
          descubren hijos nuevos al cerrar cada nivel, se precarga el nivel siguiente.

        :raises nada directamente — los errores de profundidad se registran en _logger.
        """
        self.ensure_one()
        pivot = self.production_id
        is_global = not pivot

        duration_overrides = {}
        anchor_overrides = {}
        sequence_overrides = {}
        forced_start_overrides = {}
        for line in self.line_ids:
            if line.record_type == 'mrp' and line.production_id:
                pid = line.production_id.id
                if line.duration_hours > 0:
                    duration_overrides[pid] = line.duration_hours
                anchor_overrides[pid] = line.is_anchor
                if line.reschedule_sequence:
                    sequence_overrides[pid] = line.reschedule_sequence
                if line.forced_start_date:
                    forced_start_overrides[pid] = line.forced_start_date

        self.line_ids.unlink()
        self.wc_line_ids.unlink()

        lines_vals = []
        wc_lines_data = []
        seq = 10
        visited_mo_ids = set()
        visited_po_ids = set()

        # En modo pivot el pivot es siempre un anchor (punto fijo de referencia)
        if pivot:
            anchor_overrides.setdefault(pivot.id, True)

        if is_global:
            base_dt = self.replan_from or fields.Datetime.now()
            if hasattr(base_dt, 'tzinfo') and base_dt.tzinfo:
                base_dt = base_dt.astimezone(pytz.utc).replace(tzinfo=None)
            subsequent_mos = self._get_all_active_mos()
            wc_anchors = {}
            pivot_wc_ids = set()
        else:
            base_dt = self.new_finish_date
            subsequent_mos = self._get_subsequent_mos()
            pivot_wc_ids = set(pivot.workorder_ids.mapped('workcenter_id').ids)
            wc_anchors = {wc_id: base_dt for wc_id in pivot_wc_ids}

        all_wc_ids = set(pivot_wc_ids)
        for mo in subsequent_mos:
            all_wc_ids |= set(mo.workorder_ids.mapped('workcenter_id').ids)

        if all_wc_ids:
            exclude_ids = ([] if is_global else [pivot.id]) + subsequent_mos.ids
            in_progress = self.env['mrp.production'].search([
                ('id', 'not in', exclude_ids),
                ('state', '=', 'progress'),
                ('workorder_ids.workcenter_id', 'in', list(all_wc_ids)),
            ])
            for mo in in_progress:
                est = mo.date_finished or (
                    mo.date_start + timedelta(hours=self._get_mo_duration_hours(mo))
                    if mo.date_start else None
                )
                if est:
                    for wo in mo.workorder_ids:
                        wc_id = wo.workcenter_id.id
                        if wc_id in all_wc_ids:
                            wc_anchors[wc_id] = max(wc_anchors.get(wc_id, est), est)

        mos_sorted = self._sort_mos_by_priority(subsequent_mos, sequence_overrides)

        root_label = pivot.name if pivot else ''
        truncated_mo_ids = []

        # ── BFS con preload por nivel ─────────────────────────────────────────
        # Cada ítem de la cola: (mo, level, parent_label, parent_delta)
        # Se mantiene un cache de hijos (child_cache) y POs (po_cache) que se
        # recarga en batch cada vez que se descubren MOs de un nivel nuevo.
        queue = deque()

        # Cache de hijos precargados: {parent_mo_id: recordset de hijas}
        child_cache = {}
        # Cache de POs precargadas: {mo_id: recordset de POs}
        po_cache = {}

        # Construir lista raíz de MOs y precargar sus datos en batch
        root_mos = []
        if not is_global and pivot:
            root_mos.append(pivot)
        for mo in mos_sorted:
            if mo.id not in visited_mo_ids:
                root_mos.append(mo)

        if root_mos:
            # Preload hijos y POs del nivel raíz en 2 queries (en lugar de 2*N)
            child_cache.update(self._preload_child_mos_batch(
                [mo.id for mo in root_mos], visited_mo_ids
            ))
            po_cache.update(self._preload_pos_batch(root_mos))

        # Encolar nivel raíz
        if not is_global and pivot:
            queue.append((pivot, 0, '', None))
        for mo in mos_sorted:
            if mo.id not in visited_mo_ids:
                queue.append((mo, 0, root_label, None))

        while queue:
            mo, level, parent_label, parent_delta = queue.popleft()

            if mo.id in visited_mo_ids:
                continue

            if level > MAX_DEPTH:
                truncated_mo_ids.append(mo.id)
                lines_vals.append({
                    'plan_id':             self.id,
                    'sequence':            seq,
                    'reschedule_sequence': seq,
                    'record_type':         'mrp',
                    'production_id':       mo.id,
                    'level':               level,
                    'parent_label':        parent_label,
                    'duration_hours':      0.0,
                    'is_anchor':           False,
                    'forced_start_date':   False,
                    'current_date_start':  mo.date_start,
                    'current_date_finish': mo.date_finished,
                    'new_date_start':      False,
                    'new_date_finish':     False,
                    'warning_type':        False,
                    'warning_message':     _('Profundidad máxima alcanzada — revisar manualmente'),
                    'apply':               False,
                })
                seq += 10
                continue

            visited_mo_ids.add(mo.id)

            is_anchor    = anchor_overrides.get(mo.id, mo.state in ('done', 'progress', 'to_close'))
            forced_start = forced_start_overrides.get(mo.id)
            duration_h   = duration_overrides.get(mo.id) or self._get_mo_duration_hours(mo)
            warning_type = False
            warning_msg  = ''

            if is_anchor:
                if forced_start:
                    # Anchor con inicio forzado: calcular fin respetando calendario
                    calendar = self._get_mo_calendar(mo)
                    new_start, new_end = self._schedule_duration(
                        calendar, forced_start, duration_h
                    )
                else:
                    new_start = mo.date_start
                    new_end   = mo.date_finished
                    if not new_end and mo.date_start:
                        new_end = mo.date_start + timedelta(hours=duration_h)
                if new_end:
                    for wo in mo.workorder_ids:
                        wc_id = wo.workcenter_id.id
                        if wc_id:
                            wc_anchors[wc_id] = max(wc_anchors.get(wc_id, new_end), new_end)
            elif level == 0:
                new_start, new_end = self._schedule_mo_block(
                    mo, wc_anchors, base_dt, duration_override=duration_h,
                    wc_collector=wc_lines_data,
                )
            else:
                pd = parent_delta or timedelta(0)
                proposed_start = (mo.date_start + pd) if mo.date_start else base_dt
                child_wc_anchors = dict(wc_anchors)
                new_start, new_end = self._schedule_mo_block(
                    mo, child_wc_anchors, proposed_start, duration_override=duration_h,
                    wc_collector=wc_lines_data,
                )
                if mo.date_start and abs((new_start - proposed_start).total_seconds()) > 900:
                    warning_type = 'child_adjusted'
                    warning_msg = _(
                        'Ajustada al primer turno disponible (propuesta: %s)'
                    ) % proposed_start.strftime('%d/%m %H:%M')

            mo_delta = (
                (new_start - mo.date_start)
                if (new_start and mo.date_start) else timedelta(0)
            )

            lines_vals.append({
                'plan_id':             self.id,
                'sequence':            seq,
                'reschedule_sequence': sequence_overrides.get(mo.id, seq),
                'record_type':         'mrp',
                'production_id':       mo.id,
                'level':               level,
                'parent_label':        parent_label,
                'duration_hours':      duration_h,
                'is_anchor':           is_anchor,
                'forced_start_date':   forced_start or False,
                'current_date_start':  mo.date_start,
                'current_date_finish': mo.date_finished,
                'new_date_start':      new_start,
                'new_date_finish':     new_end,
                'warning_type':        warning_type,
                'warning_message':     warning_msg,
                # Aplicar si no es anchor, O si es anchor con inicio forzado
                'apply':               not is_anchor or bool(forced_start),
            })
            seq += 10

            # POs del nodo actual — usar cache precargado (fallback a consulta individual
            # solo si el ID no estaba en el cache, lo cual no debería ocurrir normalmente)
            mo_pos = po_cache.get(mo.id, self.env['purchase.order'])
            for po in mo_pos:
                if po.id in visited_po_ids:
                    continue
                visited_po_ids.add(po.id)
                new_po_finish = (po.date_planned + mo_delta) if po.date_planned else False
                po_warn = po.state in ('purchase', 'done')
                lines_vals.append({
                    'plan_id':             self.id,
                    'sequence':            seq,
                    'reschedule_sequence': seq,
                    'record_type':         'purchase',
                    'purchase_id':         po.id,
                    'level':               level + 1,
                    'parent_label':        mo.name,
                    'duration_hours':      0.0,
                    'is_anchor':           False,
                    'current_date_start':  po.date_order,
                    'current_date_finish': po.date_planned,
                    'new_date_start':      False,
                    'new_date_finish':     new_po_finish,
                    'warning_type':        'confirmed_po' if po_warn else False,
                    'warning_message':     (
                        _('OC en estado "%s" — revisar con proveedor')
                        % PO_STATES.get(po.state, po.state)
                    ) if po_warn else '',
                    'apply':               not is_anchor,
                })
                seq += 10

            # Hijos del nodo actual — usar cache precargado en lugar de search() individual
            children = child_cache.get(mo.id, self.env['mrp.production'])
            new_children_to_enqueue = []
            for child in children:
                if child.id not in visited_mo_ids:
                    queue.append((child, level + 1, mo.name, mo_delta))
                    new_children_to_enqueue.append(child)

            # Marcar hijos nuevos como pendientes de preload para el siguiente nivel
            # Si sus IDs no están aún en child_cache, necesitan precargarse
            new_child_ids_not_cached = [
                c.id for c in new_children_to_enqueue
                if c.id not in child_cache
            ]
            if new_child_ids_not_cached:
                # Preload batch para los hijos recién encolados (nivel N+1)
                child_cache.update(self._preload_child_mos_batch(
                    new_child_ids_not_cached, visited_mo_ids
                ))
                po_cache.update(self._preload_pos_batch(new_children_to_enqueue))

        if truncated_mo_ids:
            _logger.warning(
                'mrp.reschedule.plan %s: MAX_DEPTH=%s alcanzado. IDs truncados: %s',
                self.id, MAX_DEPTH, truncated_mo_ids,
            )

        if lines_vals:
            self.env['mrp.reschedule.plan.line'].create(lines_vals)
        if wc_lines_data:
            for d in wc_lines_data:
                d['plan_id'] = self.id
            self.env['mrp.reschedule.plan.wc.line'].create(wc_lines_data)
