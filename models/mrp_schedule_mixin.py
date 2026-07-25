"""
Módulo: mrp_schedule_mixin.py
Modelo: mrp.schedule.mixin (AbstractModel — mixin reutilizable)

Provee utilidades de programación de calendarios laborales para órdenes
de fabricación (Manufacturing Orders), calculando ventanas de trabajo
reales a partir de los calendarios de turnos de Odoo.

Responsabilidades:
- Calcular el intervalo (start, end) en UTC para una duración en horas
  hábiles sobre un calendario de asistencia dado.
- Exponer un dominio de búsqueda que excluye órdenes de subcontratación.
- Definir el mapa de sangría visual para jerarquías de BoM en vistas HTML.

Relacionado con:
- resource.calendar: lee attendance_ids para determinar horarios hábiles.
- mrp.production: modelos concretos que heredan este mixin para reprogramar.
- stock.location: consulta ubicaciones de subcontratación al armar el dominio.
"""
import logging
import weakref
import pytz
from datetime import datetime, time, timedelta

from odoo import models

_logger = logging.getLogger(__name__)

_N = ' '  # non-breaking space — los espacios normales colapsan en HTML

# Cache de no_subcontract_domain por cursor (transacción).
# Las ubicaciones de subcontratación no cambian dentro de una misma transacción,
# por lo que es seguro reutilizar el resultado para evitar N queries en loops.
# Se indexa por id(env.cr) y se limpia automáticamente cuando el cursor es
# recolectado por el GC, previniendo memory leaks entre requests.
_no_subcontract_domain_cache: dict = {}


def _make_cache_cleanup(cr_id: int):
    """Retorna un callback de weakref que elimina la entrada del cache al liberar el cursor."""
    def _cleanup(_):
        _no_subcontract_domain_cache.pop(cr_id, None)
    return _cleanup


def no_subcontract_domain(env):
    """
    Construye un dominio que excluye órdenes de fabricación subcontratadas.

    Pre-carga los IDs de ubicaciones de subcontratación y usa 'not in' directo
    para evitar problemas de travesía relacional en search/search_count.
    Retorna una lista vacía cuando no existen ubicaciones de subcontratación
    para no penalizar el rendimiento de la consulta innecesariamente.

    El resultado se cachea por cursor de base de datos: dentro de la misma
    transacción se reutiliza sin ejecutar una nueva query SQL.

    :param env: entorno de Odoo (odoo.api.Environment).
    :returns: list — dominio de búsqueda compatible con ORM de Odoo.
    """
    cr_id = id(env.cr)
    if cr_id in _no_subcontract_domain_cache:
        return _no_subcontract_domain_cache[cr_id]

    sc_loc_ids = env['stock.location'].search(
        [('is_subcontracting_location', '=', True)]
    ).ids
    result = [] if not sc_loc_ids else [('location_src_id', 'not in', sc_loc_ids)]

    _no_subcontract_domain_cache[cr_id] = result
    try:
        weakref.finalize(env.cr, _make_cache_cleanup(cr_id))
    except TypeError:
        # env.cr no soporta weakref en algunos backends de test; ignorar
        pass

    return result

# Prefijos de sangría visual para jerarquías de BoM en vistas HTML.
# Se usa _N (espacio no separable) porque los espacios normales colapsan en HTML.
# Cada nivel agrega 3 caracteres _N antes del conector de árbol '└─ '.
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
