# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_scrap.py
Modelo: extensión de mrp.planner.dashboard

Agrega al dashboard MRP el análisis de desechos (stock.scrap) para el panel de
Análisis de producción.

Responsabilidades:
- Agrupar los desechos validados del período por producto (con su categoría y el
  centro de trabajo más frecuente) para la tabla de detalle.
- Calcular KPIs del período: cantidad desechada, operaciones y productos distintos.
- Producir la evolución mensual de la cantidad desechada (histórico).

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende via _inherit.
- stock.scrap: fuente de los desechos (cantidad, producto, ubicación, fecha).
"""
import logging
from datetime import datetime, date
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import models, api, fields, _

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardScrap(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Desechos (stock.scrap) — panel de Análisis de producción ──────────────

    def _scrap_domain(self, first_day, last_day):
        """Dominio de desechos validados del rango, respetando el filtro de
        almacén del usuario (por el almacén de la ubicación de origen)."""
        domain = [
            ('state', '=', 'done'),
            ('date_done', '>=', fields.Datetime.to_string(first_day)),
            ('date_done', '<=', fields.Datetime.to_string(last_day)),
            ('company_id', '=', self.env.company.id),
        ]
        allowed_ids = self._get_wh_domains().allowed_ids
        if allowed_ids is not None:
            if not allowed_ids:
                domain.append(('id', '=', False))
            else:
                domain.append(('location_id.warehouse_id', 'in', allowed_ids))
        return domain

    @api.model
    def get_scrap_analysis(self, date_from, date_to):
        """Desechos validados del rango agrupados por producto.

        Cada fila lleva el producto, su categoría, el centro de trabajo con más
        desechos del producto (o '—' si el desecho no proviene de una OT), la
        cantidad desechada, la cantidad de operaciones y el % sobre el total.

        :returns: dict {'rows': list[dict], 'totals': dict}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        scraps = self.env['stock.scrap'].search(self._scrap_domain(first_day, last_day))

        by_prod = defaultdict(lambda: {
            'qty': 0.0, 'ops': 0, 'uom': '', 'wc': defaultdict(float),
        })
        for s in scraps:
            b = by_prod[s.product_id.id]
            b['qty'] += s.scrap_qty or 0.0
            b['ops'] += 1
            b['uom'] = s.product_uom_id.name or ''
            b['name'] = s.product_id.display_name
            b['category'] = s.product_id.categ_id.name or _('Sin categoría')
            wc = s.workorder_id.workcenter_id
            if wc:
                b['wc'][wc.name] += s.scrap_qty or 0.0

        total_qty = sum(b['qty'] for b in by_prod.values())
        rows = []
        for pid, b in by_prod.items():
            top_wc = max(b['wc'].items(), key=lambda kv: kv[1])[0] if b['wc'] else '—'
            rows.append({
                'product_id': pid,
                'name':       b.get('name', ''),
                'category':   b.get('category', _('Sin categoría')),
                'workcenter': top_wc,
                'qty':        round(b['qty'], 2),
                'ops':        b['ops'],
                'uom':        b['uom'],
                'pct':        round(b['qty'] / total_qty * 100, 1) if total_qty > 0 else None,
            })
        return {
            'rows': rows,
            'totals': {
                'qty':      round(total_qty, 2),
                'ops':      sum(b['ops'] for b in by_prod.values()),
                'products': len(by_prod),
            },
        }

    @api.model
    def get_scrap_trend(self, date_from, date_to):
        """Evolución mensual de la cantidad desechada en el rango (histórico).

        Un punto por mes calendario que solape el rango; la cantidad suma
        unidades posiblemente mixtas (distintos productos/UdM), útil como
        tendencia relativa más que como magnitud absoluta.

        :returns: dict {'trend': [{'ym','qty','ops'}]}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        d_to   = datetime.strptime(date_to, '%Y-%m-%d').date()

        trend = []
        cur = date(d_from.year, d_from.month, 1)
        guard = 0
        while cur <= d_to and guard < 36:
            guard += 1
            m_end = cur + relativedelta(months=1) - relativedelta(days=1)
            seg_from = max(cur, d_from)
            seg_to   = min(m_end, d_to)
            first_day, last_day = self._wc_parse_range(str(seg_from), str(seg_to))
            scraps = self.env['stock.scrap'].search(self._scrap_domain(first_day, last_day))
            trend.append({
                'ym':  '%04d-%02d' % (cur.year, cur.month),
                'qty': round(sum(s.scrap_qty or 0.0 for s in scraps), 2),
                'ops': len(scraps),
            })
            cur += relativedelta(months=1)
        return {'trend': trend}
