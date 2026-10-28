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

        Unificación de sucursales: con "Unificar clientes por CUIT" activo en
        Ajustes, el panel muestra el cliente UNIFICADO (casa matriz + todas sus
        sucursales/razones sociales del mismo CUIT), igual que el Análisis de
        clientes. Para lograrlo se reconstruye el grupo de contactos que comparten
        el CUIT del contacto de la oportunidad y se pasa como ``partner_ids`` a
        los métodos base, que ya saben fusionar y subir el nombre a la matriz.
        """
        if not partner_id:
            return {'row': None, 'detail': {}, 'config': {}}
        partner_id = int(partner_id)
        override = amount_method if amount_method in ('pxq', 'real') else None

        # Con unificación por CUIT activa, el cálculo se acota al GRUPO de
        # sucursales (no solo al contacto), para que la fusión de la fila se dé
        # igual que en el análisis. Sin unificación, al contacto puntual.
        try:
            unify = bool(self._ca_config().get('unify_by_vat'))
        except Exception:
            unify = False
        group_ids = self._ca_unify_group_ids(partner_id) if unify else [partner_id]

        # partner_ids acota el cálculo pesado a este grupo (rápido); el ABC que
        # devuelve ya es el poblacional real (se recalcula aparte en el método).
        data = self.get_customer_analysis_data(
            date_from, date_to, None,
            amount_method_override=override, partner_ids=group_ids)
        if not isinstance(data, dict):
            data = {}
        rows = data.get('rows', []) or []
        row = next(
            (r for r in rows
             if r.get('partner_id') == partner_id
             or partner_id in (r.get('partner_ids') or [])),
            None,
        )

        # Detalle sobre el grupo completo y con el contacto REPRESENTATIVO (la
        # casa matriz que eligió la fusión), para que el título y los agregados
        # del panel reflejen al cliente unificado y no a la sucursal puntual.
        detail_pid = row.get('partner_id') if row else partner_id
        detail_group = (row.get('partner_ids') if row else None) or group_ids
        detail = self.get_customer_detail(
            detail_pid, date_from, date_to,
            partner_ids=detail_group, amount_method_override=override)

        return {
            'row': row,
            'detail': detail or {},
            'config': data.get('config', {}) or {},
        }
