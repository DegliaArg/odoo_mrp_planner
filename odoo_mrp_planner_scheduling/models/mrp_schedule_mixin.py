"""
Módulo: mrp_schedule_mixin.py
Modelo: mrp.schedule.mixin (AbstractModel — mixin reutilizable)

Provee utilidades de programación de calendarios laborales para órdenes
de fabricación (Manufacturing Orders), calculando ventanas de trabajo
reales a partir de los calendarios de turnos de Odoo.

Responsabilidades:
- Calcular el intervalo (start, end) en UTC para una duración en horas
  hábiles sobre un calendario de asistencia dado.

Relacionado con:
- resource.calendar: lee attendance_ids para determinar horarios hábiles.
- mrp.production: modelos concretos que heredan este mixin para reprogramar.
- odoo_mrp_planner.models.mrp_planner_helpers: no_subcontract_domain e
  INDENT_MAP viven en el módulo base; se re-exportan aquí por compatibilidad
  con los imports internos de este módulo.
"""
import logging
import pytz
from datetime import datetime, time, timedelta

from odoo import models

# Re-export: los modelos de este módulo importan estos helpers desde el mixin.
from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import (  # noqa: F401
    INDENT_MAP,
    no_subcontract_domain,
)

_logger = logging.getLogger(__name__)

class MrpScheduleMixin(models.AbstractModel):
    _name = 'mrp.schedule.mixin'
    _description = 'Utilidades de programación de calendarios'

    def _schedule_duration(self, calendar, after_dt, duration_hours):
        """
        Programa duration_hours horas hábiles a partir de after_dt en el calendario dado.

        Recorre los turnos de asistencia del calendario (attendance_ids) día a día,
        acumulando segmentos de tiempo hábil hasta completar la duración solicitada.
        Maneja correctamente zonas horarias: trabaja en la TZ del calendario y convierte
        los resultados a UTC naive para compatibilidad con campos Datetime de Odoo.

        :param calendar: resource.calendar — calendario de turnos a usar.
                         Si es falsy se aplica fallback lineal de 8 h.
        :param after_dt: datetime — momento de inicio (UTC naive o aware).
        :param duration_hours: float — horas hábiles a programar.
        :returns: tuple(datetime, datetime) — (start, end) en UTC naive.
        """
        if hasattr(after_dt, 'tzinfo') and after_dt.tzinfo:
            after_dt = after_dt.astimezone(pytz.utc).replace(tzinfo=None)
        if not calendar:
            # Sin calendario definido: fallback lineal (8h si no hay duración)
            return (after_dt, after_dt + timedelta(hours=duration_hours or 8.0))
        if not duration_hours:
            # duración 0 devolvía 8h incorrectamente
            return (after_dt, after_dt)

        tz = pytz.timezone(calendar.tz or 'UTC')
        remaining = float(duration_hours)
        start_result = None
        current = pytz.utc.localize(after_dt).astimezone(tz)

        # 365 días: límite de seguridad para calendarios con muchos días festivos
        # o configuraciones incompletas; evita bucles infinitos en producción.
        for _ in range(365):
            day_date = current.date()
            weekday = str(day_date.weekday())  # dayofweek en attendance_ids es string ('0'..'6')
            day_atts = calendar.attendance_ids.filtered(
                lambda a: a.dayofweek == weekday
                and (not a.date_from or a.date_from <= day_date)
                and (not a.date_to   or a.date_to   >= day_date)
            ).sorted('hour_from')

            for att in day_atts:
                def _hm(hf):
                    """Convierte hora decimal (ej. 8.5) a (hora, minuto) enteros."""
                    h = int(hf)
                    # min(..., 59): evita time(h, 60) cuando la fracción es exactamente 1.0
                    return h, min(int(round((hf - h) * 60)), 59)
                h_from, m_from = _hm(att.hour_from)
                h_to,   m_to   = _hm(att.hour_to)
                iv_start = tz.localize(
                    datetime.combine(day_date, time(h_from, m_from)), is_dst=False
                )
                if h_to >= 24:
                    # hour_to == 24 indica "fin de día"; time() no acepta hora 24
                    # por eso se construye como medianoche del día siguiente.
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
                if seg_hours <= 1e-9:  # tolerancia de punto flotante; descarta segmentos ~0 s
                    continue
                if start_result is None:
                    start_result = seg_start
                if remaining <= seg_hours + 1e-9:  # +1e-9: absorbe error de punto flotante acumulado
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
