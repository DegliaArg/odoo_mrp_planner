# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_prod_analysis.py
Modelo: extensión de mrp.planner.dashboard

Backend del panel de Análisis de producción para las pestañas OFs, Producido vs
Programado, Eficiencia y Evolución. Comparte con el resto del panel el guard de
grupos (group_prod_read/group_prod), el filtro de almacén por usuario
(_get_wh_domains) y el criterio de fechas de Ajustes (comparison_date_mode).

Responsabilidades:
- OFs: agregar las órdenes de fabricación del rango por producto (cantidades,
  estados, atrasos) para tabla y KPIs, más la evolución mensual.
- Producido vs Programado: exponer el comparativo ponderado ya existente
  (get_comparison_data) en formato del panel, con su evolución mensual.
- Eficiencia: horas planificadas vs reales por producto (a partir de las OT),
  con su evolución mensual.
- Evolución: resumen mensual que compone las tasas (%) de carga, cumplimiento y
  eficiencia junto con OFs, producido y scrap.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende via _inherit.
- mrp.production / mrp.workorder / stock.scrap: fuentes de los datos.
- mrp_planner_dashboard_mo._comparison_unit_weights / get_comparison_data.
- mrp_planner_dashboard_wc._wc_parse_range / _wc_load_by_center.
"""
import logging
from datetime import datetime, date
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import models, api, fields, _
from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import no_subcontract_domain

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardProdAnalysis(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Helpers compartidos por las pestañas ──────────────────────────────────

    def _pa_wh_mo_domain(self):
        """Dominio de almacén para OFs (respetando el filtro por usuario)."""
        return self._get_wh_domains().mo + [('company_id', '=', self.env.company.id)]

    def _pa_mode(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        return (cfg.comparison_date_mode if cfg else None) or 'finish_date'

    def _pa_mo_period_domain(self, mode, first_str, last_str):
        """Dominio de OFs del período según el criterio de fechas de Ajustes."""
        if mode == 'start_date':
            return [('date_start', '>=', first_str), ('date_start', '<=', last_str)]
        if mode in ('overlap', 'proportional'):
            return [('date_start', '<=', last_str), '|',
                    ('date_finished', '>=', first_str), ('date_finished', '=', False)]
        return [('date_finished', '>=', first_str), ('date_finished', '<=', last_str)]

    def _pa_months(self, date_from, date_to):
        """Itera los meses calendario que solapan el rango (máx. 36), acotando
        cada mes al rango. Yields (ym, seg_from_str, seg_to_str)."""
        d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        d_to   = datetime.strptime(date_to, '%Y-%m-%d').date()
        cur = date(d_from.year, d_from.month, 1)
        guard = 0
        while cur <= d_to and guard < 36:
            guard += 1
            m_end = cur + relativedelta(months=1) - relativedelta(days=1)
            seg_from = max(cur, d_from)
            seg_to   = min(m_end, d_to)
            yield ('%04d-%02d' % (cur.year, cur.month), str(seg_from), str(seg_to))
            cur += relativedelta(months=1)

    # ════════════════════════ Pestaña OFs ════════════════════════

    def _pa_of_rows(self, first_day, last_day):
        """OFs del rango agregadas por producto. Base de la tabla, los KPIs y la
        evolución mensual de OFs."""
        mode = self._pa_mode()
        first_str = fields.Datetime.to_string(first_day)
        last_str  = fields.Datetime.to_string(last_day)
        domain = ([('state', 'not in', ('cancel', 'draft'))]
                  + self._pa_mo_period_domain(mode, first_str, last_str)
                  + no_subcontract_domain(self.env)
                  + self._pa_wh_mo_domain())
        mos = self.env['mrp.production'].search(domain)
        now_s = fields.Datetime.now()

        by_prod = defaultdict(lambda: {
            'ofs': 0, 'programado': 0.0, 'producido': 0.0,
            'terminadas': 0, 'en_curso': 0, 'atrasadas': 0, 'uom': '',
        })
        for mo in mos:
            pid = mo.product_id.id
            if not pid:
                continue
            b = by_prod[pid]
            b['name'] = mo.product_id.display_name
            b['category'] = mo.product_id.categ_id.name or _('Sin categoría')
            b['uom'] = mo.product_uom_id.name if mo.product_uom_id else ''
            b['ofs'] += 1
            b['programado'] += mo.product_qty or 0.0
            b['producido']  += mo.qty_produced or 0.0
            if mo.state == 'done':
                b['terminadas'] += 1
            elif mo.state in ('progress', 'to_close'):
                b['en_curso'] += 1
            if mo.state not in ('done', 'cancel') and mo.date_finished and mo.date_finished < now_s:
                b['atrasadas'] += 1

        rows = []
        for pid, b in by_prod.items():
            prog = b['programado']
            rows.append({
                'product_id': pid,
                'name':       b.get('name', ''),
                'category':   b.get('category', _('Sin categoría')),
                'uom':        b['uom'],
                'ofs':        b['ofs'],
                'programado': round(prog, 2),
                'producido':  round(b['producido'], 2),
                'terminadas': b['terminadas'],
                'en_curso':   b['en_curso'],
                'atrasadas':  b['atrasadas'],
                'avance_pct': round(b['producido'] / prog * 100, 1) if prog > 0 else None,
            })
        return rows, mode

    @api.model
    def get_of_analysis(self, date_from, date_to):
        """OFs del rango por producto (cantidades, estados y atrasos)."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        rows, mode = self._pa_of_rows(first_day, last_day)
        return {'rows': rows, 'date_mode': mode}

    @api.model
    def get_of_trend(self, date_from, date_to):
        """Evolución mensual de OFs: totales del período y terminadas."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        trend = []
        for ym, seg_from, seg_to in self._pa_months(date_from, date_to):
            first_day, last_day = self._wc_parse_range(seg_from, seg_to)
            rows, _m = self._pa_of_rows(first_day, last_day)
            trend.append({
                'ym':         ym,
                'ofs':        sum(r['ofs'] for r in rows),
                'terminadas': sum(r['terminadas'] for r in rows),
            })
        return {'trend': trend}

    # ═══════════════════ Pestaña Producido vs Programado ═══════════════════

    @api.model
    def get_comparison_analysis(self, date_from, date_to):
        """Comparativo producido vs programado por producto, reutilizando la
        lógica ponderada del panel principal (get_comparison_data). Devuelve
        todas las filas (hasta el tope del método base) para paginar del lado
        del cliente, con un aviso si se truncó."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        data = self.get_comparison_data(date_from, date_to, page=1, page_size=200,
                                        sort_field='planned_qty', sort_dir='desc')
        items = data.get('items', [])
        rows = []
        for it in items:
            rows.append({
                'product_id': it['product_id'],
                'name':       it['product'],
                'uom':        it.get('uom', ''),
                'programado': it['planned_qty'],
                'producido':  it['produced_qty'],
                'desvio':     round((it['planned_qty'] or 0.0) - (it['produced_qty'] or 0.0), 2),
                'pct':        it['pct'],
            })
        return {
            'rows':      rows,
            'kpis':      data.get('kpis', {}),
            'date_mode': data.get('mo_mode'),
            'truncated': data.get('total', 0) > len(rows),
            'total':     data.get('total', 0),
        }

    @api.model
    def get_comparison_trend(self, date_from, date_to):
        """Evolución mensual del cumplimiento % ponderado."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        cfg = self.env['mrp.reschedule.config'].get_config()
        green = (cfg.comparison_pct_green if cfg else 0) or 90
        warn  = (cfg.comparison_pct_warn if cfg else 0) or 50
        trend = []
        for ym, seg_from, seg_to in self._pa_months(date_from, date_to):
            data = self.get_comparison_data(seg_from, seg_to, page=1, page_size=1)
            k = data.get('kpis', {})
            trend.append({
                'ym':        ym,
                'pct':       k.get('pct'),
                'programado': k.get('planned', 0.0),
                'producido':  k.get('produced', 0.0),
            })
        return {'trend': trend, 'green': green, 'warn': warn}

    # ════════════════════════ Pestaña Eficiencia ════════════════════════

    def _pa_efficiency_rows(self, first_day, last_day):
        """Horas planificadas vs reales por producto, a partir de las OT del
        rango. Mismo criterio de fechas y prorrateo que la carga de CT."""
        mode = self._pa_mode()
        now_utc = fields.Datetime.now()
        allowed_ids = self._get_wh_domains().allowed_ids

        wos_domain = [
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
        wos = self.env['mrp.workorder'].search(wos_domain)

        def _overlap_frac(w_start, w_end, p_start, p_end):
            if not w_start:
                return 0.0
            if not w_end or w_end <= w_start:
                return 1.0 if p_start <= w_start <= p_end else 0.0
            total = (w_end - w_start).total_seconds()
            ov = (min(w_end, p_end) - max(w_start, p_start)).total_seconds()
            return max(0.0, min(1.0, ov / total))

        by_prod = defaultdict(lambda: {
            'plan_h': 0.0, 'real_h': 0.0, 'ofs': set(), 'uom': '',
        })
        for w in wos:
            prod = w.production_id.product_id
            if not prod:
                continue
            w_end = w.date_finished if (w.state == 'done' and w.date_finished) else now_utc
            if mode == 'proportional':
                frac = _overlap_frac(w.date_start, w_end, first_day, last_day)
            elif mode == 'start_date':
                frac = 1.0 if (w.date_start and first_day <= w.date_start <= last_day) else 0.0
            elif mode == 'overlap':
                frac = 1.0 if _overlap_frac(w.date_start, w_end, first_day, last_day) > 0.0 else 0.0
            else:  # finish_date
                _ref = w.date_finished or (now_utc if w.state != 'done' else None)
                frac = 1.0 if (_ref and first_day <= _ref <= last_day) else 0.0
            if frac <= 0.0:
                continue
            b = by_prod[prod.id]
            b['name'] = prod.display_name
            b['category'] = prod.categ_id.name or _('Sin categoría')
            b['plan_h'] += (w.duration_expected or 0.0) / 60.0 * frac
            b['real_h'] += (w.duration or 0.0) / 60.0 * frac
            b['ofs'].add(w.production_id.id)

        rows = []
        for pid, b in by_prod.items():
            plan = b['plan_h']
            rows.append({
                'product_id': pid,
                'name':       b.get('name', ''),
                'category':   b.get('category', _('Sin categoría')),
                'ofs':        len(b['ofs']),
                'plan_h':     round(plan, 1),
                'real_h':     round(b['real_h'], 1),
                'eficiencia': round(b['real_h'] / plan * 100, 1) if plan > 0 else None,
            })
        return rows, mode

    @api.model
    def get_efficiency_analysis(self, date_from, date_to):
        """Eficiencia (real ÷ planificado) por producto, a partir de las OT."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        rows, mode = self._pa_efficiency_rows(first_day, last_day)
        cfg = self.env['mrp.reschedule.config'].get_config()
        return {
            'rows': rows,
            'date_mode': mode,
            'warn_pct': (cfg.wc_load_warn_pct if cfg else 0) or 70,
            'crit_pct': (cfg.wc_load_crit_pct if cfg else 0) or 90,
        }

    @api.model
    def get_efficiency_trend(self, date_from, date_to):
        """Evolución mensual de la eficiencia % (Σ real ÷ Σ plan)."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        trend = []
        for ym, seg_from, seg_to in self._pa_months(date_from, date_to):
            first_day, last_day = self._wc_parse_range(seg_from, seg_to)
            rows, _m = self._pa_efficiency_rows(first_day, last_day)
            plan = sum(r['plan_h'] for r in rows)
            real = sum(r['real_h'] for r in rows)
            trend.append({
                'ym':         ym,
                'eficiencia': round(real / plan * 100, 1) if plan > 0 else None,
                'plan_h':     round(plan, 1),
                'real_h':     round(real, 1),
            })
        return {'trend': trend}

    # ════════════════════════ Pestaña Evolución ════════════════════════

    @api.model
    def get_evolution_analysis(self, date_from, date_to):
        """Resumen mensual que compone las tasas (%) de carga, cumplimiento y
        eficiencia junto con OFs terminadas, producido y scrap. Combina los
        building blocks de las otras pestañas para no duplicar lógica."""
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        carga = {m['ym']: m for m in self.get_wc_load_trend(date_from, date_to)['trend']}
        cumpl = {m['ym']: m for m in self.get_comparison_trend(date_from, date_to)['trend']}
        efic  = {m['ym']: m for m in self.get_efficiency_trend(date_from, date_to)['trend']}
        scrap = {m['ym']: m for m in self.get_scrap_trend(date_from, date_to)['trend']}
        ofs   = {m['ym']: m for m in self.get_of_trend(date_from, date_to)['trend']}

        cfg = self.env['mrp.reschedule.config'].get_config()
        rows = []
        for ym, _sf, _st in self._pa_months(date_from, date_to):
            rows.append({
                'ym':          ym,
                'ofs':         (ofs.get(ym) or {}).get('ofs', 0),
                'terminadas':  (ofs.get(ym) or {}).get('terminadas', 0),
                'producido':   (cumpl.get(ym) or {}).get('producido', 0.0),
                'carga_pct':   (carga.get(ym) or {}).get('carga_pct'),
                'cumpl_pct':   (cumpl.get(ym) or {}).get('pct'),
                'efic_pct':    (efic.get(ym) or {}).get('eficiencia'),
                'scrap':       (scrap.get(ym) or {}).get('qty', 0.0),
            })
        return {
            'rows': rows,
            'warn_pct':   (cfg.wc_load_warn_pct if cfg else 0) or 70,
            'crit_pct':   (cfg.wc_load_crit_pct if cfg else 0) or 90,
            'cumpl_green': (cfg.comparison_pct_green if cfg else 0) or 90,
        }
