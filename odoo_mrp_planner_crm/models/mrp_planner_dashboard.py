"""
Módulo: mrp_planner_dashboard.py (odoo_mrp_planner_crm)
Modelo: extensión de mrp.planner.dashboard

Orquestador de los indicadores del cliente para el formulario de la oportunidad
de CRM. NO recalcula nada: reúsa los métodos del Análisis de clientes del módulo
base y los combina en un único RPC.
"""
from odoo import api, models


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    @api.model
    def get_crm_customer_kpis(self, partner_id, date_from, date_to, amount_method=None):
        """Indicadores del cliente para el panel de la oportunidad.

        Combina, sin cálculos nuevos:
        - get_customer_analysis_data: devuelve la fila del cliente con TODOS los
          KPIs (ABC poblacional del período, cumplimiento, puntualidad, lead
          time, tendencia, totales, top artículo/familia…). Se recorre el
          universo para que el ABC sea el real (relativo a todos los clientes).
        - get_customer_detail: evolución mensual, mix por categoría de venta y
          familia, lista de pedidos y top de artículos.

        :param partner_id: int — cliente (campo "Contacto" de la oportunidad).
        :param date_from:  str 'YYYY-MM-DD'.
        :param date_to:    str 'YYYY-MM-DD'.
        :param amount_method: 'pxq' | 'real' | None — valorización del monto
            (override del toggle del panel). None usa el método de Ajustes.
        :returns: dict {'row': dict|None, 'detail': dict, 'config': dict}.
        """
        if not partner_id:
            return {'row': None, 'detail': {}, 'config': {}}
        partner_id = int(partner_id)
        override = amount_method if amount_method in ('pxq', 'real') else None

        # partner_ids acota el cálculo pesado a este cliente (rápido); el ABC que
        # devuelve ya es el poblacional real (se recalcula aparte en el método).
        data = self.get_customer_analysis_data(
            date_from, date_to, None,
            amount_method_override=override, partner_ids=[partner_id])
        if not isinstance(data, dict):
            data = {}
        rows = data.get('rows', []) or []
        row = next(
            (r for r in rows
             if r.get('partner_id') == partner_id
             or partner_id in (r.get('partner_ids') or [])),
            None,
        )

        detail = self.get_customer_detail(
            partner_id, date_from, date_to, amount_method_override=override)

        return {
            'row': row,
            'detail': detail or {},
            'config': data.get('config', {}) or {},
        }
