# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_wc.py
Modelo: extensión de mrp.planner.dashboard

Agrega al dashboard MRP los métodos de análisis de carga de Centros de Trabajo (WC).

Responsabilidades:
- Exponer la lista de tags de centros de trabajo con al menos un CT activo.
- Calcular horas disponibles, ejecutadas, pendientes y tiempo muerto por CT en un rango de fechas.
- Producir el ranking de los 10 CTs con mayor carga planificada en OFs activas.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende via _inherit.
- mrp.workcenter: fuente de datos de capacidad y eficiencia de cada CT.
- mrp.workorder: operaciones de producción que consumen la capacidad de los CTs.
- resource.calendar: calendario laboral usado para calcular horas disponibles.
"""
import logging
import pytz
from datetime import datetime
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardWc(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Filtros de sector (WC tags) — usados por widgets de OFs ────────────

    @api.model
    def get_mo_warehouses(self):
        """Devuelve almacenes disponibles para el widget de OFs y flag de programación."""
        allowed = self._get_wh_domains().allowed_ids
        if allowed is None:
            whs = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)])
        elif not allowed:
            whs = self.env['stock.warehouse']
        else:
            whs = self.env['stock.warehouse'].browse(allowed)
        cfg = self.env['mrp.reschedule.config'].get_config()
        u = self.env.user
        has_scheduling = (
            u.has_group('odoo_mrp_planner.group_scheduling') or
            u.has_group('odoo_mrp_planner.group_admin') or
            u.has_group('base.group_system')
        )
        enable_scheduling = bool(cfg.enable_scheduling) and has_scheduling if cfg else has_scheduling
        return {
            'warehouses': [{'id': wh.id, 'name': wh.name} for wh in whs.sorted('name')],
            'enable_scheduling': enable_scheduling,
        }

    @api.model
    def get_wc_tags(self):
        """Devuelve la lista de tags de CTs que tienen al menos un centro de trabajo activo.

        Usa una sola query para obtener todos los tag IDs con WCs activos, evitando el
        patrón N+1 (un search_count por tag) que existía en la implementación original.

        :returns: list[dict] — lista de dicts ``{'id': int, 'name': str}`` ordenada
                  según el orden natural de ``mrp.workcenter.tag``.
        """
        Tag = self.env['mrp.workcenter.tag']
        Wc  = self.env['mrp.workcenter']
        allowed_ids = self._get_wh_domains().allowed_ids

        active_wcs = Wc.search([('active', '=', True)])
        if allowed_ids is None:
            # Sin restricción: todos los CTs activos
            relevant_wc_ids = set(active_wcs.ids)
        elif not allowed_ids:
            # Sin acceso a ningún depósito
            relevant_wc_ids = set()
        else:
            # Solo CTs con workorders de los depósitos permitidos
            relevant_wc_ids = set(
                self.env['mrp.workorder'].search([
                    ('workcenter_id', 'in', active_wcs.ids),
                    ('production_id.picking_type_id.warehouse_id', 'in', allowed_ids),
                ]).mapped('workcenter_id').ids
            )

        active_tag_ids = set(
            Wc.browse(list(relevant_wc_ids)).mapped('tag_ids').ids
        )

        cfg = self.env['mrp.reschedule.config'].get_config()
        u = self.env.user
        has_scheduling = (
            u.has_group('odoo_mrp_planner.group_scheduling') or
            u.has_group('odoo_mrp_planner.group_admin') or
            u.has_group('base.group_system')
        )
        enable_scheduling = bool(cfg.enable_scheduling) and has_scheduling if cfg else has_scheduling
        return {
            'tags': [
                {'id': tag.id, 'name': tag.name}
                for tag in Tag.search([])
                if tag.id in active_tag_ids
            ],
            'enable_scheduling': enable_scheduling,
        }

    @api.model
    def get_wc_chart_data(self, date_from, date_to, tag_id=None):
        """Calcula la carga de Centros de Trabajo en el rango de fechas indicado.

        Modelo sin registro de tiempo real: todo en horas ESTÁNDAR (duration_expected),
        que es el único dato confiable cuando no se loguea tiempo en planta.
        Para cada CT activo (filtrado opcionalmente por tag) determina (en horas):
        - Disponible: horas del calendario laboral ajustadas por eficiencia.
        - Completado: Σ duration_expected de las OT terminadas que solapan el período.
        - Pendiente: Σ duration_expected de las OT no terminadas que solapan el período.
        - Planificado: Completado + Pendiente.
        - Carga %: Planificado ÷ Disponible × 100.
        - Avance %: Completado ÷ Planificado × 100.

        La atribución es simétrica (Completado y Pendiente por solapamiento). Los cortes del
        período se convierten a UTC según el huso del usuario. Los workorders se cargan en
        un único batch (evita N+1) y las horas de calendario se cachean por intervalo.
        Los CTs sin nada planificado en el período se omiten.

        :param date_from: str — fecha de inicio en formato ``'YYYY-MM-DD'``.
        :param date_to:   str — fecha de fin en formato ``'YYYY-MM-DD'`` (inclusive, hasta las 23:59:59).
        :param tag_id:    int | None — si se indica, filtra los CTs que tengan ese tag.
        :returns: dict con las claves:
                  - ``labels`` (list[str]): nombres de CTs incluidos.
                  - ``available_hours`` (list[float]): horas disponibles por CT.
                  - ``planificado`` (list[float]): horas planificadas por CT.
                  - ``completado`` (list[float]): horas estándar de OT terminadas por CT.
                  - ``pendiente`` (list[float]): horas estándar de OT no terminadas por CT.
                  - ``totals`` (dict): sumatorios globales, carga % y avance %.
        """
        # Los cortes se interpretan en el huso del usuario y se convierten a UTC (los
        # datetime de Odoo se almacenan en UTC). Así el borde del período coincide con lo
        # que el usuario ve en la lista de OT y no se corre por diferencia horaria.
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        first_day = tz.localize(datetime.strptime(date_from, '%Y-%m-%d')) \
            .astimezone(pytz.UTC).replace(tzinfo=None)
        last_day = tz.localize(datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)) \
            .astimezone(pytz.UTC).replace(tzinfo=None)

        domain = [('active', '=', True)]
        if tag_id:
            domain.append(('tag_ids', 'in', int(tag_id)))
        workcenters = self.env['mrp.workcenter'].search(domain)

        labels, avail_list, pendiente_list = [], [], []

        # Caché de horas brutas de calendario: evita recalcular el mismo intervalo
        # cuando varios CTs comparten el mismo resource.calendar.
        _cal_hours_cache = {}  # (calendar_id, dt_start, dt_end) -> raw hours (sin efficiency)

        def _avail_hours(calendar, dt_start, dt_end, efficiency):
            """Devuelve las horas efectivas del calendario ajustadas por eficiencia del CT.

            Primero intenta ``get_work_hours_count`` del recurso; si falla (calendario
            atípico o sin attendances periódicos), calcula un promedio semanal a partir
            de las líneas de asistencia sin fecha de vigencia y lo extrapola al span.
            """
            key = (calendar.id, dt_start, dt_end)
            if key not in _cal_hours_cache:
                try:
                    h = calendar.get_work_hours_count(
                        dt_start.replace(tzinfo=pytz.UTC),
                        dt_end.replace(tzinfo=pytz.UTC),
                        compute_leaves=False,
                    )
                except Exception as e:
                    _logger.debug("WC chart: error calendario %s: %s", calendar.name, e)
                    weekly = sum(
                        a.hour_to - a.hour_from
                        for a in calendar.attendance_ids
                        if not a.date_from and not a.date_to
                    )
                    span = (dt_end - dt_start).days + 1
                    h = weekly * (span / 7.0)
                _cal_hours_cache[key] = h
            return _cal_hours_cache[key] * (efficiency or 100.0) / 100.0

        # Fix 19: cargar todos los workorders en 1 query batch antes del loop
        allowed_ids = self._get_wh_domains().allowed_ids
        wos_domain = [
            ('workcenter_id', 'in', workcenters.ids),
            ('state', 'not in', ('cancel',)),
            ('date_start', '!=', False),
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            ('date_finished', '=', False),
            ('production_id.location_src_id.is_subcontracting_location', '!=', True),
        ]
        if allowed_ids is not None:
            if not allowed_ids:
                wos_domain.append(('id', '=', False))
            else:
                wos_domain.append(('production_id.picking_type_id.warehouse_id', 'in', allowed_ids))
        all_wos = self.env['mrp.workorder'].search(wos_domain)
        wos_by_wc = defaultdict(list)
        for wo in all_wos:
            wos_by_wc[wo.workcenter_id.id].append(wo)

        planificado_list, completado_list = [], []

        for wc in workcenters:
            efficiency = wc.time_efficiency or 100.0
            avail = 0.0
            if wc.resource_calendar_id:
                avail = _avail_hours(wc.resource_calendar_id, first_day, last_day, efficiency)

            wos = wos_by_wc.get(wc.id, [])  # cargado en batch antes del loop

            # Modelo sin registro de tiempo real (todo en horas ESTÁNDAR, duration_expected):
            #   Completado  = Σ duration_expected de las OT terminadas que solapan el período.
            #   Pendiente   = Σ duration_expected de las OT no terminadas que solapan el período.
            #   Planificado = Completado + Pendiente.
            # Atribución simétrica: el universo ya está filtrado por solapamiento (state ≠ cancel).
            completado = pendiente = 0.0
            for w in wos:
                exp = (w.duration_expected or 0.0) / 60.0
                if w.state == 'done':
                    completado += exp
                else:
                    pendiente += exp

            planificado = completado + pendiente

            # Excluir CTs sin nada planificado en el período.
            if allowed_ids is not None:
                if planificado == 0.0:
                    continue
            elif avail == 0.0 and planificado == 0.0:
                continue

            labels.append(wc.name)
            avail_list.append(round(avail, 1))
            planificado_list.append(round(planificado, 1))
            completado_list.append(round(completado, 1))
            pendiente_list.append(round(pendiente, 1))

        tot_avail = sum(avail_list)
        tot_plan  = sum(planificado_list)
        tot_comp  = sum(completado_list)
        tot_pend  = sum(pendiente_list)
        carga_pct  = round(tot_plan / tot_avail * 100, 1) if tot_avail > 0 else 0.0
        avance_pct = round(tot_comp / tot_plan * 100, 1) if tot_plan > 0 else 0.0

        return {
            'labels':          labels,
            'available_hours': avail_list,
            'planificado':     planificado_list,
            'completado':      completado_list,
            'pendiente':       pendiente_list,
            'totals': {
                'disponible':   round(tot_avail, 1),
                'planificado':  round(tot_plan,  1),
                'carga_pct':    carga_pct,
                'completado':   round(tot_comp,  1),
                'pendiente':    round(tot_pend,  1),
                'avance_pct':   avance_pct,
            },
        }
