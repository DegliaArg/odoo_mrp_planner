# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: report_management_daily.py
Modelo: report.odoo_mrp_planner.report_management_daily (AbstractModel de reporte)

Provee los valores del reporte PDF 'Resumen diario de Gerencia'. Reutiliza
_get_management_overview_data del panel a nivel empresa completa (sin el guard de
permisos y sin el filtro de depósitos del usuario, porque el PDF es institucional)
fijando la empresa reportada en el contexto. No recalcula nada que ya calcule el
panel: la tasa de servicio ajustada por faltante prolongado ya viene resuelta.

Relacionado con:
- mrp_planner_dashboard_management._get_management_overview_data: fuente de datos.
- report/mrp_management_daily_report.xml: ir.actions.report + template QWeb.
- mrp_planner_dashboard_management._send_management_report: renderiza este reporte.
"""
from odoo import models, api, fields


class ReportManagementDaily(models.AbstractModel):
    _name = 'report.odoo_mrp_planner.report_management_daily'
    _description = 'Resumen diario de Gerencia (PDF)'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        company = (self.env['res.company'].browse(data['company_id'])
                   if data.get('company_id') else self.env.company)
        overview = self.env['mrp.planner.dashboard'].with_company(company).with_context(
            allowed_company_ids=[company.id]
        )._get_management_overview_data(month=data.get('month'), force_all_warehouses=True)
        report_date = (data.get('report_date')
                       or fields.Date.to_string(fields.Date.context_today(self)))
        # Para que todo entre en una página, el template muestra las primeras TOP
        # familias y agrupa el resto en "Otras". El total de ese resto se precalcula
        # acá (evita depender de builtins como sum() dentro del QWeb).
        top = 9

        def _tail(rows, key):
            return round(sum((r.get(key) or 0.0) for r in rows[top:]), 2)

        extra = {
            'top': top,
            'demand_others': _tail(overview['demand']['rows'], 'qty'),
            'invoiced_others': _tail(overview['invoiced']['rows'], 'amount'),
            'produced_others': _tail(overview['produced']['rows'], 'qty'),
        }
        return {
            'doc_ids': docids,
            'doc_model': 'mrp.planner.dashboard',
            'docs': self.env['mrp.planner.dashboard'].browse(docids),
            'o': overview,
            'extra': extra,
            'company': company,
            'report_date': report_date,
        }
