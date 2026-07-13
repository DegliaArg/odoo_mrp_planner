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
import pytz
from datetime import datetime, timedelta

from odoo import models

from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import INDENT_MAP

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

    # ── Anclas de WC ─────────────────────────────────────────────────────────

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

    # ── Programación del árbol ────────────────────────────────────────────────

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

    # ── Colección de líneas ───────────────────────────────────────────────────

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
