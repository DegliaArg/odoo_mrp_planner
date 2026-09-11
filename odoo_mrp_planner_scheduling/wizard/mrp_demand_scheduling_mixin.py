"""
Mixin: MrpDemandSchedulingMixin — scheduling de fechas contra calendario laboral.

Responsabilidades:
- Obtener el calendario del proveedor para avanzar/retroceder días hábiles.
- Avanzar o retroceder N días hábiles respetando el calendario de trabajo.
- Construir las anclas de WC (carga existente en OFs confirmadas/en progreso).
- Programar el árbol de demanda bottom-up asignando fechas a cada nodo.
- Convertir el árbol programado en la lista de dicts para crear las líneas del plan.
"""
import logging
from datetime import datetime, timedelta

from odoo import models

from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import INDENT_MAP

_logger = logging.getLogger(__name__)


class MrpDemandSchedulingMixin(models.AbstractModel):
    _name = 'mrp.demand.scheduling.mixin'
    _description = 'Mixin de scheduling contra calendario laboral'

    # ── Calendario de proveedor ───────────────────────────────────────────────

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

    # ── Avance / retroceso de días hábiles ───────────────────────────────────

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

        # Precomputar asistencias agrupadas por día de la semana (string '0'..'6').
        # Permite lookup O(1) dentro del loop en lugar de iterar toda la lista cada día.
        atts_by_weekday = {}
        for att in calendar.attendance_ids:
            atts_by_weekday.setdefault(att.dayofweek, []).append(att)

        dt = from_dt
        days_counted = 0
        max_iter = lead_days * 7 + 30  # margen extra para calendarios con muchos días festivos

        for _ in range(max_iter):
            if days_counted >= lead_days:
                break
            dt += timedelta(days=1)
            dt_date = dt.date()
            weekday = str(dt.weekday())
            # O(1): si el weekday no tiene asistencias, es día no laboral directo
            if any(
                (not att.date_from or att.date_from <= dt_date)
                and (not att.date_to   or att.date_to   >= dt_date)
                for att in atts_by_weekday.get(weekday, ())
            ):
                days_counted += 1

        dt_date = dt.date()
        weekday = str(dt.weekday())
        day_atts = sorted(
            [
                a for a in atts_by_weekday.get(weekday, ())
                if (not a.date_from or a.date_from <= dt_date)
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

        # Precomputar asistencias agrupadas por día de la semana (string '0'..'6').
        # Permite lookup O(1) dentro del loop en lugar de iterar toda la lista cada día.
        atts_by_weekday = {}
        for att in calendar.attendance_ids:
            atts_by_weekday.setdefault(att.dayofweek, []).append(att)

        dt = before_dt
        days_counted = 0
        max_iter = lead_days * 7 + 30  # margen para calendarios con muchos días libres

        for _ in range(max_iter):
            if days_counted >= lead_days:
                break
            dt -= timedelta(days=1)
            dt_date = dt.date()
            weekday = str(dt.weekday())  # '0'=lunes, igual que att.dayofweek
            # O(1): si el weekday no tiene asistencias, es día no laboral directo
            if any(
                (not att.date_from or att.date_from <= dt_date)
                and (not att.date_to   or att.date_to   >= dt_date)
                for att in atts_by_weekday.get(weekday, ())
            ):
                days_counted += 1

        # Posicionar al inicio del primer turno del día resultante
        dt_date = dt.date()
        weekday = str(dt.weekday())
        day_atts = sorted(
            [
                a for a in atts_by_weekday.get(weekday, ())
                if (not a.date_from or a.date_from <= dt_date)
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

    # ── Anclas de WC ─────────────────────────────────────────────────────────

    def _get_wc_busy_multi(self, start, roots):
        """Construye la AGENDA de cada CT: la lista de intervalos (inicio, fin)
        ocupados por la carga REALMENTE planificada en Odoo, ordenados y fusionados.

        Reemplaza al modelo de "un solo ancla por CT" (el fin de lo último). Con la
        agenda completa el motor ve los HUECOS entre trabajos y puede calzar una OT
        nueva en un hueco temprano en vez de apilarla siempre al final (capacidad
        finita = 1 máquina por CT).

        IMPORTANTE (fix backlog): las OTs sin planificar (date_start/date_finished
        en NULL) NO ocupan agenda. Un backlog no planificado no toma una franja
        concreta del CT, así que no genera intervalo (si contara, empujaría todo a
        "atraso").

        :param start: datetime — piso temporal (UTC naive). Solo se consideran OTs
                      que terminan en/después de esta fecha.
        :param roots: list[dict] — lista de nodos raíz de los árboles de demanda.
        :returns: dict — {workcenter_id: [(start, end), ...]} ordenado y sin solapes.
        """
        wc_ids = set()

        def _collect(node):
            # Todos los candidatos (primario + alternativos): sin su agenda real, un
            # alternativo sin carga parecería siempre libre y ganaría mal el reparto.
            for _primary, candidates, _dur in node['operations']:
                for wc in candidates:
                    wc_ids.add(wc.id)
            for child in node['children']:
                _collect(child)

        for root in roots:
            _collect(root)
        if not wc_ids:
            return {}

        # Un único search_read de los intervalos (no un max agregado): necesitamos
        # DÓNDE está cada trabajo, no solo el fin de la cola. Solo OTs planificadas
        # (fechas seteadas), vivas (no done/cancel) y que terminan >= start.
        wos = self.env['mrp.workorder'].search_read(
            [
                ('workcenter_id', 'in', list(wc_ids)),
                ('state', 'not in', ('done', 'cancel')),
                ('date_start', '!=', False),
                ('date_finished', '!=', False),
                ('date_finished', '>=', start),
            ],
            ['workcenter_id', 'date_start', 'date_finished'],
        )
        busy = {}
        for wo in wos:
            wc = wo['workcenter_id']
            wc_id = wc[0] if wc else None
            ds, df = wo['date_start'], wo['date_finished']
            if not wc_id or not ds or not df or df <= ds:
                continue
            busy.setdefault(wc_id, []).append((ds, df))

        # Ordenar por inicio y fusionar solapes. Con capacidad 1 no deberían
        # solaparse, pero se fusiona por robustez (datos históricos inconsistentes).
        for wc_id, ivs in busy.items():
            ivs.sort(key=lambda iv: iv[0])
            merged = []
            for s, e in ivs:
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))
            busy[wc_id] = merged
        return busy

    # ── Programación del árbol ────────────────────────────────────────────────

    def _schedule_tree(self, node, start, wc_busy, min_dt=None, target_end=None,
                       wc_collector=None, direction='alap'):
        """Programa los nodos OF del árbol en orden bottom-up (primero las hojas).

        Cada operación (OT) se calza en un HUECO real de la agenda de su centro
        (capacidad finita = 1), no apilada detrás de lo último. La OF hereda sus
        fechas de las OTs: scheduled_start = inicio de la 1ª OT, scheduled_end =
        fin de la última.

        Los nodos OC/Subcont./compra se resuelven en un post-paso: su fecha de
        inicio se calcula retrocediendo lead_days desde el inicio de la OF padre.
        Los nodos stock son hojas sin fechas propias.

        La fecha de inicio de cada nodo OF respeta como PISO DURO (after_dt):
        - El fin del último hijo OF ya programado (dependencia de materiales).
        - min_dt: piso global (no se puede programar antes de hoy).
        - Para hijos OC/Subcont.: min_dt + lead_days (no se puede pedir en el pasado).

        La DIRECCIÓN define cómo se calza dentro de la agenda del CT:
        - 'alap': cada OT en el hueco más tardío que cumpla target_end (no adelanta
          producción). Si el deadline no es alcanzable, cae a 'asap' desde el piso.
        - 'asap': cada OT en el primer hueco disponible (empaqueta temprano).

        :param node: dict — nodo del árbol de demanda (se modifica en-place).
        :param start: datetime — fecha mínima de inicio para este nodo.
        :param wc_busy: dict — {wc_id: [(start, end), ...]} agenda compartida entre
                        artículos; cada OT calzada inserta su intervalo aquí.
        :param min_dt: datetime | None — piso temporal global (normalmente hoy UTC midnight).
        :param target_end: datetime | None — fecha objetivo de fin (deadline) del nodo.
        :param wc_collector: dict | None — acumulador de carga por CT para el resumen.
        :param direction: str — 'alap' | 'asap' (política de colocación).
        """
        leaf_types = ('purchase', 'subcontract', 'buy', 'stock')
        if node.get('type') in leaf_types:
            return  # Se resuelve desde el padre

        company_calendar = self.env.company.resource_calendar_id

        # Estimación del inicio de este nodo (retrocediendo su duración total desde
        # target_end): es la fecha objetivo de FIN de las hijas (back-chaining real,
        # la hija debe estar lista cuando la madre la consume). Se usa SOLO para
        # propagar a las hijas; la colocación ALAP real de este nodo la hace
        # _place_ops op por op. En 'asap' las hijas la ignoran y empaquetan temprano.
        jit_start = None
        if target_end:
            total_dur = sum(dur_h for _, _, dur_h in node['operations'])
            if total_dur > 0:
                first_wc = next((p for p, _, _ in node['operations'] if p), None)
                cal_bwd = (
                    first_wc.resource_calendar_id
                    if (first_wc and first_wc.resource_calendar_id)
                    else company_calendar
                )
                jit_start, _ = self._schedule_duration_backward(cal_bwd, target_end, total_dur)

        children_end = start
        for child in node['children']:
            if child.get('type') not in leaf_types:
                self._schedule_tree(child, start, wc_busy, min_dt=min_dt,
                                    target_end=jit_start, wc_collector=wc_collector,
                                    direction=direction)
                if child['scheduled_end']:
                    children_end = max(children_end, child['scheduled_end'])

        after_dt = max(start, children_end)
        if min_dt:
            after_dt = max(after_dt, min_dt)

        # Si algún hijo es compra/subcont., la OF no puede empezar antes de
        # min_dt + lead_days hábiles (no podemos pedir antes de hoy).
        if min_dt:
            for child in node['children']:
                if child.get('type') in ('purchase', 'subcontract', 'buy'):
                    lead = child.get('lead_days', 7)
                    cal  = child.get('supplier_calendar') or company_calendar
                    earliest_mo_start = self._forward_schedule_days(cal, min_dt, lead)
                    after_dt = max(after_dt, earliest_mo_start)

        # Piso duro de esta OF (fin de hijas, min_dt global y leads de proveedor).
        # NO incluye la carga de CT (que es blanda: la resuelven los huecos).
        node['min_start'] = after_dt

        # Colocación de las operaciones en la agenda de cada CT: elige centro
        # (primario o alternativo) buscando el mejor hueco, según la dirección.
        scheduled_ops, node_start, node_end = self._place_ops(
            node['operations'], after_dt, target_end, direction,
            wc_busy, wc_collector, company_calendar,
        )
        node['scheduled_ops']   = scheduled_ops
        node['scheduled_start'] = node_start
        node['scheduled_end']   = node_end

        # Backward schedule OC/Subcont./compra desde el inicio de la OF.
        for child in node['children']:
            if child.get('type') in ('purchase', 'subcontract', 'buy') and node_start:
                lead = child.get('lead_days', 7)
                cal  = child.get('supplier_calendar') or company_calendar
                child['scheduled_end']   = node_start
                raw_start = self._backward_schedule_days(cal, node_start, lead)
                child['scheduled_start'] = max(raw_start, min_dt) if min_dt else raw_start

    def _place_ops(self, operations, after_dt, target_end, direction,
                   wc_busy, wc_collector, company_calendar):
        """Coloca las operaciones (OTs) de una OF en la agenda de sus centros.

        Para cada operación elige el CT (primario o alternativo) que mejor calza
        según la dirección, buscando un HUECO real en su agenda (`wc_busy`), e
        inserta el intervalo elegido para que las OTs siguientes lo vean ocupado.

        - 'asap': pasada hacia adelante desde after_dt; por operación, el candidato
          que TERMINA más temprano (primario desempata).
        - 'alap': pasada hacia atrás desde target_end; por operación (en orden
          inverso), el candidato de INICIO más tardío (pega al deadline). Si el
          inicio de la 1ª operación cae antes de after_dt (deadline inalcanzable),
          se descarta y se cae a la pasada 'asap' desde after_dt. La inserción en la
          agenda se hace RECIÉN al confirmar la dirección, para que un intento ALAP
          fallido no ensucie `wc_busy` antes del fallback.

        :param operations: list[(primary_wc, [candidatos], dur_h)] — ops de la ruta.
        :param after_dt: datetime — piso duro de inicio.
        :param target_end: datetime | None — deadline objetivo (solo ALAP).
        :param direction: str — 'alap' | 'asap'.
        :param wc_busy: dict — {wc_id: [(start, end)]} agenda por CT (se muta).
        :param wc_collector: dict | None — acumulador de carga por CT (se muta).
        :param company_calendar: resource.calendar — fallback de calendario.
        :returns: tuple(list[dict], datetime | None, datetime) —
                  (scheduled_ops, node_start, node_end).
        """
        def _cal(wc):
            return (wc.resource_calendar_id or company_calendar) if wc else company_calendar

        def _forward():
            placed = []
            t = after_dt
            for primary, candidates, dur_h in operations:
                if not candidates:
                    cs, ce = self._schedule_in_gaps(
                        company_calendar, max(t, after_dt), dur_h, wc_busy.get(0, []))
                    chosen, is_primary = None, True
                else:
                    best = None
                    for cand in candidates:
                        cs, ce = self._schedule_in_gaps(
                            _cal(cand), max(t, after_dt), dur_h, wc_busy.get(cand.id, []))
                        if best is None or ce < best[1]:
                            best = (cs, ce, cand)
                    cs, ce, chosen = best
                    is_primary = bool(primary) and chosen.id == primary.id
                placed.append({'primary': primary, 'chosen': chosen,
                               'candidates': candidates, 'is_primary': is_primary,
                               'dur': dur_h, 'start': cs, 'end': ce})
                t = ce
            return placed

        def _backward():
            placed = []
            t = target_end
            for primary, candidates, dur_h in reversed(operations):
                if not candidates:
                    cs, ce = self._schedule_backward_in_gaps(
                        company_calendar, t, dur_h, wc_busy.get(0, []))
                    chosen, is_primary = None, True
                else:
                    best = None
                    for cand in candidates:
                        cs, ce = self._schedule_backward_in_gaps(
                            _cal(cand), t, dur_h, wc_busy.get(cand.id, []))
                        if best is None or cs > best[0]:   # inicio más tardío
                            best = (cs, ce, cand)
                    cs, ce, chosen = best
                    is_primary = bool(primary) and chosen.id == primary.id
                placed.append({'primary': primary, 'chosen': chosen,
                               'candidates': candidates, 'is_primary': is_primary,
                               'dur': dur_h, 'start': cs, 'end': ce})
                t = cs
            placed.reverse()   # volver al orden de la ruta
            return placed

        placed = None
        if direction == 'alap' and target_end and operations:
            cand = _backward()
            if cand and cand[0]['start'] >= after_dt:
                placed = cand   # deadline alcanzable respetando el piso
        if placed is None:
            placed = _forward()

        # Confirmar: insertar los intervalos en la agenda y acumular carga.
        scheduled = []
        node_start = None
        node_end = after_dt
        for o in placed:
            chosen = o['chosen']
            wc_id = chosen.id if chosen else 0
            lst = wc_busy.setdefault(wc_id, [])
            lst.append((o['start'], o['end']))
            lst.sort(key=lambda iv: iv[0])
            if wc_collector is not None and chosen:
                c = wc_collector.setdefault(chosen.id, {'hours': 0.0, 'start': None, 'end': None})
                c['hours'] += o['dur']
                c['start'] = min(c['start'], o['start']) if c['start'] else o['start']
                c['end']   = max(c['end'], o['end']) if c['end'] else o['end']
            scheduled.append({
                'wc': chosen, 'is_primary': o['is_primary'],
                'primary_wc': o['primary'], 'candidates': o.get('candidates') or [],
                'dur': o['dur'], 'start': o['start'], 'end': o['end'],
            })
            if node_start is None:
                node_start = o['start']
            node_end = max(node_end, o['end'])
        return scheduled, node_start, node_end

    # ── Colección de líneas ───────────────────────────────────────────────────

    def _collect_lines(self, node, lines_vals, seq, item_id=None, parent_key=None):
        """Convierte el árbol de demanda programado en una lista de dicts para crear líneas.

        Recorre el árbol en pre-orden (padre antes que hijos) y agrega un dict por
        nodo a lines_vals. Los nodos OC/stock son hojas (no tienen hijos que procesar).
        Los nodos OF continúan la recursión para agregar sus componentes.

        Cada dict lleva 'node_key' (identidad estable) y dos claves TRANSITORIAS
        con prefijo '_' que action_calculate post-procesa (y quita antes del create):
          - '_parent_key': node_key del padre, para setear parent_line_id.
          - '_ops': lista de operaciones (scheduled_ops) para crear las line.op.

        :param node: dict — nodo del árbol de demanda ya programado.
        :param lines_vals: list[dict] — lista acumuladora de valores para crear líneas.
        :param seq: list[int] — lista de un elemento usado como contador de secuencia
                    mutable (trick para pasar por referencia en recursión).
        :param item_id: int | None — ID del mrp.production.request.item al que pertenece.
        :param parent_key: str | None — node_key de la línea-OF padre (None en la raíz).
        """
        indent    = INDENT_MAP.get(node['level'], ' ' * 9 + '└─ ')
        product   = node['product']
        node_type = node.get('type', 'manufacture')
        node_key  = self._node_key(item_id, node) if item_id else ''

        if node_type in ('purchase', 'subcontract', 'buy'):
            lines_vals.append({
                'sequence':          seq[0],
                'level':             node['level'],
                'item_id':           item_id,
                'node_key':          node_key,
                '_parent_key':       parent_key,
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
                'node_key':          node_key,
                '_parent_key':       parent_key,
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

        # Nodo OF: usa los CTs ELEGIDOS al programar (scheduled_ops), no los de la
        # ruta — el motor puede haber mandado a un alternativo por carga. La cadena
        # marca cuáles fueron alternativos y used_alternative habilita el aviso.
        sops     = node.get('scheduled_ops') or []
        chosen   = [(o['wc'], o['is_primary']) for o in sops if o['wc']]
        dur_h    = sum(o['dur'] for o in sops)
        used_alt = any(not ip for _wc, ip in chosen)
        wc_label = ' › '.join(
            (wc.name if ip else f'{wc.name} (alt)') for wc, ip in chosen
        )

        # Operaciones para dibujar barras por-CT en el Gantt (una por operación con
        # CT elegido). Se omiten las sin CT: no tienen fila donde dibujarse.
        op_seq  = 0
        ops_data = []
        for o in sops:
            if not o.get('wc'):
                continue
            op_seq += 10
            primary_wc = o.get('primary_wc')
            cand_ids = [c.id for c in (o.get('candidates') or [])]
            ops_data.append({
                'sequence':              op_seq,
                'workcenter_id':         o['wc'].id,
                'primary_workcenter_id': primary_wc.id if primary_wc else False,
                'is_alternative':        not o['is_primary'],
                'duration_hours':        round(o['dur'], 2),
                'date_start':            o['start'],
                'date_finish':           o['end'],
                'candidate_workcenter_ids': [(6, 0, cand_ids)],
            })

        lines_vals.append({
            'sequence':          seq[0],
            'level':             node['level'],
            'item_id':           item_id,
            'node_key':          node_key,
            '_parent_key':       parent_key,
            '_ops':              ops_data,
            'min_start':         node.get('min_start'),
            'record_type':       'mrp',
            'product_id':        product.id,
            'bom_id':            node['bom'].id if node.get('bom') else False,
            'product_qty':       node['qty'],
            'duration_hours':    round(dur_h, 2),
            'new_date_start':    node['scheduled_start'],
            'new_date_finish':   node['scheduled_end'],
            'workcenter_id':     chosen[0][0].id if chosen else False,
            'workcenter_chain':  wc_label if (len(chosen) > 1 or used_alt) else '',
            'used_alternative':  used_alt,
            'suggestion_state':  'pending' if used_alt else 'none',
            'workcenter_label':  '',
            'description_label': f'{indent}{product.display_name}',
            'type_label':        'OF' if node['level'] == 0 else 'OF hija',
            'warning_type':      '',
            'warning_message':   '',
        })
        seq[0] += 10

        for child in node['children']:
            self._collect_lines(child, lines_vals, seq, item_id=item_id, parent_key=node_key)
