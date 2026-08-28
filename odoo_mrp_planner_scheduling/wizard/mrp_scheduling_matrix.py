"""
Módulo: mrp_scheduling_matrix.py
Modelo: mrp.production.request (extensión)

Métodos de backend para el widget de tablero de programación por semanas y CTs.
Devuelven la estructura de datos que consume el componente OWL SchedulingMatrixWidget.

Responsabilidades:
- get_scheduling_matrix: construye la matriz semanas × CTs con las líneas planificadas.
- get_scheduling_matrix_filters: devuelve sectores y solicitudes disponibles para filtros.
- get_scheduling_wcs_for_tags: CTs que pertenecen a uno o más sectores (tags).
- action_resequence_lines: actualiza la secuencia de varias líneas de una vez.
- action_reassign_wc: reasigna una línea a otro centro de trabajo.
"""
from datetime import datetime, timedelta

from odoo import models, api


class MrpProductionRequestMatrix(models.Model):
    _inherit = 'mrp.production.request'

    # ── Filtros ───────────────────────────────────────────────────────────────

    @api.model
    def get_scheduling_matrix_filters(self):
        """Devuelve sectores (tags de CT), solicitudes recientes y el tag predeterminado.

        :returns: dict con 'tags', 'requests' y 'default_scheduling_tag_id'.
        """
        tags = self.env['mrp.workcenter.tag'].search([], order='name')
        requests = self.env['mrp.production.request'].search(
            [('state', 'in', ('calculated', 'confirmed'))],
            order='id desc', limit=60,
        )
        cfg = self.env['mrp.reschedule.config'].get_config()
        default_tag_id = (
            cfg.default_scheduling_tag_id.id
            if cfg and cfg.default_scheduling_tag_id
            else None
        )
        return {
            'tags': [{'id': t.id, 'name': t.name} for t in tags],
            'requests': [
                {'id': r.id, 'name': r.name, 'state': r.state}
                for r in requests
            ],
            'default_scheduling_tag_id': default_tag_id,
        }

    @api.model
    def get_scheduling_wcs_for_tags(self, tag_ids):
        """Devuelve los centros de trabajo que tienen al menos uno de los tags dados.

        :param tag_ids: list[int] — IDs de mrp.workcenter.tag.
        :returns: list[dict] con 'id' y 'name' de cada CT.
        """
        if not tag_ids:
            return []
        wcs = self.env['mrp.workcenter'].search(
            [('tag_ids', 'in', tag_ids), ('active', '=', True)],
            order='name',
        )
        return [{'id': w.id, 'name': w.name} for w in wcs]

    # ── Datos de la matriz ────────────────────────────────────────────────────

    @api.model
    def get_scheduling_matrix(self, request_ids=None, tag_ids=None, date_from=None, date_to=None):
        """Construye la matriz de programación: filas=CTs, columnas=semanas ISO, celdas=MOs.

        Parámetros:
        - request_ids: list[int] | None — filtrar por solicitudes específicas (None = todas).
        - tag_ids:     list[int] | None — filtrar CTs por sector (tag). None = sin filtro.
        - date_from:   str 'YYYY-MM-DD' — inicio del rango (inclusive).
        - date_to:     str 'YYYY-MM-DD' — fin del rango (inclusive).

        :returns: dict con week_keys, week_labels, wc_rows y total_lines.
        """
        _empty = lambda reason: {
            'week_keys': [], 'week_labels': {}, 'wc_rows': [], 'total_lines': 0,
            'empty_reason': reason,
        }

        domain = [('record_type', '=', 'mrp'), ('new_date_start', '!=', False)]
        if request_ids:
            domain.append(('request_id', 'in', request_ids))

        lines = self.env['mrp.production.request.line'].search(domain)

        if not lines:
            return _empty('no_lines')

        # Filtrar por rango de fechas
        if date_from:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            lines = lines.filtered(lambda l: l.new_date_start >= dt_from)
        if date_to:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            lines = lines.filtered(lambda l: l.new_date_start < dt_to)

        if not lines:
            return _empty('no_date_match')

        # CTs con líneas asignadas
        wc_ids_in_lines = {l.workcenter_id.id for l in lines if l.workcenter_id}
        if not wc_ids_in_lines:
            return _empty('no_workcenter')

        # Filtrar CTs por tags de sector si se especificaron
        wcs = self.env['mrp.workcenter'].browse(list(wc_ids_in_lines))
        if tag_ids:
            tag_id_set = set(tag_ids)
            wcs = wcs.filtered(lambda w: tag_id_set & set(w.tag_ids.ids))

        if not wcs:
            return _empty('no_tag_match')

        valid_wc_ids = set(wcs.ids)
        lines = lines.filtered(lambda l: l.workcenter_id.id in valid_wc_ids)

        # ── Calcular semanas ISO presentes ────────────────────────────────────
        week_keys_set = set()
        week_labels = {}
        for line in lines:
            dt = line.new_date_start
            iso = dt.isocalendar()
            year, week = iso[0], iso[1]
            wk = f'{year}-W{week:02d}'
            week_keys_set.add(wk)
            if wk not in week_labels:
                monday = datetime.fromisocalendar(year, week, 1)
                sunday = datetime.fromisocalendar(year, week, 7)
                week_labels[wk] = {
                    'label': f'S{week:02d}',
                    'year': year,
                    'date_from': monday.strftime('%d/%m/%Y'),
                    'date_to': sunday.strftime('%d/%m/%Y'),
                }

        week_keys = sorted(week_keys_set)

        # ── Prefetch de datos relacionados (evita N+1) ────────────────────────
        lines.mapped('product_id.uom_id')
        lines.mapped('item_id.date_deadline')
        lines.mapped('request_id.name')

        # ── Agrupar líneas por (wc_id, semana) ───────────────────────────────
        cells_by_wc_week = {}
        for line in lines:
            if not line.workcenter_id:
                continue
            dt = line.new_date_start
            iso = dt.isocalendar()
            wk = f'{iso[0]}-W{iso[1]:02d}'
            wc_id = line.workcenter_id.id
            key = (wc_id, wk)
            if key not in cells_by_wc_week:
                cells_by_wc_week[key] = []

            req = line.request_id
            item = line.item_id
            uom = ''
            if line.product_id and line.product_id.uom_id:
                uom = line.product_id.uom_id.name

            cells_by_wc_week[key].append({
                'line_id':        line.id,
                'request_id':     req.id,
                'request_name':   req.name,
                'request_state':  req.state,
                'product_name':   line.product_id.display_name if line.product_id else '',
                'qty':            line.product_qty,
                'uom':            uom,
                'date_start':     line.new_date_start.strftime('%d/%m/%Y %H:%M')
                                  if line.new_date_start else '',
                'date_finish':    line.new_date_finish.strftime('%d/%m/%Y %H:%M')
                                  if line.new_date_finish else '',
                'duration_hours': line.duration_hours,
                'level':          line.level,
                'sequence':       line.sequence,
                'type_label':     line.type_label or '',
                'workcenter_id':  line.workcenter_id.id,
                'workcenter_name': line.workcenter_id.name,
                'item_deadline':  item.date_deadline.strftime('%d/%m/%Y')
                                  if item and item.date_deadline else '',
            })

        # ── Calcular capacidad semanal por CT ─────────────────────────────────
        company_calendar = self.env.company.resource_calendar_id

        def _week_capacity_hours(wc, year, week):
            cal = wc.resource_calendar_id or company_calendar
            if not cal:
                return 40.0
            monday = datetime.fromisocalendar(year, week, 1).date()
            total = 0.0
            for att in cal.attendance_ids:
                dow = int(att.dayofweek)  # '0'=Lunes … '6'=Domingo
                day = monday + timedelta(days=dow)
                if att.date_from and att.date_from > day:
                    continue
                if att.date_to and att.date_to < day:
                    continue
                total += att.hour_to - att.hour_from
            return round(total, 2) if total > 0 else 40.0

        # ── Construir wc_rows ─────────────────────────────────────────────────
        wc_rows = []
        for wc in wcs.sorted(lambda w: w.name):
            cells = {}
            planned_hours_per_week = {}
            capacity_hours_per_week = {}

            for wk in week_keys:
                parts = wk.split('-W')
                year_w, week_w = int(parts[0]), int(parts[1])
                cell_lines = list(cells_by_wc_week.get((wc.id, wk), []))
                cell_lines.sort(key=lambda l: (l['sequence'], l['line_id']))
                cells[wk] = cell_lines

                planned = sum(l['duration_hours'] for l in cell_lines)
                capacity = _week_capacity_hours(wc, year_w, week_w)
                planned_hours_per_week[wk] = round(planned, 2)
                capacity_hours_per_week[wk] = capacity

            tag_names = [t.name for t in wc.tag_ids]

            wc_rows.append({
                'wc_id':                   wc.id,
                'wc_name':                 wc.name,
                'tag_names':               tag_names,
                'cells':                   cells,
                'planned_hours_per_week':  planned_hours_per_week,
                'capacity_hours_per_week': capacity_hours_per_week,
            })

        return {
            'week_keys':   week_keys,
            'week_labels': week_labels,
            'wc_rows':     wc_rows,
            'total_lines': len(lines),
        }

    # ── Acciones de interacción ───────────────────────────────────────────────

    @api.model
    def action_resequence_lines(self, sequence_map):
        """Actualiza la secuencia de varias líneas a la vez.

        Llamado después de un drag-and-drop de reordenamiento dentro de un CT.

        :param sequence_map: list[dict] con {line_id, new_sequence}.
        :returns: True.
        """
        for item in sequence_map:
            line = self.env['mrp.production.request.line'].browse(item['line_id'])
            if line.exists():
                line.write({'sequence': item['new_sequence']})
        return True

    @api.model
    def action_reassign_wc(self, line_id, new_wc_id):
        """Reasigna una línea de plan a un centro de trabajo diferente.

        Actualiza el workcenter_id de la línea y recalcula el resumen de carga
        (mrp.production.request.wc) para los CTs afectados (origen y destino).

        :param line_id:   int — ID de mrp.production.request.line.
        :param new_wc_id: int — ID de mrp.workcenter destino.
        :returns: True si se aplicó, False si la línea no existe.
        """
        line = self.env['mrp.production.request.line'].browse(line_id)
        if not line.exists():
            return False

        old_wc_id = line.workcenter_id.id
        line.write({'workcenter_id': new_wc_id})

        # Recalcular resumen de carga para los CTs afectados
        request = line.request_id
        for wc_id in filter(None, {old_wc_id, new_wc_id}):
            existing = request.wc_load_ids.filtered(lambda w: w.workcenter_id.id == wc_id)
            affected = request.line_ids.filtered(
                lambda l: l.workcenter_id.id == wc_id and l.record_type == 'mrp'
            )
            if affected:
                total_hours = sum(affected.mapped('duration_hours'))
                starts = [l.new_date_start for l in affected if l.new_date_start]
                ends   = [l.new_date_finish for l in affected if l.new_date_finish]
                vals = {
                    'total_hours': round(total_hours, 2),
                    'date_start':  min(starts) if starts else False,
                    'date_end':    max(ends)   if ends   else False,
                }
                if existing:
                    existing.write(vals)
                else:
                    self.env['mrp.production.request.wc'].create({
                        'request_id':    request.id,
                        'workcenter_id': wc_id,
                        **vals,
                    })
            elif existing:
                existing.unlink()

        return True
