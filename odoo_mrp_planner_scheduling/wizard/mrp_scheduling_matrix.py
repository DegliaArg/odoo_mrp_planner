"""
Módulo: mrp_scheduling_matrix.py

Métodos de backend para el tablero de programación de producción.

Fuente de datos: mrp.production (todas las OFs, no solo las generadas por
solicitudes de programación).

Organización: filas = CT × Turno, columnas = períodos (día / semana / mes).
Los turnos provienen de mrp.planner.shift, configurados en mrp.reschedule.config.
"""
from datetime import datetime, timedelta, date as date_cls

import pytz

from odoo import models, api

# ── Helpers de períodos ───────────────────────────────────────────────────────

_MONTH_ABBR = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
_DAY_ABBR   = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']


def _all_period_keys(date_from_str, date_to_str, granularity):
    """Genera todas las claves de período entre date_from y date_to (inclusive)."""
    dt_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
    dt_to   = datetime.strptime(date_to_str,   '%Y-%m-%d').date()
    keys = []
    if granularity == 'day':
        d = dt_from
        while d <= dt_to:
            keys.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)
    elif granularity == 'month':
        y, m = dt_from.year, dt_from.month
        while date_cls(y, m, 1) <= dt_to:
            keys.append(f'{y}-{m:02d}')
            m += 1
            if m > 12:
                m, y = 1, y + 1
    else:   # week
        d = dt_from - timedelta(days=dt_from.weekday())
        while d <= dt_to:
            iso = d.isocalendar()
            keys.append(f'{iso[0]}-W{iso[1]:02d}')
            d += timedelta(weeks=1)
    return keys


def _period_label(key, granularity):
    """Retorna un dict de display para una clave de período."""
    if granularity == 'day':
        d = datetime.strptime(key, '%Y-%m-%d').date()
        return {
            'label':   f'{_DAY_ABBR[d.weekday()]} {d.day:02d}/{d.month:02d}',
            'sublabel': str(d.year),
        }
    if granularity == 'month':
        y, m = int(key[:4]), int(key[5:])
        return {'label': _MONTH_ABBR[m - 1], 'sublabel': str(y)}
    # week
    yr, wk = int(key[:4]), int(key[6:])
    monday = datetime.fromisocalendar(yr, wk, 1).date()
    sunday = datetime.fromisocalendar(yr, wk, 7).date()
    return {
        'label':     f'S{wk:02d}',
        'sublabel':  str(yr),
        'date_from': monday.strftime('%d/%m/%Y'),
        'date_to':   sunday.strftime('%d/%m/%Y'),
    }


def _period_key_for_dt(dt_local, granularity):
    """Devuelve la clave de período para un datetime local."""
    d = dt_local.date()
    if granularity == 'day':
        return d.strftime('%Y-%m-%d')
    if granularity == 'month':
        return f'{d.year}-{d.month:02d}'
    iso = d.isocalendar()
    return f'{iso[0]}-W{iso[1]:02d}'


def _shift_label(s):
    """Etiqueta compacta del turno: nombre + rango horario."""
    hf = int(s.hour_from)
    ht = int(s.hour_to)
    return f'{s.name} ({hf:02d}–{ht:02d})'


# ── Extensión de mrp.production ───────────────────────────────────────────────

