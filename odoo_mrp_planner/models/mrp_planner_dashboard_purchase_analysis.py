# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_purchase_analysis.py
Modelo: extensión de mrp.planner.dashboard

Análisis de compras productivas: seguimiento semanal de las OFs del sector
vulcanizado (o cualquier sector seleccionado via tag de CT) y las OCs que
cuelgan de ellas a cualquier profundidad de la cadena MTO.

Para cada OF del sector se recorre el árbol de moves (move_raw_ids →
move_orig_ids) en BFS hasta encontrar purchase.order.line en las hojas.
Las OFs intermedias se ignoran en la vista; solo se exponen las OCs.

Agrupación por semana ISO del date_start de la OT del sector seleccionado
que pertenece a cada OF (la más temprana si hay varias).
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import models, api, fields, _

_logger = logging.getLogger(__name__)

_PO_STATE_LABEL = {
    'draft':    'Borrador',
    'sent':     'Enviada',
    'purchase': 'OC',
    'done':     'Bloqueada',
    'cancel':   'Cancelada',
}
_MO_STATE_LABEL = {
    'draft':     'Borrador',
    'confirmed': 'Confirmada',
    'progress':  'En curso',
    'to_close':  'Por cerrar',
    'done':      'Terminada',
    'cancel':    'Cancelada',
}


