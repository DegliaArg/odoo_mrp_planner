"""
Módulo: resource_calendar.py (odoo_mrp_planner)
Modelo: extensión de resource.calendar

Provee un helper compartido para calcular las horas laborables de un calendario
en un rango, descontando feriados/licencias. Lo usan tanto el panel de carga de
CT (mrp_planner_dashboard_wc) como el tablero de programación
(odoo_mrp_planner_scheduling), para no duplicar la lógica.
"""
import logging

import pytz

from odoo import models

_logger = logging.getLogger(__name__)


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    def _planner_available_hours(self, dt_from, dt_to, cache=None):
        """Horas laborables del calendario en [dt_from, dt_to], descontando
        feriados y licencias (compute_leaves=True).

        :param dt_from: datetime UTC naive — inicio del rango.
        :param dt_to:   datetime UTC naive — fin del rango.
        :param cache:   dict opcional {(cal_id, dt_from, dt_to): horas} para no
                        recalcular el mismo intervalo entre varios CTs/meses.
        :returns: float — horas laborables disponibles en el rango.
        """
        self.ensure_one()
        key = (self.id, dt_from, dt_to)
        if cache is not None and key in cache:
            return cache[key]
        try:
            h = self.get_work_hours_count(
                dt_from.replace(tzinfo=pytz.UTC),
                dt_to.replace(tzinfo=pytz.UTC),
                compute_leaves=True,   # descuenta feriados y licencias del calendario
            )
        except Exception as e:
            _logger.debug("Planner: error calendario %s: %s", self.name, e)
            # Fallback lineal: suma horas semanales de attendance sin fecha y las
            # prorratea por el span del rango.
            weekly = sum(
                a.hour_to - a.hour_from
                for a in self.attendance_ids
                if not a.date_from and not a.date_to
            )
            span = (dt_to - dt_from).days + 1
            h = weekly * (span / 7.0)
        if cache is not None:
            cache[key] = h
        return h
