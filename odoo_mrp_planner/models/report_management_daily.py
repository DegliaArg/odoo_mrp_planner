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

    @staticmethod
    def _leaf(name):
        """Nombre de familia sin el prefijo de la categoría padre (el encabezado de
        la tabla ya dice 'Pieza final'/'Semiprocesado'): acorta y evita el wrap.
        'Pieza final / Bujes de barra estabilizadora' → 'Bujes de barra estabilizadora'."""
        return (name or '').rsplit(' / ', 1)[-1].strip() or (name or '')

    def _money(self, v, cur):
        return '%s %s' % (cur, self._int(v))

    def _pct(self, v):
        if v is None:
            return '—'
        return ('%.1f' % v).replace('.', ',') + '%'

    def _delta(self, d, cur=None):
        """Mini-leyenda del aporte del día, con el MISMO formato que el panel de
        Gerencia: 'Hoy: {hoy} {flecha}{+/−dif} vs ayer', donde dif = hoy − ayer
        (lineal). Verde si hoy > ayer, rojo si hoy < ayer, sin flecha si igual.
        ``cur`` formatea hoy y la diferencia en moneda."""
        if not d:
            return None
        today = d.get('today') or 0.0
        yest = d.get('yesterday') or 0.0
        diff = today - yest
        fmt = (lambda v: self._money(v, cur)) if cur else (lambda v: self._int(v))
        return {
            'today': fmt(today),
            'diff': ('+' if diff >= 0 else '−') + fmt(abs(diff)),
            'dir': 'up' if diff > 0 else ('down' if diff < 0 else 'flat'),
        }

    @staticmethod
    def _bar_pct(raw, mx):
        """Ancho % de la barra proporcional, relativa al máximo de la tabla.
        Piso de 2% para que las familias chicas muestren una marca mínima."""
        if not mx or raw <= 0:
            return 0
        return max(2, min(100, int(round(raw / mx * 100.0))))

    def _fam_rows(self, rows, key, cur=None, top=11):
        """Filas (name, value, bar) por familia + total de 'otras'. La barra es
        proporcional al máximo de las filas mostradas."""
        shown = rows[:top]
        mx = max((r.get(key) or 0.0) for r in shown) if shown else 0.0
        out = [{'name': self._leaf(r.get('name')) or '(sin familia)',
                'value': (self._money(r.get(key) or 0.0, cur) if cur
                          else self._int(r.get(key) or 0.0)),
                'bar': self._bar_pct(r.get(key) or 0.0, mx)}
               for r in shown]
        others = None
        tail = rows[top:]
        if tail:
            s = sum((r.get(key) or 0.0) for r in tail)
            others = (self._money(s, cur) if cur else self._int(s))
        return out, others

    def _inv_rows(self, rows, cur, top=11):
        """Filas de facturado (name, qty, amount, bar); la barra es proporcional
        al monto facturado de cada familia."""
        shown = rows[:top]
        mx = max((r.get('amount') or 0.0) for r in shown) if shown else 0.0
        out = [{'name': self._leaf(r.get('name')) or '(sin familia)',
                'qty': self._int(r.get('qty') or 0.0),
                'amount': self._money(r.get('amount') or 0.0, cur),
                'bar': self._bar_pct(r.get('amount') or 0.0, mx)}
               for r in shown]
        others = None
        tail = rows[top:]
        if tail:
            others = {'qty': self._int(sum((r.get('qty') or 0.0) for r in tail)),
                      'amount': self._money(sum((r.get('amount') or 0.0) for r in tail), cur)}
        return out, others

    def _mov_section(self, title, block, now=False):
        """Sección de movimiento (despachos/embalajes/picking) por categoría de
        venta, con barras proporcionales. ``now`` marca las fotos del momento
        (embalajes/picking) para pintarles el chip "Ahora"."""
        if not block.get('configured'):
            return {'title': title, 'configured': False, 'rows': [], 'total': '0', 'now': now}
        src = block.get('rows', [])
        mx = max((r.get('qty') or 0.0) for r in src) if src else 0.0
        rows = [{'name': r.get('name') or '—',
                 'value': self._int(r.get('qty') or 0.0),
                 'bar': self._bar_pct(r.get('qty') or 0.0, mx)}
                for r in src]
        return {'title': title, 'configured': True, 'rows': rows,
                'total': self._int(block.get('qty') or 0.0), 'now': now}

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

        # ── Semáforo de la tasa de scrap (acá "más alto = peor") ─────────────
        scr = ov.get('scrap') or {}
        scrap_rate = scr.get('rate')
        if scrap_rate is None:
            scrap_color = '#64748b'
        elif scrap_rate >= 10:
            scrap_color = '#c0392b'
        elif scrap_rate >= 3:
            scrap_color = '#b45309'
        else:
            scrap_color = '#1e7e34'

        # ── KPIs (orden y etiquetas del one-pager; ancho relativo por card) ───
        navy = '#004b88'
        kpis = [
            {'label': 'Demanda (pz)', 'value': self._int(ov['demand']['total_qty']),
             'accent': navy, 'delta': self._delta(dly('demand')), 'subs': [], 'width': 12},
            {'label': 'Producido (pz)', 'value': self._int(ov['produced']['total_qty']),
             'accent': navy, 'delta': self._delta(dly('produced')), 'subs': [], 'width': 12},
            {'label': 'Facturado (pz)', 'value': self._int(ov['invoiced']['total_qty']),
             'accent': navy, 'delta': self._delta(dly('invoiced_qty')), 'subs': [], 'width': 12},
            {'label': 'Facturado ($)', 'value': self._money(ov['invoiced']['total_amount'], cur),
             'accent': navy, 'delta': self._delta(dly('invoiced_amount'), cur), 'subs': [], 'width': 22},
            {'label': 'Despachos (pz)', 'value': self._int(ov['dispatch']['qty']),
             'accent': navy, 'delta': self._delta(dly('dispatch')), 'width': 14,
             'subs': ['%s transferencias' % self._int(ov['dispatch'].get('pickings') or 0)]},
            {'label': 'Tasa de servicio', 'value': self._pct(rate), 'accent': svc_color,
             'delta': None, 'width': 14,
             'subs': ['%s/%s pz' % (self._int(svc['delivered']), self._int(svc['ordered'])),
                      '%s de %s ped. trabajados' % (
                          svc.get('worked_orders', 0), svc.get('total_orders', 0))]},
            {'label': 'Tasa de scrap',
             'value': ('s/prod' if scrap_rate is None else self._pct(scrap_rate)),
             'accent': scrap_color, 'delta': None, 'width': 14,
             'subs': ['%s pz desechadas' % self._int(scr.get('qty') or 0.0)]},
        ]

        # ── Desglose por familia: Demanda + Producido en par (50/50) ──────────
        dem_rows, dem_others = self._fam_rows(ov['demand']['rows'], 'qty')
        prod_rows, prod_others = self._fam_rows(ov['produced']['rows'], 'qty')
        inv_rows, inv_others = self._inv_rows(ov['invoiced']['rows'], cur)
        fam_pair = [
            {'title': 'Demanda por familia', 'col1': 'Pieza final',
             'total': self._int(ov['demand']['total_qty']),
             'rows': dem_rows, 'others': dem_others},
            {'title': 'Producido por familia', 'col1': 'Semiprocesado',
             'total': self._int(ov['produced']['total_qty']),
             'rows': prod_rows, 'others': prod_others},
        ]
        # Facturado por familia: a todo el ancho, con piezas + monto.
        fam_invoice = {
            'title': 'Facturado por familia', 'col1': 'Pieza final',
            'total_pz': self._int(ov['invoiced']['total_qty']),
            'total_amount': self._money(ov['invoiced']['total_amount'], cur),
            'rows': inv_rows, 'others': inv_others,
        }

        # ── Movimientos por categoría de venta (Despachos/Embalajes/Picking) ──
        movements = [
            self._mov_section('Despachos', ov['dispatch']),
            self._mov_section('Embalajes', ov['packing'], now=True),
            self._mov_section('Pickings', ov['picking'], now=True),
        ]

        # ── Membrete (caja de marca) y pie corporativo ────────────────────────
        co = primary_co
        brand_logo = None
        if co.logo:
            logo = co.logo.decode() if isinstance(co.logo, bytes) else co.logo
            brand_logo = 'data:image/png;base64,%s' % logo
        locality = ' '.join(x for x in [co.city, co.state_id.name, co.zip] if x)
        line2 = ', '.join(p for p in [co.street, co.street2, locality or None,
                                      co.country_id.name] if p)
        footer = ' · '.join(p for p in [co.name, line2, co.email, co.vat] if p)

        y, m = int(ov['month'][:4]), int(ov['month'][5:7])
        rep = {
            'company_label': ', '.join(companies.mapped('name')),
            'company_name': co.name,
            'brand_logo': brand_logo,
            'footer': footer,
            'month_label': '%s %s' % (_MESES[m], y),
            'report_date': (data.get('report_date')
                            or fields.Date.to_string(fields.Date.context_today(self))),
            'is_current': is_cur,
            'kpis': kpis,
            'fam_pair': fam_pair,
            'fam_invoice': fam_invoice,
            'movements': movements,
        }
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.planner.dashboard',
            'docs': self.env['mrp.planner.dashboard'].browse(docids),
            'company': co,
            'rep': rep,
        }
