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
- Calcular la tasa de scrap = desecho ÷ (producido + desecho) por producto y
  global (dimensión Calidad del OEE), separando el desecho de insumos que no
  tienen producción asociada en el período (no comparten denominador).
- Calcular KPIs del período: cantidad desechada, tasa, operaciones y productos.
- Producir la evolución mensual de la cantidad desechada y de la tasa.

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende via _inherit.
- stock.scrap: fuente de los desechos (cantidad, producto, ubicación, fecha).
- mrp.production: cantidad producida del período (denominador de la tasa),
  con el mismo criterio de fechas/almacén que el resto del panel
  (_pa_mode/_pa_mo_period_domain/_pa_wh_mo_domain de prod_analysis).
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

    def _scrap_produced_by_product(self, first_day, last_day, tag_id=None, mos=None):
        """Cantidad producida del rango por producto (denominador de la tasa de
        scrap y filtro de sector efectivo), con el mismo criterio de
        fechas/subcontratación/almacén que las demás pestañas del panel.

        :param tag_id: acota a las OFs cuyas OT tocan ese sector (tag de CT).
        :param mos: recordset prefetch-eado de un rango contenedor (evolución
                    mensual); se filtra al segmento en memoria.
        :returns: (produced_map {product_id: qty}, total_produced).
        """
        if mos is None:
            mos = self._pa_fetch_mos(first_day, last_day, tag_id)
        else:
            mode = self._pa_mode()
            mos = mos.filtered(lambda m: self._pa_mo_in_period(m, mode, first_day, last_day))
        produced = defaultdict(float)
        for mo in mos:
            if mo.product_id:
                produced[mo.product_id.id] += mo.qty_produced or 0.0
        return produced, sum(produced.values())

    @staticmethod
    def _scrap_rate(scrap_qty, produced_qty):
        """Tasa de scrap = desecho ÷ (producido + desecho) × 100 (Good ÷ Total del
        OEE). None si el producto no tuvo producción en el período (es insumo:
        no comparte denominador con ningún terminado)."""
        if produced_qty <= 0:
            return None
        denom = produced_qty + scrap_qty
        return round(scrap_qty / denom * 100, 1) if denom > 0 else None

    @api.model
    def get_scrap_analysis(self, date_from, date_to, tag_id=None):
        """Desechos validados del rango agrupados por producto.

        Solo se consideran los desechos de productos CON producción propia en el
        período (terminados): el desecho de insumos/componentes se excluye por
        completo (tabla, total y %), porque no comparte denominador con ningún
        terminado. Cada fila lleva el producto, su categoría, el centro de
        trabajo con más desechos, la cantidad desechada, el % sobre el total, la
        cantidad producida y la tasa de scrap (desecho ÷ (producido + desecho)).

        :param tag_id: acota al sector (tag de CT) vía la producción del período.
        :returns: dict {'rows': list[dict], 'totals': dict}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        first_day, last_day = self._wc_parse_range(date_from, date_to)
        scraps = self.env['stock.scrap'].search(self._scrap_domain(first_day, last_day))
        produced_map, total_produced = self._scrap_produced_by_product(first_day, last_day, tag_id)
        sectors_map = self._pa_product_sectors(first_day, last_day)

        by_prod = defaultdict(lambda: {
            'qty': 0.0, 'ops': 0, 'uom': '', 'wc': defaultdict(float),
        })
        for s in scraps:
            # Solo terminados del sector: los insumos (sin producción propia) y
            # los productos fuera del sector quedan fuera del panel.
            if produced_map.get(s.product_id.id, 0.0) <= 0:
                continue
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
                'sectors':    sectors_map.get(pid, []),
                'workcenter': top_wc,
                'qty':        round(b['qty'], 2),
                'ops':        b['ops'],
                'uom':        b['uom'],
                'producido':  round(produced_map.get(pid, 0.0), 2),
                'tasa':       self._scrap_rate(b['qty'], produced_map.get(pid, 0.0)),
                'pct':        round(b['qty'] / total_qty * 100, 1) if total_qty > 0 else None,
            })
        # Tasa global a nivel planta: desecho de terminados ÷ (producido + ese desecho).
        # Suma unidades posiblemente mixtas ⇒ leer como indicador, no magnitud exacta.
        tasa_global = self._scrap_rate(total_qty, total_produced)
        return {
            'rows': rows,
            'totals': {
                'qty':       round(total_qty, 2),
                'ops':       sum(b['ops'] for b in by_prod.values()),
                'products':  len(by_prod),
                'producido': round(total_produced, 2),
                'tasa':      tasa_global,
            },
        }

    @api.model
    def get_scrap_trend(self, date_from, date_to, tag_id=None):
        """Evolución mensual de la cantidad desechada y de la tasa de scrap.

        Un punto por mes calendario que solape el rango. Solo cuenta el desecho
        de terminados (los insumos se excluyen, igual que la tabla). La cantidad
        suma unidades posiblemente mixtas (distintos productos/UdM), útil como
        tendencia relativa. La tasa mensual = desecho ÷ (producido + desecho) del
        mes (None si no hubo producción).

        Un solo prefetch (desechos + OFs del rango completo); cada mes filtra en
        memoria en vez de re-buscar.

        :returns: dict {'trend': [{'ym','qty','ops','tasa'}]}.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_prod_read',
                                   'odoo_mrp_planner.group_prod')
        d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        d_to   = datetime.strptime(date_to, '%Y-%m-%d').date()

        full_first, full_last = self._wc_parse_range(date_from, date_to)
        all_scraps = self.env['stock.scrap'].search(self._scrap_domain(full_first, full_last))
        all_mos    = self._pa_fetch_mos(full_first, full_last, tag_id)

        trend = []
        cur = date(d_from.year, d_from.month, 1)
        guard = 0
        while cur <= d_to and guard < 36:
            guard += 1
            m_end = cur + relativedelta(months=1) - relativedelta(days=1)
            seg_from = max(cur, d_from)
            seg_to   = min(m_end, d_to)
            first_day, last_day = self._wc_parse_range(str(seg_from), str(seg_to))
            scraps = all_scraps.filtered(
                lambda s: s.date_done and first_day <= s.date_done <= last_day)
            produced_map, total_produced = self._scrap_produced_by_product(
                first_day, last_day, tag_id, mos=all_mos)
            terminados = scraps.filtered(lambda s: produced_map.get(s.product_id.id, 0.0) > 0)
            scrap_terminados = sum(s.scrap_qty or 0.0 for s in terminados)
            trend.append({
                'ym':   '%04d-%02d' % (cur.year, cur.month),
                'qty':  round(scrap_terminados, 2),
                'ops':  len(terminados),
                'tasa': self._scrap_rate(scrap_terminados, total_produced),
            })
            cur += relativedelta(months=1)
        return {'trend': trend}