class MrpPlannerDashboardPurchaseAnalysis(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Apertura de la vista ──────────────────────────────────────────────────

    @api.model
    def action_open_purchase_analysis(self):
        """Abre el panel de Análisis de compras (vista form sin barra de control)."""
        self._ensure_planner_group('odoo_mrp_planner.group_purchase',
                                   'odoo_mrp_planner.group_purchase_admin')
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Análisis de compras'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'domain': [('id', '=', rec.id)],
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_purchase_analysis_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_purchase_analysis(self):
        """Botón Actualizar: reabre la vista con un registro nuevo."""
        return self.action_open_purchase_analysis()

    # ── Datos para el widget ──────────────────────────────────────────────────

    @api.model
    def get_purchase_analysis(self, tag_ids, date_from, date_to):
        """
        Devuelve OFs del sector (tag_ids) con OT en el rango de fechas,
        agrupadas por semana ISO, con todas las OCs descendientes a cualquier
        profundidad de la cadena MTO.

        :param tag_ids: list[int] — IDs de mrp.workcenter.tag (sector).
        :param date_from: str 'YYYY-MM-DD' — inicio del rango.
        :param date_to:   str 'YYYY-MM-DD' — fin del rango.
        :returns: dict con 'weeks' (lista de semanas con OFs y OCs).
        """
        self._ensure_planner_group('odoo_mrp_planner.group_purchase',
                                   'odoo_mrp_planner.group_purchase_admin')

        if not tag_ids:
            return {'weeks': [], 'total_mos': 0, 'total_pos': 0}

        date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
        date_to_dt   = datetime.strptime(date_to,   '%Y-%m-%d').replace(
            hour=23, minute=59, second=59)

        # 1. OTs del sector en el rango
        wo_domain = [
            ('workcenter_id.tag_ids', 'in', list(tag_ids)),
            ('date_start', '>=', fields.Datetime.to_string(date_from_dt)),
            ('date_start', '<=', fields.Datetime.to_string(date_to_dt)),
            ('state', 'not in', ['cancel']),
            ('production_id.state', 'not in', ['cancel', 'draft']),
        ]
        workorders = self.env['mrp.workorder'].search(wo_domain, order='date_start asc')

        # Mapa mo_id → date_start más temprana de sus OTs en el sector
        mo_earliest = {}
        for wo in workorders:
            mo_id = wo.production_id.id
            if not mo_id:
                continue
            if mo_id not in mo_earliest or (wo.date_start and wo.date_start < mo_earliest[mo_id]):
                mo_earliest[mo_id] = wo.date_start

        if not mo_earliest:
            return {'weeks': [], 'total_mos': 0, 'total_pos': 0}

        mos = self.env['mrp.production'].browse(list(mo_earliest.keys()))

        # 2. Para cada OF raíz, recolectar OCs descendientes (BFS)
        today = fields.Date.today()
        mo_po_lines = {}
        for mo in mos:
            mo_po_lines[mo.id] = self._pca_collect_po_lines(mo)

        # 3. Agrupar por semana ISO
        weeks_data = defaultdict(list)
        for mo in mos:
            dt = mo_earliest.get(mo.id)
            if not dt:
                continue
            if isinstance(dt, str):
                dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
            iso = dt.isocalendar()
            week_key = (iso[0], int(iso[1]))

            po_lines = mo_po_lines.get(mo.id, self.env['purchase.order.line'])
            pos_data = self._pca_format_po_lines(po_lines, today)

            weeks_data[week_key].append({
                'mo_id':          mo.id,
                'mo_name':        mo.name or '',
                'product_id':     mo.product_id.id,
                'product_name':   mo.product_id.display_name or '',
                'qty':            mo.product_qty or 0.0,
                'qty_produced':   mo.qty_produced or 0.0,
                'uom':            mo.product_uom_id.name or '',
                'state':          mo.state,
                'state_label':    _MO_STATE_LABEL.get(mo.state, mo.state),
                'wo_date':        dt.strftime('%d/%m/%Y %H:%M'),
                'pos':            pos_data,
                'pos_count':      len(pos_data),
                'has_late_pos':   any(p['is_late'] for p in pos_data),
                'has_pending_pos': any(p['state'] in ('draft', 'sent') for p in pos_data),
            })

        # 4. Construir lista de semanas ordenadas
        weeks = []
        total_pos = 0
        for (year, week) in sorted(weeks_data.keys()):
            monday = datetime.fromisocalendar(year, week, 1).date()
            sunday = datetime.fromisocalendar(year, week, 7).date()
            week_mos = weeks_data[(year, week)]
            week_pos = sum(m['pos_count'] for m in week_mos)
            total_pos += week_pos
            weeks.append({
                'week_label': f'W{week:02d}',
                'year':       year,
                'date_from':  str(monday),
                'date_to':    str(sunday),
                'mos':        week_mos,
                'mo_count':   len(week_mos),
                'po_count':   week_pos,
            })

        return {
            'weeks':      weeks,
            'total_mos':  len(mos),
            'total_pos':  total_pos,
        }

    # ── Helpers privados ──────────────────────────────────────────────────────

    def _pca_collect_po_lines(self, root_mo):
        """BFS desde root_mo recorriendo la cadena de moves para encontrar
        todas las purchase.order.line descendientes a cualquier profundidad.

        Sigue: move_raw_ids → move_orig_ids → purchase_line_id (hoja)
                                             → production_id (nodo intermedio)
        """
        visited = set()
        queue   = [root_mo]
        line_ids = set()

        while queue:
            batch = queue
            queue = []
            for mo in batch:
                if mo.id in visited:
                    continue
                visited.add(mo.id)
                for raw_move in mo.move_raw_ids:
                    for supply_move in raw_move.move_orig_ids:
                        if supply_move.purchase_line_id:
                            line_ids.add(supply_move.purchase_line_id.id)
                        # Nodo intermedio: OF hija que produce este componente
                        child_mo = supply_move.production_id
                        if child_mo and child_mo.id not in visited:
                            queue.append(child_mo)

        if not line_ids:
            return self.env['purchase.order.line']
        return self.env['purchase.order.line'].browse(list(line_ids))

    def _pca_format_po_lines(self, po_lines, today):
        """Convierte un recordset de purchase.order.line en una lista de dicts
        para el frontend, ordenada por fecha planificada (nulls al final)."""
        rows = []
        for line in po_lines:
            po = line.order_id
            date_planned = line.date_planned
            if date_planned and hasattr(date_planned, 'date'):
                date_planned_d = date_planned.date()
            elif date_planned:
                date_planned_d = date_planned
            else:
                date_planned_d = None

            qty_ordered  = line.product_qty or 0.0
            qty_received = line.qty_received or 0.0
            pct_received = round(qty_received / qty_ordered * 100, 1) if qty_ordered > 0 else 0.0

            is_late = (
                po.state in ('purchase', 'sent', 'draft')
                and date_planned_d is not None
                and date_planned_d < today
                and qty_received < qty_ordered
            )

            rows.append({
                'po_id':          po.id,
                'po_name':        po.name or '',
                'partner':        po.partner_id.name or '',
                'product':        line.product_id.display_name or '',
                'qty_ordered':    qty_ordered,
                'qty_received':   qty_received,
                'pct_received':   pct_received,
                'date_planned':   str(date_planned_d) if date_planned_d else '',
                'state':          po.state,
                'state_label':    _PO_STATE_LABEL.get(po.state, po.state),
                'is_late':        is_late,
                'is_subcontract': bool(po.subcontract_production_ids) if hasattr(po, 'subcontract_production_ids') else False,
            })

        rows.sort(key=lambda r: (r['date_planned'] or '9999-99-99'))
        return rows
