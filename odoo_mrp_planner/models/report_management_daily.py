# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: report_management_daily.py
Modelo: report.odoo_mrp_planner.report_management_daily (AbstractModel de reporte)

Provee los valores del reporte PDF 'Resumen diario de Gerencia'. Reutiliza
_get_management_overview_data del panel a nivel empresa completa (sin el guard de
permisos y sin el filtro de depósitos del usuario, porque el PDF es institucional)
fijando las empresas reportadas en el contexto.

Acá se arma todo YA FORMATEADO (números estilo es-AR, colores, íconos, barras de
proporción) para que el template QWeb sea puramente presentacional y replique la
estética del panel de Gerencia (tarjetas de KPI + tablas por familia con barras).

Relacionado con:
- mrp_planner_dashboard_management._get_management_overview_data: fuente de datos.
- report/mrp_management_daily_report.xml: ir.actions.report + template QWeb.
- mrp_planner_dashboard_management._send_management_report: renderiza este reporte.
"""
from odoo import models, api, fields


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
        """Aporte del día + dirección vs ayer. money=True si se pasa cur."""
        if not d:
            return None
        today = d.get('today') or 0.0
        yest = d.get('yesterday') or 0.0
        direction = 'up' if today > yest else ('down' if today < yest else 'flat')
        txt = (self._money(abs(today), cur) if cur else self._int(abs(today)))
        return {'text': ('+' if today >= 0 else '−') + txt, 'dir': direction}

    def _rows(self, rows, key, cur=None, top=9):
        """Filas formateadas (name, value, bar%) + fila 'otras' + total agregado."""
        shown = rows[:top]
        maxv = max([(r.get(key) or 0.0) for r in shown] or [0.0]) or 1.0
        out = []
        for r in shown:
            v = r.get(key) or 0.0
            out.append({
                'name': r.get('name') or '(sin familia)',
                'value': (self._money(v, cur) if cur else self._int(v)),
                'bar': max(3.0, round(v / maxv * 100.0, 1)),
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
        # Empresas a consolidar: company_ids (lista) o, por compatibilidad, un
        # company_id suelto; si no viene nada, la empresa activa.
        company_ids = data.get('company_ids') or (
            [data['company_id']] if data.get('company_id') else [])
        companies = (self.env['res.company'].browse(company_ids)
                     if company_ids else self.env.company)
        primary = companies[:1] or self.env.company
        ov = self.env['mrp.planner.dashboard'].with_company(primary).with_context(
            allowed_company_ids=companies.ids
        )._get_management_overview_data(month=data.get('month'), force_all_warehouses=True)

        cur = ov['currency']
        daily = ov.get('daily') or {}
        is_cur = ov.get('is_current')

        def dly(key):
            return daily.get(key) if is_cur else None

        # ── Tarjetas de KPI (mismos íconos/colores que el panel) ──────────────
        kpis = [
            {'icon': 'fa-shopping-basket', 'color': '#2563eb', 'label': 'Demanda',
             'value': self._int(ov['demand']['total_qty']) + ' pz',
             'delta': self._delta(dly('demand'))},
            {'icon': 'fa-dollar', 'color': '#16a34a', 'label': 'Facturado',
             'value': self._money(ov['invoiced']['total_amount'], cur),
             'delta': self._delta(dly('invoiced_amount'), cur)},
            {'icon': 'fa-file-text-o', 'color': '#64748b', 'label': 'Facturado (pz)',
             'value': self._int(ov['invoiced']['total_qty']) + ' pz',
             'delta': self._delta(dly('invoiced_qty'))},
            {'icon': 'fa-industry', 'color': '#7c3aed', 'label': 'Producido',
             'value': self._int(ov['produced']['total_qty']) + ' pz',
             'delta': self._delta(dly('produced'))},
            {'icon': 'fa-truck', 'color': '#ea580c', 'label': 'Despachos',
             'value': self._int(ov['dispatch']['qty']) + ' pz',
             'delta': self._delta(dly('dispatch'))},
            {'icon': 'fa-archive', 'color': '#0891b2', 'label': 'Embalajes',
             'value': self._int(ov['packing']['qty']) + ' pz', 'delta': None},
            {'icon': 'fa-hand-paper-o', 'color': '#0d9488', 'label': 'Picking',
             'value': self._int(ov['picking']['qty']) + ' pz', 'delta': None},
        ]

        # Tarjeta de tasa de servicio con color de semáforo.
        svc = ov['service']
        rate = svc['rate']
        if rate is None:
            svc_color = '#94a3b8'
        elif rate >= (ov['rate_green_pct'] or 80):
            svc_color = '#16a34a'
        elif rate >= (ov['rate_warn_pct'] or 60):
            svc_color = '#d97706'
        else:
            svc_color = '#dc2626'
        service_card = {
            'icon': 'fa-check-circle', 'color': svc_color, 'label': 'Tasa de servicio',
            'value': self._pct(rate),
            'sub': self._int(svc['delivered']) + ' / ' + self._int(svc['ordered']) + ' pz',
        }

        # ── Secciones por familia (con barras de proporción) ──────────────────
        dem_rows, dem_others = self._rows(ov['demand']['rows'], 'qty')
        inv_rows, inv_others = self._rows(ov['invoiced']['rows'], 'amount', cur)
        prod_rows, prod_others = self._rows(ov['produced']['rows'], 'qty')
        sections = [
            {'title': 'Demanda por familia', 'icon': 'fa-shopping-basket',
             'color': '#2563eb', 'light': '#dbeafe',
             'rows': dem_rows, 'others': dem_others,
             'total': self._int(ov['demand']['total_qty']) + ' pz'},
            {'title': 'Facturado por familia', 'icon': 'fa-dollar',
             'color': '#16a34a', 'light': '#dcfce7',
             'rows': inv_rows, 'others': inv_others,
             'total': self._money(ov['invoiced']['total_amount'], cur)},
            {'title': 'Producido por familia', 'icon': 'fa-industry',
             'color': '#7c3aed', 'light': '#ede9fe',
             'rows': prod_rows, 'others': prod_others,
             'total': self._int(ov['produced']['total_qty']) + ' pz'},
        ]

        # Nota de la tasa de servicio.
        if svc.get('excused'):
            svc_note = (
                'Tasa de servicio = entregado ÷ demanda del mes. Se descontaron %s pz '
                'de demanda de pedidos pendientes sin stock para pickear hace más de %s '
                'días (demanda bruta %s pz).' % (
                    self._int(svc['excused']), svc.get('excuse_days'),
                    self._int(svc['ordered_gross'])))
        else:
            svc_note = ('Tasa de servicio = entregado ÷ demanda del mes. '
                        'Sin demanda excusada por faltante prolongado este mes.')

        rep = {
            'company_label': ', '.join(companies.mapped('name')),
            'month': ov['month'],
            'report_date': (data.get('report_date')
                            or fields.Date.to_string(fields.Date.context_today(self))),
            'is_current': is_cur,
            'kpis': kpis,
            'service_card': service_card,
            'sections': sections,
            'svc_note': svc_note,
        }
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.planner.dashboard',
            'docs': self.env['mrp.planner.dashboard'].browse(docids),
            'rep': rep,
        }
