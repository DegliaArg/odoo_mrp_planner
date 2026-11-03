# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: report_management_daily.py
Modelo: report.odoo_mrp_planner.report_management_daily (AbstractModel de reporte)

Provee los valores del reporte PDF 'Resumen diario de Gerencia'. Reutiliza
_get_management_overview_data del panel a nivel empresa (facturado por las empresas
de la config; el resto, todas las del sistema) y arma TODO ya formateado (números
es-AR, colores, íconos, barras, chips de variación) para que el template QWeb sea
puramente presentacional: un one-pager ejecutivo (no un clon del panel).

Relacionado con:
- mrp_planner_dashboard_management._get_management_overview_data: fuente de datos.
- report/mrp_management_daily_report.xml: ir.actions.report + template QWeb.
- mrp_planner_dashboard_management._send_management_report: renderiza este reporte.
"""
from odoo import models, api, fields

_MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
          'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


class ReportManagementDaily(models.AbstractModel):
    _name = 'report.odoo_mrp_planner.report_management_daily'
    _description = 'Resumen diario de Gerencia (PDF)'

    # ── Helpers de formato (estilo es-AR: miles con punto) ───────────────────

    @staticmethod
    def _int(v):
        return '{:,.0f}'.format(v or 0.0).replace(',', '.')

    def _money(self, v, cur):
        return '%s %s' % (cur, self._int(v))

    def _pct(self, v):
        if v is None:
            return '—'
        return ('%.1f' % v).replace('.', ',') + '%'

    def _delta(self, d, cur=None):
        """Chip de aporte del día. None si no hay aporte hoy (evita el ruido de '+0').
        dir up/down/flat compara hoy vs ayer."""
        if not d:
            return None
        today = d.get('today') or 0.0
        if abs(today) < 1e-9:
            return None
        yest = d.get('yesterday') or 0.0
        direction = 'up' if today > yest else ('down' if today < yest else 'flat')
        txt = (self._money(abs(today), cur) if cur else self._int(abs(today)))
        return {'text': ('+' if today >= 0 else '−') + txt, 'dir': direction}

    def _rows(self, rows, key, cur=None, top=10):
        """Filas formateadas (name, value, bar%) + total de 'otras'."""
        shown = rows[:top]
        maxv = max([(r.get(key) or 0.0) for r in shown] or [0.0]) or 1.0
        out = []
        for r in shown:
            v = r.get(key) or 0.0
            out.append({
                'name': r.get('name') or '(sin familia)',
                'value': (self._money(v, cur) if cur else self._int(v)),
                'bar': max(4.0, round(v / maxv * 100.0, 1)),
            })
        others = None
        tail = rows[top:]
        if tail:
            s = sum((r.get(key) or 0.0) for r in tail)
            others = (self._money(s, cur) if cur else self._int(s))
        return out, others

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        company_ids = data.get('company_ids') or (
            [data['company_id']] if data.get('company_id') else [])
        companies = (self.env['res.company'].browse(company_ids)
                     if company_ids else self.env.company)
        primary_co = companies[:1] or self.env.company
        ov = self.env['mrp.planner.dashboard'].with_company(primary_co).with_context(
            allowed_company_ids=companies.ids
        )._get_management_overview_data(month=data.get('month'), force_all_warehouses=True,
                                        invoice_companies=companies)

        cur = ov['currency']
        daily = ov.get('daily') or {}
        is_cur = ov.get('is_current')

        def dly(key):
            return daily.get(key) if is_cur else None

        # ── KPIs destacados (3 grandes + tasa de servicio) ────────────────────
        primary = [
            {'icon': 'fa-shopping-basket', 'color': '#2563eb', 'light': '#dbeafe',
             'label': 'Demanda del mes',
             'value': self._int(ov['demand']['total_qty']), 'unit': 'piezas',
             'delta': self._delta(dly('demand'))},
            {'icon': 'fa-dollar', 'color': '#16a34a', 'light': '#dcfce7',
             'label': 'Facturado del mes',
             'value': self._money(ov['invoiced']['total_amount'], cur), 'unit': '',
             'delta': self._delta(dly('invoiced_amount'), cur)},
            {'icon': 'fa-industry', 'color': '#7c3aed', 'light': '#ede9fe',
             'label': 'Producido del mes',
             'value': self._int(ov['produced']['total_qty']), 'unit': 'piezas',
             'delta': self._delta(dly('produced'))},
        ]

        svc = ov['service']
        rate = svc['rate']
        if rate is None:
            svc_color, svc_light = '#64748b', '#f1f5f9'
        elif rate >= (ov['rate_green_pct'] or 80):
            svc_color, svc_light = '#16a34a', '#dcfce7'
        elif rate >= (ov['rate_warn_pct'] or 60):
            svc_color, svc_light = '#d97706', '#fef3c7'
        else:
            svc_color, svc_light = '#dc2626', '#fee2e2'
        service_card = {
            'icon': 'fa-check-circle', 'color': svc_color, 'light': svc_light,
            'label': 'Tasa de servicio',
            'value': self._pct(rate),
            'sub': self._int(svc['delivered']) + ' / ' + self._int(svc['ordered']) + ' pz',
            'extra': '%s de %s pedidos trabajados' % (svc.get('worked_orders', 0),
                                                      svc.get('total_orders', 0)),
        }

        # ── KPIs secundarios (tira compacta) ──────────────────────────────────
        secondary = [
            {'icon': 'fa-file-text-o', 'color': '#0ea5e9', 'label': 'Facturado (pz)',
             'value': self._int(ov['invoiced']['total_qty']) + ' pz'},
            {'icon': 'fa-truck', 'color': '#ea580c', 'label': 'Despachos',
             'value': self._int(ov['dispatch']['qty']) + ' pz'},
            {'icon': 'fa-archive', 'color': '#0891b2', 'label': 'Embalajes',
             'value': self._int(ov['packing']['qty']) + ' pz'},
            {'icon': 'fa-hand-paper-o', 'color': '#0d9488', 'label': 'Picking',
             'value': self._int(ov['picking']['qty']) + ' pz'},
        ]

        # ── Secciones por familia (con barras de proporción) ──────────────────
        dem_rows, dem_others = self._rows(ov['demand']['rows'], 'qty')
        inv_rows, inv_others = self._rows(ov['invoiced']['rows'], 'amount', cur)
        prod_rows, prod_others = self._rows(ov['produced']['rows'], 'qty')
        sections = [
            {'title': 'Demanda por familia', 'icon': 'fa-shopping-basket',
             'color': '#2563eb', 'light': '#eff4ff', 'bar': '#bfd4fe',
             'rows': dem_rows, 'others': dem_others,
             'total': self._int(ov['demand']['total_qty']) + ' pz'},
            {'title': 'Facturado por familia', 'icon': 'fa-dollar',
             'color': '#16a34a', 'light': '#effaf1', 'bar': '#bbe9c6',
             'rows': inv_rows, 'others': inv_others,
             'total': self._money(ov['invoiced']['total_amount'], cur)},
            {'title': 'Producido por familia', 'icon': 'fa-industry',
             'color': '#7c3aed', 'light': '#f5f1ff', 'bar': '#d6c8fb',
             'rows': prod_rows, 'others': prod_others,
             'total': self._int(ov['produced']['total_qty']) + ' pz'},
        ]

        y, m = int(ov['month'][:4]), int(ov['month'][5:7])
        rep = {
            'company_label': ', '.join(companies.mapped('name')),
            'month_label': '%s %s' % (_MESES[m], y),
            'report_date': (data.get('report_date')
                            or fields.Date.to_string(fields.Date.context_today(self))),
            'is_current': is_cur,
            'primary': primary,
            'service_card': service_card,
            'secondary': secondary,
            'sections': sections,
            'svc_note': ('La tasa de servicio cuenta SOLO los pedidos trabajados en el '
                         'mes (con al menos una entrega en el mes). Distinta de la Tasa '
                         'de cumplimiento de Ventas, que considera toda la demanda.'),
        }
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.planner.dashboard',
            'docs': self.env['mrp.planner.dashboard'].browse(docids),
            'rep': rep,
        }
