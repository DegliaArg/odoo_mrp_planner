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

    def _fam_rows(self, rows, key, cur=None, top=11):
        """Filas (name, value) por familia + total de 'otras'."""
        shown = rows[:top]
        out = [{'name': r.get('name') or '(sin familia)',
                'value': (self._money(r.get(key) or 0.0, cur) if cur
                          else self._int(r.get(key) or 0.0))}
               for r in shown]
        others = None
        tail = rows[top:]
        if tail:
            s = sum((r.get(key) or 0.0) for r in tail)
            others = (self._money(s, cur) if cur else self._int(s))
        return out, others

    def _mov_section(self, title, block):
        """Sección de movimiento (despachos/embalajes/picking) por categoría de venta."""
        if not block.get('configured'):
            return {'title': title, 'configured': False, 'rows': [], 'total': '—'}
        rows = [{'name': r.get('name') or '—', 'value': self._int(r.get('qty') or 0.0)}
                for r in block.get('rows', [])]
        return {'title': title, 'configured': True, 'rows': rows,
                'total': self._int(block.get('qty') or 0.0) + ' pz'}

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

        # ── Semáforo de la tasa de servicio ──────────────────────────────────
        svc = ov['service']
        rate = svc['rate']
        if rate is None:
            svc_color = '#64748b'
        elif rate >= (ov['rate_green_pct'] or 80):
            svc_color = '#1e7e34'
        elif rate >= (ov['rate_warn_pct'] or 60):
            svc_color = '#b45309'
        else:
            svc_color = '#c0392b'

        # ── KPIs (misma selección que el panel) ───────────────────────────────
        navy = '#004b88'
        kpis = [
            {'label': 'Demanda del mes', 'value': self._int(ov['demand']['total_qty']) + ' pz',
             'accent': navy, 'delta': self._delta(dly('demand')), 'sub': None},
            {'label': 'Producido del mes', 'value': self._int(ov['produced']['total_qty']) + ' pz',
             'accent': navy, 'delta': self._delta(dly('produced')), 'sub': None},
            {'label': 'Facturado del mes', 'value': self._money(ov['invoiced']['total_amount'], cur),
             'accent': navy, 'delta': self._delta(dly('invoiced_amount'), cur), 'sub': None},
            {'label': 'Facturado (piezas)', 'value': self._int(ov['invoiced']['total_qty']) + ' pz',
             'accent': navy, 'delta': self._delta(dly('invoiced_qty')), 'sub': None},
            {'label': 'Despachos del mes', 'value': self._int(ov['dispatch']['qty']) + ' pz',
             'accent': navy, 'delta': self._delta(dly('dispatch')), 'sub': None},
            {'label': 'Tasa de servicio', 'value': self._pct(rate), 'accent': svc_color,
             'delta': None,
             'sub': '%s/%s pz · %s de %s ped.' % (
                 self._int(svc['delivered']), self._int(svc['ordered']),
                 svc.get('worked_orders', 0), svc.get('total_orders', 0))},
        ]

        # ── Desglose por familia ──────────────────────────────────────────────
        dem_rows, dem_others = self._fam_rows(ov['demand']['rows'], 'qty')
        prod_rows, prod_others = self._fam_rows(ov['produced']['rows'], 'qty')
        inv_rows, inv_others = self._fam_rows(ov['invoiced']['rows'], 'amount', cur)
        families = [
            {'title': 'Demanda por familia', 'rows': dem_rows, 'others': dem_others,
             'total': self._int(ov['demand']['total_qty']) + ' pz'},
            {'title': 'Producido por familia', 'rows': prod_rows, 'others': prod_others,
             'total': self._int(ov['produced']['total_qty']) + ' pz'},
            {'title': 'Facturado por familia', 'rows': inv_rows, 'others': inv_others,
             'total': self._money(ov['invoiced']['total_amount'], cur)},
        ]

        # ── Movimientos por categoría de venta (Despachos/Embalajes/Picking) ──
        movements = [
            self._mov_section('Despachos', ov['dispatch']),
            self._mov_section('Embalajes', ov['packing']),
            self._mov_section('Picking', ov['picking']),
        ]

        y, m = int(ov['month'][:4]), int(ov['month'][5:7])
        rep = {
            'company_label': ', '.join(companies.mapped('name')),
            'month_label': '%s %s' % (_MESES[m], y),
            'report_date': (data.get('report_date')
                            or fields.Date.to_string(fields.Date.context_today(self))),
            'is_current': is_cur,
            'kpis': kpis,
            'families': families,
            'movements': movements,
            'svc_note': ('La tasa de servicio cuenta SOLO los pedidos trabajados en el '
                         'mes (con al menos una entrega en el mes). Distinta de la Tasa '
                         'de cumplimiento de Ventas, que considera toda la demanda.'),
        }
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.planner.dashboard',
            'docs': self.env['mrp.planner.dashboard'].browse(docids),
            'company': primary_co,   # membrete (web.external_layout)
            'rep': rep,
        }
