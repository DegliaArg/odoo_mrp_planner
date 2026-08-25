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
    def get_wcs_for_tags(self, tag_ids):
        """Devuelve los centros de trabajo que tienen alguno de los tags dados."""
        self._ensure_planner_group('odoo_mrp_planner.group_purchase',
                                   'odoo_mrp_planner.group_purchase_admin')
        if not tag_ids:
            return []
        wcs = self.env['mrp.workcenter'].search(
            [('tag_ids', 'in', list(tag_ids))], order='name asc')
        return [{'id': wc.id, 'name': wc.name} for wc in wcs]

    @api.model
    def get_purchase_analysis(self, tag_ids, date_from, date_to):
        """
        Devuelve estructura para tabla doble entrada CT × semana ISO.

        Filas: centros de trabajo del sector (tag_ids).
        Columnas: semanas ISO del rango de fechas.
        Celdas: lista de OTs planificadas para ese CT en esa semana,
                cada una con sus OCs descendientes (BFS por cadena MTO).

        :param tag_ids: list[int] — IDs de mrp.workcenter.tag.
        :param date_from: str 'YYYY-MM-DD'
        :param date_to:   str 'YYYY-MM-DD'
        :returns: dict con week_keys, week_labels, wc_rows, total_mos, total_pos.
        """
        self._ensure_planner_group('odoo_mrp_planner.group_purchase',
                                   'odoo_mrp_planner.group_purchase_admin')

        _EMPTY = {'week_keys': [], 'week_labels': {}, 'wc_rows': [], 'total_mos': 0, 'total_pos': 0}
        if not tag_ids:
            return _EMPTY

        date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
        date_to_dt   = datetime.strptime(date_to, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59)

        wo_domain = [
            ('workcenter_id.tag_ids', 'in', list(tag_ids)),
            ('date_start', '>=', fields.Datetime.to_string(date_from_dt)),
            ('date_start', '<=', fields.Datetime.to_string(date_to_dt)),
            ('state', 'not in', ['cancel']),
            ('production_id.state', 'not in', ['cancel', 'draft']),
        ]
        workorders = self.env['mrp.workorder'].search(wo_domain, order='date_start asc')

        if not workorders:
            return _EMPTY

        today = fields.Date.today()

        # BFS una sola vez por OF única
        mo_po_data = {}
        for mo in workorders.mapped('production_id'):
            if mo.id not in mo_po_data:
                po_lines = self._pca_collect_po_lines(mo)
                mo_po_data[mo.id] = self._pca_format_po_lines(po_lines, today)

        # Agrupar OTs por (wc_id, week_key)
        wc_cell_map = defaultdict(lambda: defaultdict(list))
        wc_names = {}
        week_info = {}

        for wo in workorders:
            dt = wo.date_start
            if not dt:
                continue
            if isinstance(dt, str):
                dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
            iso = dt.isocalendar()
            year, week = iso[0], int(iso[1])
            week_key = f'{year}-W{week:02d}'

            if week_key not in week_info:
                monday = datetime.fromisocalendar(year, week, 1).date()
                sunday = datetime.fromisocalendar(year, week, 7).date()
                week_info[week_key] = {
                    'label':     f'W{week:02d}',
                    'year':      year,
                    'date_from': str(monday),
                    'date_to':   str(sunday),
                }

            wc = wo.workcenter_id
            wc_names[wc.id] = wc.name

            mo = wo.production_id
            pos_data = mo_po_data.get(mo.id, [])

            wc_cell_map[wc.id][week_key].append({
                'wo_id':          wo.id,
                'mo_id':          mo.id,
                'mo_name':        mo.name or '',
                'product_name':   mo.product_id.display_name or '',
                'qty':            mo.product_qty or 0.0,
                'uom':            mo.product_uom_id.name or '',
                'state':          mo.state,
                'state_label':    _MO_STATE_LABEL.get(mo.state, mo.state),
                'wo_date':        dt.strftime('%d/%m/%Y %H:%M'),
                'pos':            pos_data,
                'pos_count':      len(pos_data),
                'has_late_pos':   any(p['is_late'] for p in pos_data),
                'has_pending_pos': any(p['state'] in ('draft', 'sent') for p in pos_data),
            })

        week_keys = sorted(week_info.keys())

        wc_rows = []
        for wc_id in sorted(wc_names.keys(), key=lambda i: wc_names[i]):
            cells = {wk: wc_cell_map[wc_id].get(wk, []) for wk in week_keys}
            wc_rows.append({
                'wc_id':   wc_id,
                'wc_name': wc_names[wc_id],
                'cells':   cells,
            })

        all_mo_ids = {wo.production_id.id for wo in workorders}
        all_po_ids = {po['po_id'] for data in mo_po_data.values() for po in data}

        return {
            'week_keys':   week_keys,
            'week_labels': week_info,
            'wc_rows':     wc_rows,
            'total_mos':   len(all_mo_ids),
            'total_pos':   len(all_po_ids),
        }

    # ── Helpers privados ──────────────────────────────────────────────────────

    def _pca_collect_po_lines(self, root_mo):
        """Recopila todas las purchase.order.line relacionadas con root_mo
        y sus OFs descendientes a cualquier profundidad.

        Usa dos estrategias combinadas para cubrir los distintos casos de
        cómo Odoo vincula la cadena de fabricación:

        Estrategia 1 — por movimientos de stock:
            move_raw_ids → move_orig_ids → purchase_line_id  (OC directa)
                                         → production_id      (OF hija)

        Estrategia 2 — por campo origin:
            Las OFs hijas tienen en su `origin` el nombre de la OF madre.
            Las OCs tienen en su `origin` el nombre de la OF que las generó.
            Esto cubre los casos en que el scheduler crea los documentos sin
            enlazar los movimientos de stock.
        """
        visited_mo = set()
        queue = [root_mo]
        all_mos = []

        # BFS: recopila todas las OFs de la cadena
        while queue:
            mo = queue.pop(0)
            if mo.id in visited_mo:
                continue
            visited_mo.add(mo.id)
            all_mos.append(mo)

            # Estrategia 1: OFs hijas vía movimientos
            for raw in mo.move_raw_ids:
                for sup in raw.move_orig_ids:
                    if sup.production_id and sup.production_id.id not in visited_mo:
                        queue.append(sup.production_id)

            # Estrategia 2: OFs hijas vía campo origin
            if mo.name:
                children = self.env['mrp.production'].search([
                    ('origin', 'ilike', mo.name),
                    ('id', 'not in', list(visited_mo)),
                    ('state', 'not in', ['cancel']),
                ])
                for child in children:
                    if child.id not in visited_mo:
                        queue.append(child)

        # Recopila líneas de OC de todas las OFs encontradas
        line_ids = set()
        for mo in all_mos:
            # Estrategia 1: vía movimientos con purchase_line_id
            for raw in mo.move_raw_ids:
                for sup in raw.move_orig_ids:
                    if sup.purchase_line_id:
                        line_ids.add(sup.purchase_line_id.id)

            # Estrategia 2: vía campo origin de la OC
            if mo.name:
                pos = self.env['purchase.order'].search([
                    ('origin', 'ilike', mo.name),
                    ('state', 'not in', ['cancel']),
                ])
                for po in pos:
                    line_ids.update(po.order_line.ids)

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