class MrpProductionBoard(models.Model):
    _inherit = 'mrp.production'

    # ── Filtros ───────────────────────────────────────────────────────────────

    @api.model
    def get_scheduling_board_filters(self):
        """Devuelve sectores (tags de CT) y turnos disponibles."""
        tags = self.env['mrp.workcenter.tag'].search([], order='name')
        cfg  = self.env['mrp.reschedule.config'].get_config()
        default_tag_id = (
            cfg.default_scheduling_tag_id.id
            if cfg and cfg.default_scheduling_tag_id else None
        )
        shifts = []
        if cfg and getattr(cfg, 'enable_shifts', False):
            shifts = [
                {
                    'id':        s.id,
                    'name':      s.name,
                    'hour_from': s.hour_from,
                    'hour_to':   s.hour_to,
                    'label':     _shift_label(s),
                }
                for s in cfg.shift_ids.sorted('hour_from')
            ]
        return {
            'tags':                      [{'id': t.id, 'name': t.name} for t in tags],
            'default_scheduling_tag_id': default_tag_id,
            'shifts':                    shifts,
        }

    @api.model
    def get_scheduling_board_wcs_for_tags(self, tag_ids):
        """CTs activos que tienen al menos uno de los tags dados."""
        if not tag_ids:
            return []
        wcs = self.env['mrp.workcenter'].search(
            [('tag_ids', 'in', tag_ids), ('active', '=', True)],
            order='name',
        )
        return [{'id': w.id, 'name': w.name} for w in wcs]

    # ── Datos del tablero ─────────────────────────────────────────────────────

    @api.model
    def get_scheduling_board(self, tag_ids=None, date_from=None, date_to=None,
                              granularity='day'):
        """
        Construye el tablero de programación.

        Filas  = CT × Turno (o solo CT si no hay turnos configurados).
        Columnas = TODOS los períodos del rango (días / semanas / meses),
                   independientemente de si tienen OFs.

        Parámetros:
        - tag_ids:     list[int] | None  — filtrar CTs por sector.
        - date_from:   str 'YYYY-MM-DD' — inicio del rango (inclusive).
        - date_to:     str 'YYYY-MM-DD' — fin del rango (inclusive).
        - granularity: 'day' | 'week' | 'month'.

        :returns: dict con period_keys, period_labels, wc_shift_rows, total_mos.
        """
        _empty = lambda reason: {
            'period_keys': [], 'period_labels': {}, 'wc_shift_rows': [],
            'total_mos': 0, 'empty_reason': reason,
        }

        if not date_from or not date_to:
            return _empty('no_dates')

        # Todos los períodos del rango — siempre se muestran aunque estén vacíos
        period_keys   = _all_period_keys(date_from, date_to, granularity)
        period_labels = {k: _period_label(k, granularity) for k in period_keys}

        # Turnos de config
        cfg    = self.env['mrp.reschedule.config'].get_config()
        shifts = []
        if cfg and getattr(cfg, 'enable_shifts', False):
            shifts = list(cfg.shift_ids.sorted('hour_from'))

        # CTs válidos según tags
        if tag_ids:
            tagged_wcs   = self.env['mrp.workcenter'].search(
                [('tag_ids', 'in', tag_ids), ('active', '=', True)]
            )
            valid_wc_ids = set(tagged_wcs.ids)
        else:
            valid_wc_ids = None   # None = todos

        # Dominio de OFs
        dt_from = datetime.strptime(date_from, '%Y-%m-%d')
        dt_to   = datetime.strptime(date_to,   '%Y-%m-%d') + timedelta(days=1)
        domain = [
            ('state', 'in', ('confirmed', 'progress', 'to_close')),
            ('date_start', '!=', False),
            ('date_start', '>=', dt_from),
            ('date_start', '<',  dt_to),
        ]
        mos = self.env['mrp.production'].search(domain, order='date_start, id')

        # Prefetch para evitar N+1
        mos.mapped('product_id.uom_id')
        mos.mapped('product_id.product_tmpl_id.x_centros_compatibles.workcenter_id')
        mos.mapped('workorder_ids.workcenter_id')

        tz = pytz.timezone(self.env.user.tz or 'UTC')

        def _mo_wc(mo):
            """Workcenter de la OF: primero WO, luego config de producto."""
            for wo in mo.workorder_ids.sorted('sequence'):
                wc = wo.workcenter_id
                if wc and wc.active:
                    if valid_wc_ids is None or wc.id in valid_wc_ids:
                        return wc
            centros = mo.product_id.product_tmpl_id.x_centros_compatibles.filtered(
                'active'
            ).sorted(lambda c: (not c.is_preferred, c.sequence))
            for centro in centros:
                wc = centro.workcenter_id
                if wc and wc.active:
                    if valid_wc_ids is None or wc.id in valid_wc_ids:
                        return wc
            return None

        def _mo_shift(dt_local):
            """Turno al que pertenece una OF según su hora local de inicio."""
            if not shifts:
                return None
            h = dt_local.hour + dt_local.minute / 60.0
            for s in shifts:
                hf, ht = s.hour_from, s.hour_to
                if hf > ht:   # turno nocturno
                    if h >= hf or h < ht:
                        return s
                else:
                    if hf <= h < ht:
                        return s
            return None

        # Agrupar chips por (wc_id, shift_id_or_None, period_key)
        wc_records   = {}   # wc_id → workcenter
        cells_matrix = {}   # (wc_id, shift_id|None) → {period_key: [chips]}

        total_mos = 0
        for mo in mos:
            wc = _mo_wc(mo)
            if wc is None:
                continue

            wc_records[wc.id] = wc
            dt_local  = pytz.utc.localize(mo.date_start).astimezone(tz)
            shift     = _mo_shift(dt_local)
            shift_id  = shift.id if shift else None
            pair      = (wc.id, shift_id)
            pk        = _period_key_for_dt(dt_local, granularity)

            if pair not in cells_matrix:
                cells_matrix[pair] = {}
            if pk not in cells_matrix[pair]:
                cells_matrix[pair][pk] = []

            uom = mo.product_uom_id.name if mo.product_uom_id else ''
            date_finish_str = ''
            if mo.state == 'done' and mo.date_finished:
                try:
                    date_finish_str = (
                        pytz.utc.localize(mo.date_finished)
                        .astimezone(tz)
                        .strftime('%d/%m %H:%M')
                    )
                except Exception:
                    pass

            # Duración: suma de work orders (minutos → horas), o 0
            total_minutes = sum(
                wo.duration_expected or 0 for wo in mo.workorder_ids
            )
            duration_hours = round(total_minutes / 60.0, 2) if total_minutes else 0.0

            cells_matrix[pair][pk].append({
                'mo_id':          mo.id,
                'mo_name':        mo.name,
                'product_name':   mo.product_id.display_name if mo.product_id else '',
                'qty':            mo.product_qty,
                'uom':            uom,
                'duration_hours': duration_hours,
                'date_start':     dt_local.strftime('%d/%m %H:%M'),
                'date_finish':    date_finish_str,
                'state':          mo.state,
            })
            total_mos += 1

        # Construir wc_shift_rows en orden: CT (nombre) → turno (hour_from)
        wcs_sorted = sorted(wc_records.values(), key=lambda w: w.name)

        wc_shift_rows = []
        for wc in wcs_sorted:
            tag_names = [t.name for t in wc.tag_ids]

            if shifts:
                rows_for_wc = []
                for idx, s in enumerate(shifts):
                    pair  = (wc.id, s.id)
                    raw   = cells_matrix.get(pair, {})
                    cells = {pk: raw.get(pk, []) for pk in period_keys}
                    rows_for_wc.append({
                        'row_id':         f'{wc.id}_{s.id}',
                        'wc_id':          wc.id,
                        'wc_name':        wc.name,
                        'tag_names':      tag_names,
                        'shift_id':       s.id,
                        'shift_name':     s.name,
                        'shift_label':    _shift_label(s),
                        'is_first_shift': idx == 0,
                        'shift_count':    len(shifts),
                        'cells':          cells,
                    })
                wc_shift_rows.extend(rows_for_wc)
            else:
                pair  = (wc.id, None)
                raw   = cells_matrix.get(pair, {})
                cells = {pk: raw.get(pk, []) for pk in period_keys}
                wc_shift_rows.append({
                    'row_id':         str(wc.id),
                    'wc_id':          wc.id,
                    'wc_name':        wc.name,
                    'tag_names':      tag_names,
                    'shift_id':       None,
                    'shift_name':     '',
                    'shift_label':    '',
                    'is_first_shift': True,
                    'shift_count':    1,
                    'cells':          cells,
                })

        return {
            'period_keys':   period_keys,
            'period_labels': period_labels,
            'wc_shift_rows': wc_shift_rows,
            'total_mos':     total_mos,
            'has_shifts':    bool(shifts),
        }

    @api.model
    def get_mo_components(self, mo_id):
        """Devuelve los componentes (movimientos de materia prima) de la OF."""
        mo = self.env['mrp.production'].browse(mo_id)
        if not mo.exists():
            return []
        result = []
        for move in mo.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            uom = move.product_uom.name if move.product_uom else ''
            result.append({
                'product_name': move.product_id.display_name if move.product_id else '',
                'qty':          move.product_uom_qty,
                'uom':          uom,
            })
        return result
