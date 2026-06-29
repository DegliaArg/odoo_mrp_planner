import logging
import pytz
from datetime import datetime, time, timedelta

from odoo import models

_logger = logging.getLogger(__name__)

_N = ' '  # non-breaking space — los espacios normales colapsan en HTML


def no_subcontract_domain(env):
    """Excluye OFs de subcontratación filtrando por ubicación de origen.
    Pre-carga los IDs de ubicaciones de subcontratación y usa 'not in' directo
    para evitar problemas de travesía relacional en search/search_count."""
    sc_loc_ids = env['stock.location'].search(
        [('is_subcontracting_location', '=', True)]
    ).ids
    if not sc_loc_ids:
        return []
    return [('location_src_id', 'not in', sc_loc_ids)]
INDENT_MAP = {
    0: '',
    1: '└─ ',
    2: f'{_N*3}└─ ',
    3: f'{_N*6}└─ ',
    4: f'{_N*9}└─ ',
    5: f'{_N*12}└─ ',
}


class MrpScheduleMixin(models.AbstractModel):
    _name = 'mrp.schedule.mixin'
    _description = 'Utilidades de programación de calendarios'

    def _schedule_duration(self, calendar, after_dt, duration_hours):
        """Programa duration_hours horas hábiles a partir de after_dt según el calendario.
        Retorna (start, end) como datetimes UTC naive."""
        if hasattr(after_dt, 'tzinfo') and after_dt.tzinfo:
            after_dt = after_dt.astimezone(pytz.utc).replace(tzinfo=None)
        if not calendar:
            # Sin calendario definido: fallback lineal (8h si no hay duración)
            return (after_dt, after_dt + timedelta(hours=duration_hours or 8.0))
        if not duration_hours:
            # FIX [FASE-3]: duración 0 devolvía 8h incorrectamente
            return (after_dt, after_dt)

        tz = pytz.timezone(calendar.tz or 'UTC')
        remaining = float(duration_hours)
        start_result = None
        current = pytz.utc.localize(after_dt).astimezone(tz)

        for _ in range(365):
            day_date = current.date()
            weekday = str(day_date.weekday())
            day_atts = calendar.attendance_ids.filtered(
                lambda a: a.dayofweek == weekday
                and (not a.date_from or a.date_from <= day_date)
                and (not a.date_to   or a.date_to   >= day_date)
            ).sorted('hour_from')

            for att in day_atts:
                def _hm(hf):
                    h = int(hf)
                    return h, min(int(round((hf - h) * 60)), 59)
                h_from, m_from = _hm(att.hour_from)
                h_to,   m_to   = _hm(att.hour_to)
                iv_start = tz.localize(
                    datetime.combine(day_date, time(h_from, m_from)), is_dst=False
                )
                if h_to >= 24:
                    iv_end = tz.localize(
                        datetime.combine(day_date + timedelta(days=1), time(0, 0)),
                        is_dst=False,
                    )
                else:
                    iv_end = tz.localize(
                        datetime.combine(day_date, time(h_to, m_to)), is_dst=False
                    )
                if current >= iv_end:
                    continue
                seg_start = max(current, iv_start)
                seg_hours = (iv_end - seg_start).total_seconds() / 3600.0
                if seg_hours <= 1e-9:
                    continue
                if start_result is None:
                    start_result = seg_start
                if remaining <= seg_hours + 1e-9:
                    end_result = seg_start + timedelta(hours=remaining)
                    return (
                        start_result.astimezone(pytz.utc).replace(tzinfo=None),
                        end_result.astimezone(pytz.utc).replace(tzinfo=None),
                    )
                remaining -= seg_hours
                current = iv_end

            current = tz.localize(
                datetime.combine(day_date + timedelta(days=1), time(0, 0)), is_dst=False
            )

        _logger.warning('MRP Reschedule: sin slot en 365 días (%s)', calendar.name)
        return (after_dt, after_dt + timedelta(hours=duration_hours))
