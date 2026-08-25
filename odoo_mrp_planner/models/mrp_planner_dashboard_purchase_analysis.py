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
    'draft':    'Cotización',
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

        # BFS batch para todas las OFs raíz de una sola vez
        root_mos = workorders.mapped('production_id')
        mo_po_data = self._pca_batch_po_data(root_mos, today)

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
                'product_name':   mo.product_id.name or '',
                'qty':            mo.product_qty or 0.0,
                'uom':            mo.product_uom_id.name or '',
                'state':          mo.state,
                'state_label':    _MO_STATE_LABEL.get(mo.state, mo.state),
                'wo_date':        dt.strftime('%d/%m/%Y %H:%M'),
                'pos':            pos_data,
                'pos_count':      len(pos_data),
                'has_late_pos':   any(p['is_late'] for p in pos_data),
                'has_pending_pos': any(
                    p['state'] in ('draft', 'sent')
                    or (p['state'] == 'purchase' and p['pct_received'] < 100)
                    for p in pos_data
                ),
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

    def _pca_batch_po_data(self, root_mos, today):
        """BFS batch para TODOS los root_mos en conjunto.

        En vez de N BFS individuales con ilike por MO, hace:
        - UNA query por nivel del BFS (origin IN [nombres del nivel])
        - UNA query global para todas las OCs al final

        Retorna: {root_mo_id: [po_line_dicts]}
        """
        MO  = self.env['mrp.production']
        PO  = self.env['purchase.order']
        POL = self.env['purchase.order.line']

        if not root_mos:
            return {}

        # Map mo_id → root_mo_id que lo originó
        mo_to_root = {mo.id: mo.id for mo in root_mos}
        all_mo_ids = set(mo_to_root)
        current_level = root_mos   # recordset

        # BFS nivel a nivel — una query por nivel
        while current_level:
            current_names = [mo.name for mo in current_level if mo.name]
            if not current_names:
                break

            # Estrategia 1: OFs hijas vía origin (UNA query exacta, usa índice)
            children_q = MO.search([
                ('origin', 'in', current_names),
                ('id', 'not in', list(all_mo_ids)),
                ('state', 'not in', ['cancel']),
            ])

            # Estrategia 2: OFs hijas vía movimientos (batch con mapped)
            children_m = current_level.mapped(
                'move_raw_ids.move_orig_ids.production_id'
            ).filtered(lambda m: m.id not in all_mo_ids)

            all_children = children_q | children_m
            if not all_children:
                break

            # Build child_id → parent_mo_id desde los moves (ya en cache)
            child_to_parent = {}
            for parent in current_level:
                for raw in parent.move_raw_ids:
                    for sup in raw.move_orig_ids:
                        if sup.production_id and sup.production_id.id not in child_to_parent:
                            child_to_parent[sup.production_id.id] = parent.id

            # Asignar ownership a los hijos
            name_to_parent_id = {mo.name: mo.id for mo in current_level if mo.name}
            for child in all_children:
                if child.id in mo_to_root:
                    continue
                origin = (child.origin or '').strip()
                parent_id = name_to_parent_id.get(origin) or child_to_parent.get(child.id)
                if parent_id:
                    mo_to_root[child.id] = mo_to_root.get(parent_id, parent_id)

            new_children = all_children.filtered(lambda m: m.id not in all_mo_ids)
            all_mo_ids.update(new_children.ids)
            current_level = new_children

        # Todos los MOs de la cadena
        all_mos   = MO.browse(list(all_mo_ids))
        all_names = [mo.name for mo in all_mos if mo.name]

        # Product_ids de componentes consumidos por cada root MO (de sus move_raw_ids,
        # ya en cache del BFS). Se usa para filtrar las líneas de OC al final.
        root_bom_products = {mo.id: set() for mo in root_mos}
        for mo in all_mos:
            root_id = mo_to_root.get(mo.id)
            if root_id in root_bom_products:
                for raw in mo.move_raw_ids:
                    if raw.product_id:
                        root_bom_products[root_id].add(raw.product_id.id)

        # UNA query para todas las OCs (origin exacto, usa índice)
        all_pos = PO.search([
            ('origin', 'in', all_names),
            ('state', 'not in', ['cancel']),
        ]) if all_names else PO

        # Prefetch para evitar N+1 en _pca_format_po_lines
        if all_pos:
            all_pos.mapped('order_line.product_id')
            all_pos.mapped('order_line.date_planned')
            all_pos.mapped('order_line.qty_received')
            all_pos.mapped('partner_id')
            if 'subcontract_production_ids' in PO._fields:
                all_pos.mapped('subcontract_production_ids')

        # Map: mo_name → po_lines
        name_to_lines = {}
        for po in all_pos:
            name_to_lines.setdefault((po.origin or '').strip(), []).extend(po.order_line)

        # Moves-based: prefetch y recopilar
        if all_mos:
            all_mos.mapped('move_raw_ids.move_orig_ids.purchase_line_id')

        move_lines_by_mo = {}   # mo_id → set of line_ids
        for mo in all_mos:
            lids = set()
            for raw in mo.move_raw_ids:
                for sup in raw.move_orig_ids:
                    if sup.purchase_line_id:
                        lids.add(sup.purchase_line_id.id)
            move_lines_by_mo[mo.id] = lids

        # Build root_mo_id → set of line_ids
        root_line_ids = {mo.id: set() for mo in root_mos}
        all_unique_ids = set()

        for mo in all_mos:
            root_id = mo_to_root.get(mo.id)
            if root_id not in root_line_ids:
                continue
            bucket = root_line_ids[root_id]
            # origin-based
            for line in name_to_lines.get(mo.name or '', []):
                bucket.add(line.id)
                all_unique_ids.add(line.id)
            # moves-based
            for lid in move_lines_by_mo.get(mo.id, set()):
                bucket.add(lid)
                all_unique_ids.add(lid)

        # Prefetch todos los campos de línea de una vez
        if all_unique_ids:
            all_lines_rs = POL.browse(list(all_unique_ids))
            all_lines_rs.mapped('order_id.partner_id')
            all_lines_rs.mapped('order_id.state')
            all_lines_rs.mapped('product_id')
            all_lines_rs.mapped('qty_received')
            all_lines_rs.mapped('date_planned')
            if 'subcontract_production_ids' in PO._fields:
                all_lines_rs.mapped('order_id.subcontract_production_ids')

        # Map line_id → product_id (desde cache del prefetch, sin query)
        line_pid_map = {
            line.id: line.product_id.id
            for line in POL.browse(list(all_unique_ids))
        } if all_unique_ids else {}

        # Formatear por root MO filtrando por árbol de consumo (LdM real)
        result = {}
        for mo in root_mos:
            all_ids  = root_line_ids.get(mo.id, set())
            bom_pids = root_bom_products.get(mo.id, set())
            if bom_pids:
                # Solo incluir líneas cuyo producto está en la cadena de consumo
                filtered_ids = {
                    lid for lid in all_ids
                    if line_pid_map.get(lid) in bom_pids
                }
            else:
                filtered_ids = all_ids   # sin info de LdM, mostrar todo
            result[mo.id] = self._pca_format_po_lines(
                POL.browse(list(filtered_ids)), today)

        return result

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
                'product':        line.product_id.name or '',
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
