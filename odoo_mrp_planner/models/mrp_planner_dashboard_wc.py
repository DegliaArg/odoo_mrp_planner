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
from datetime import datetime, date
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardWc(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Panel de Análisis de producción ───────────────────────────────────────

    @api.model
    def action_open_production_analysis(self):
        """Abre el Panel de Análisis de producción (vista form sin barra de control)."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Análisis de producción'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_production_analysis_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_production_analysis(self):
        """Botón Actualizar del panel: reabre la vista con un registro nuevo."""
        return self.action_open_production_analysis()

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
        enable_scheduling = self.env['mrp.reschedule.config']._scheduling_ui_enabled()
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

        enable_scheduling = self.env['mrp.reschedule.config']._scheduling_ui_enabled()
        _cfg = self.env['mrp.reschedule.config'].get_config()
        return {
            'tags': [
                {'id': tag.id, 'name': tag.name}
                for tag in Tag.search([])
                if tag.id in active_tag_ids
            ],
            'enable_scheduling': enable_scheduling,
            'enable_oee': bool(_cfg.enable_oee) if _cfg else False,
        }

    @api.model
    def _wc_parse_range(self, date_from, date_to):
        """Cortes del rango como Datetimes UTC naive, interpretados en el huso
        del usuario (los datetime de Odoo se guardan en UTC)."""
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        first_day = tz.localize(datetime.strptime(date_from, '%Y-%m-%d')) \
            .astimezone(pytz.UTC).replace(tzinfo=None)
        last_day = tz.localize(datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)) \
            .astimezone(pytz.UTC).replace(tzinfo=None)
        return first_day, last_day

    def _wc_fetch_data(self, first_day, last_day, tag_id=None):
        """Prefetch de centros de trabajo + sus OT que solapan [first_day, last_day].

        Se busca UNA sola vez el rango completo. La tabla/gráfico lo usan directo
        y la evolución mensual reutiliza el mismo recordset filtrando por mes en
        memoria (ver get_wc_load_trend), evitando N búsquedas SQL.

        :returns: (workcenters, wos_by_wc, allowed_ids) — wos_by_wc = dict
                  {wc_id: [workorder, ...]} con TODAS las OT del rango.
        """
        domain = [('active', '=', True)]
        if tag_id:
            domain.append(('tag_ids', 'in', int(tag_id)))
        workcenters = self.env['mrp.workcenter'].search(domain)

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
            ('company_id', '=', self.env.company.id),
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
        return workcenters, wos_by_wc, allowed_ids

    def _wc_load_by_center(self, first_day, last_day, tag_id=None, prefetch=None,
                           cal_cache=None):
        """Carga por centro de trabajo en [first_day, last_day] (UTC naive).

        Una fila por CT con actividad, asignando cada OT al período con el MISMO
        criterio de fechas configurado en Ajustes para la comparativa y el
        forecast (comparison_date_mode). Base compartida del gráfico, la tabla
        de detalle y la evolución mensual.

        :param prefetch: (workcenters, wos_by_wc, allowed_ids) ya obtenidos con
                         _wc_fetch_data sobre un rango que CONTENGA a este; si es
                         None se buscan acá. Las OT fuera del segmento aportan
                         fracción 0 (se filtran igual), así que los números son
                         idénticos a buscar el segmento directo.
        :param cal_cache: dict compartido de horas de calendario (para no
                          recalcular el mismo intervalo entre meses/CTs).
        :returns: (rows, wc_mode).
        """
        if prefetch is None:
            workcenters, wos_by_wc, allowed_ids = self._wc_fetch_data(first_day, last_day, tag_id)
        else:
            workcenters, wos_by_wc, allowed_ids = prefetch

        # Caché de horas brutas de calendario: evita recalcular el mismo intervalo
        # cuando varios CTs comparten el mismo resource.calendar (y entre meses).
        _cal_hours_cache = cal_cache if cal_cache is not None else {}

        def _avail_hours(calendar, dt_start, dt_end):
            key = (calendar.id, dt_start, dt_end)
            if key not in _cal_hours_cache:
                try:
                    h = calendar.get_work_hours_count(
                        dt_start.replace(tzinfo=pytz.UTC),
                        dt_end.replace(tzinfo=pytz.UTC),
                        compute_leaves=True,   # descuenta feriados y licencias del calendario
                    )
                except Exception as e:
                    _logger.debug("WC load: error calendario %s: %s", calendar.name, e)
                    weekly = sum(
                        a.hour_to - a.hour_from
                        for a in calendar.attendance_ids
                        if not a.date_from and not a.date_to
                    )
                    span = (dt_end - dt_start).days + 1
                    h = weekly * (span / 7.0)
                _cal_hours_cache[key] = h
            # La eficiencia del CT NO multiplica la capacidad (en Odoo ajusta la
            # duración esperada de las operaciones, no las horas del calendario).
            return _cal_hours_cache[key]

        now_utc = fields.Datetime.now()
        _cfg    = self.env['mrp.reschedule.config'].get_config()
        wc_mode = (_cfg.comparison_date_mode if _cfg else None) or 'finish_date'

        def _overlap_frac(w_start, w_end, p_start, p_end):
            if not w_start:
                return 0.0
            if not w_end or w_end <= w_start:
                return 1.0 if p_start <= w_start <= p_end else 0.0
            total = (w_end - w_start).total_seconds()
            ov = (min(w_end, p_end) - max(w_start, p_start)).total_seconds()
            return max(0.0, min(1.0, ov / total))

        rows = []
        for wc in workcenters:
            avail = 0.0
            if wc.resource_calendar_id:
                avail = _avail_hours(wc.resource_calendar_id, first_day, last_day)

            wos = wos_by_wc.get(wc.id, [])
            ejecutado = pendiente = planificado = no_planificado = 0.0
            for w in wos:
                w_end = w.date_finished if (w.state == 'done' and w.date_finished) else now_utc
                if wc_mode == 'proportional':
                    frac = _overlap_frac(w.date_start, w_end, first_day, last_day)
                elif wc_mode == 'start_date':
                    frac = 1.0 if (w.date_start and first_day <= w.date_start <= last_day) else 0.0
                elif wc_mode == 'overlap':
                    frac = 1.0 if _overlap_frac(w.date_start, w_end, first_day, last_day) > 0.0 else 0.0
                else:  # finish_date
                    _ref = w.date_finished or (now_utc if w.state != 'done' else None)
                    frac = 1.0 if (_ref and first_day <= _ref <= last_day) else 0.0
                if frac <= 0.0:
                    continue
                real_p = (w.duration or 0.0) / 60.0 * frac
                plan_p = (w.duration_expected or 0.0) / 60.0 * frac
                ejecutado   += real_p
                planificado += plan_p
                if w.state != 'done':
                    pendiente += max(0.0, plan_p - real_p)
                no_planificado += max(0.0, real_p - plan_p)

            # Excluir CTs sin actividad en el período.
            if allowed_ids is not None:
                if ejecutado == 0.0 and pendiente == 0.0:
                    continue
            elif avail == 0.0 and ejecutado == 0.0 and pendiente == 0.0:
                continue

            rows.append({
                'wc_id':          wc.id,
                'name':           wc.name,
                'tags':           wc.tag_ids.mapped('name'),
                'disponible':     round(avail, 1),
                'planificado':    round(planificado, 1),
                'ejecutado':      round(ejecutado, 1),
                'pendiente':      round(pendiente, 1),
                'no_planificado': round(no_planificado, 1),
            })
        return rows, wc_mode

    @api.model
    def get_wc_chart_data(self, date_from, date_to, tag_id=None):
        """Carga de CTs del rango, en el formato de arrays paralelos que consume
        el gráfico del panel de Producción (foto rápida). Ver _wc_load_by_center.
        """
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        rows, wc_mode = self._wc_load_by_center(first_day, last_day, tag_id)
        _cfg = self.env['mrp.reschedule.config'].get_config()

        tot_avail  = sum(r['disponible']     for r in rows)
        tot_plan   = sum(r['planificado']    for r in rows)
        tot_ejec   = sum(r['ejecutado']      for r in rows)
        tot_pend   = sum(r['pendiente']      for r in rows)
        tot_noplan = sum(r['no_planificado'] for r in rows)
        carga_pct  = round(tot_plan / tot_avail * 100, 1) if tot_avail > 0 else 0.0

        return {
            'labels':          [r['name'] for r in rows],
            'available_hours': [r['disponible'] for r in rows],
            'planificado':     [r['planificado'] for r in rows],
            'ejecutado':       [r['ejecutado'] for r in rows],
            'pendiente':       [r['pendiente'] for r in rows],
            'no_planificado':  [r['no_planificado'] for r in rows],
            'totals': {
                'disponible':      round(tot_avail,  1),
                'planificado':     round(tot_plan,   1),
                'carga_pct':       carga_pct,
                'ejecutado':       round(tot_ejec,   1),
                'pendiente':       round(tot_pend,   1),
                'no_planificado':  round(tot_noplan, 1),
                'warn_pct':        (_cfg.wc_load_warn_pct if _cfg else 0) or 70,
                'crit_pct':        (_cfg.wc_load_crit_pct if _cfg else 0) or 90,
                'date_mode':       wc_mode,
            },
        }

    @api.model
    def get_wc_load_table(self, date_from, date_to, tag_id=None):
        """Tabla de detalle por CT: una fila por centro con horas y métricas
        derivadas (carga %, holgura = disponible − planificado, eficiencia =
        ejecutado ÷ planificado). Para el panel de Análisis de producción.

        :returns: dict {'rows': list[dict], 'totals': dict, 'date_mode': str}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        rows, wc_mode = self._wc_load_by_center(first_day, last_day, tag_id)
        _cfg = self.env['mrp.reschedule.config'].get_config()

        out = []
        for r in rows:
            disp, plan, ejec = r['disponible'], r['planificado'], r['ejecutado']
            out.append({
                **r,
                'carga_pct':   round(plan / disp * 100, 1) if disp > 0 else None,
                'holgura':     round(disp - plan, 1),
                'eficiencia':  round(ejec / plan * 100, 1) if plan > 0 else None,
            })
        tot_avail = sum(r['disponible']  for r in rows)
        tot_plan  = sum(r['planificado'] for r in rows)
        return {
            'rows': out,
            'date_mode': wc_mode,
            'totals': {
                'disponible':     round(tot_avail, 1),
                'planificado':    round(tot_plan, 1),
                'ejecutado':      round(sum(r['ejecutado'] for r in rows), 1),
                'pendiente':      round(sum(r['pendiente'] for r in rows), 1),
                'no_planificado': round(sum(r['no_planificado'] for r in rows), 1),
                'carga_pct':      round(tot_plan / tot_avail * 100, 1) if tot_avail > 0 else None,
                'warn_pct':       (_cfg.wc_load_warn_pct if _cfg else 0) or 70,
                'crit_pct':       (_cfg.wc_load_crit_pct if _cfg else 0) or 90,
            },
        }

    @api.model
    def get_wc_load_trend(self, date_from, date_to, tag_id=None):
        """Evolución mensual de la carga % de CT en el rango (histórico).

        Un punto por mes calendario que solape el rango; cada mes se acota al
        rango y se calcula su carga % (Σ planificado ÷ Σ disponible). Meses sin
        disponible quedan con rate None.

        :returns: dict {'trend': [{'ym','carga_pct','disponible','planificado'}],
                        'warn_pct': int, 'crit_pct': int}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        d_to   = datetime.strptime(date_to, '%Y-%m-%d').date()
        _cfg = self.env['mrp.reschedule.config'].get_config()

        # Un solo prefetch del rango completo + una caché de calendario compartida:
        # cada mes se calcula filtrando el recordset en memoria (sin re-buscar).
        full_first, full_last = self._wc_parse_range(date_from, date_to)
        prefetch = self._wc_fetch_data(full_first, full_last, tag_id)
        cal_cache = {}

        trend = []
        cur = date(d_from.year, d_from.month, 1)
        # Cota defensiva de 36 meses para no disparar cálculos enormes.
        guard = 0
        while cur <= d_to and guard < 36:
            guard += 1
            m_end = cur + relativedelta(months=1) - relativedelta(days=1)
            seg_from = max(cur, d_from)
            seg_to   = min(m_end, d_to)
            first_day, last_day = self._wc_parse_range(str(seg_from), str(seg_to))
            rows, _ = self._wc_load_by_center(first_day, last_day, tag_id,
                                              prefetch=prefetch, cal_cache=cal_cache)
            disp = sum(r['disponible'] for r in rows)
            plan = sum(r['planificado'] for r in rows)
            trend.append({
                'ym':          '%04d-%02d' % (cur.year, cur.month),
                'carga_pct':   round(plan / disp * 100, 1) if disp > 0 else None,
                'disponible':  round(disp, 1),
                'planificado': round(plan, 1),
            })
            cur += relativedelta(months=1)
        return {
            'trend': trend,
            'warn_pct': (_cfg.wc_load_warn_pct if _cfg else 0) or 70,
            'crit_pct': (_cfg.wc_load_crit_pct if _cfg else 0) or 90,
        }
