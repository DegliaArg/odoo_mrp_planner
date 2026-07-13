# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_po.py
Modelo: extensión de mrp.planner.dashboard

Provee los datos del widget de Órdenes de Compra (OC) en el dashboard MRP.

Responsabilidades:
- Consultar OCs en sus distintos estados (borrador, a aprobar, aprobadas, vencidas, pendientes).
- Consultar recepciones (pickings entrantes) y entregas a subcontratistas vinculadas a OCs.
- Calcular KPIs de resumen para el widget (cantidades por estado, vencimientos, criticidad).
- Soportar filtrado por tipo (compra pura / subcontratación), rango de fechas, ordenamiento
  por columna y paginación del lado servidor.
- Detectar disponibilidad real de picking en Odoo 16+ donde 'partially_available' ya no
  existe como estado nativo.
- Trazar la Orden de Fabricación (OF) de subcontratación asociada a una entrega mediante
  cuatro estrategias de fallback sucesivas.

Relacionado con:
- purchase.order: origen principal de los datos de OC.
- stock.picking: recepciones y entregas a subcontratistas.
- mrp.reschedule.config: lee umbrales de criticidad (alert_po_critical_days) y visibilidad
  de la pestaña de servicios (show_po_services_tab).
- mrp.production: se traza para obtener el producto terminado de una subcontratación.
"""
import logging
from datetime import datetime
from collections import deque

from odoo import models, fields, api, _
from .const import DEFAULT_PO_CRITICAL_DAYS

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardPo(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Widget OCs con pestañas ──────────────────────────────────────────────

    @api.model
    def get_po_dashboard_data(self, filter_type='all', date_from=None, date_to=None, sort_field=None, sort_dir='asc', page=1, page_size=50):
        """
        Retorna todos los datos necesarios para renderizar el widget de OC del dashboard.

        Consulta OCs por estado, recepciones, entregas a subcontratistas y calcula KPIs
        de resumen. Aplica filtrado, ordenamiento y paginación en una sola llamada RPC
        para minimizar round-trips desde el cliente JS.

        Los servicios (OCs con todas las líneas de tipo 'service') se segregan y solo
        aparecen en la pestaña de servicios cuando la config lo habilita.

        :param filter_type: str — 'all', 'purchase' (solo compra directa) o
            'subcontract' (solo subcontratación).
        :param date_from: str|None — fecha mínima en formato 'YYYY-MM-DD'; filtra
            date_order para OCs y scheduled_date para pickings.
        :param date_to: str|None — fecha máxima en formato 'YYYY-MM-DD' (inclusive).
        :param sort_field: str|None — nombre de la columna a ordenar; valores válidos:
            'name', 'partner', 'date_planned', 'amount_total', 'scheduled_date',
            'overdue', 'availability', 'finished_product', 'po_name'.
        :param sort_dir: str — dirección de ordenamiento: 'asc' (default) o 'desc'.
        :param page: int — número de página base 1 para la paginación.
        :param page_size: int — cantidad de registros por página (default 50).
        :returns: dict con claves:
            - 'kpis': dict con contadores de KPIs.
            - 'show_services_tab': bool.
            - 'rfqs', 'to_approve', 'overdue', 'all_pos', 'pending_pos': list[dict] de OCs.
            - 'receipts', 'deliveries': list[dict] de pickings con líneas de movimiento.
            - 'services': list[dict] de OCs de servicio.
        """
        PO      = self.env['purchase.order']
        Picking = self.env['stock.picking']
        now     = fields.Datetime.now()

        # Sanitizar sort_dir para evitar inyección en la cláusula ORDER BY de ORM.
        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _rev = (_sd == 'desc')
        _PO_FIELD = {
            'name': 'name', 'partner': 'partner_id',
            'date_planned': 'date_planned', 'amount_total': 'amount_total',
        }
        _PICK_FIELD = {
            'name': 'name', 'partner': 'partner_id',
            'scheduled_date': 'scheduled_date', 'overdue': 'scheduled_date',
            'availability': 'state',
        }
        po_f       = _PO_FIELD.get(sort_field, 'date_planned')
        pick_f     = _PICK_FIELD.get(sort_field, 'scheduled_date')
        po_order   = f'{po_f} {_sd}'
        pick_order = f'{pick_f} {_sd}'
        offset     = (max(1, page) - 1) * page_size

        sc_domain = []
        if filter_type == 'purchase':
            sc_domain = [('subcontract_production_ids', '=', False)]
        elif filter_type == 'subcontract':
            sc_domain = [('subcontract_production_ids', '!=', False)]

        date_domain = []
        if date_from:
            date_domain.append(('date_order', '>=', date_from + ' 00:00:00'))
        if date_to:
            date_domain.append(('date_order', '<=', date_to + ' 23:59:59'))

        sched_domain = []
        if date_from:
            sched_domain.append(('scheduled_date', '>=', date_from + ' 00:00:00'))
        if date_to:
            sched_domain.append(('scheduled_date', '<=', date_to + ' 23:59:59'))

        rfq_dom      = [('state', 'in', ('draft', 'sent'))] + sc_domain + date_domain
        approve_dom  = [('state', '=', 'to approve')] + sc_domain + date_domain
        # state='done' = OC bloqueada/cerrada — no es accionable, no va en vencidas ni pendientes
        approved_dom = [('state', '=', 'purchase')] + sc_domain + date_domain

        approved = PO.search(approved_dom)
        overdue  = approved.filtered(lambda p: p.date_planned and p.date_planned < now)
        pending  = approved.filtered(lambda p: not p.date_planned or p.date_planned >= now)

        # Leer umbral crítico OC desde config
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        po_crit_days = cfg.alert_po_critical_days if cfg else DEFAULT_PO_CRITICAL_DAYS

        def _po_dict(po):
            return {
                'id':               po.id,
                'name':             po.name,
                'partner':          po.partner_id.display_name if po.partner_id else '',
                'date_planned':     po.date_planned.strftime('%d/%m/%Y') if po.date_planned else '—',
                'amount_total':     po.amount_total,
                'is_subcontract':   bool(po.subcontract_production_ids),
                'state':            po.state,
            }

        def _move_qty(m):
            """En Odoo 18, 'quantity' es el campo unificado (antes quantity_done
            en move_lines). Para pickings de subcontratación, reserved_availability=0
            pero quantity=demanda. Usamos el máximo de ambos para cubrir ambos casos."""
            return max(
                getattr(m, 'quantity', 0) or 0,
                getattr(m, 'reserved_availability', 0) or 0,
            )

        def _pick_avail(p):
            """En Odoo 16+, 'partially_available' fue eliminado como estado.
            Los pickings parcialmente reservados quedan en 'assigned'.
            Detectamos la diferencia comparando qty disponible vs demanda."""
            if p.state == 'assigned':
                is_partial = any(
                    _move_qty(m) < m.product_uom_qty - 0.001
                    for m in p.move_ids if m.state not in ('done', 'cancel')
                )
                return 'partially_available' if is_partial else 'assigned'
            if p.state == 'confirmed':
                has_any = any(
                    _move_qty(m) > 0.001
                    for m in p.move_ids if m.state not in ('done', 'cancel')
                )
                return 'partially_available' if has_any else 'confirmed'
            return p.state

        _AVAIL_LABEL = {
            'assigned':            'Disponible',
            'partially_available': 'Parcialmente',
            'confirmed':           'No disponible',
            'waiting':             'No disponible',
        }

        # Verificar disponibilidad de campos opcionales en tiempo de ejecución para
        # garantizar compatibilidad con versiones de Odoo que no tengan estos campos.
        _has_raw_mo  = 'raw_material_production_id' in self.env['stock.move']._fields
        _has_po_line = 'purchase_line_id' in self.env['mrp.production']._fields

        # Límite de profundidad para el BFS de trazado de movimientos. Previene bucles
        # infinitos en estructuras de picking circular o datos corruptos.
        MAX_DEPTH = 20
        def _trace_mo_iter(root_moves):
            """Recorre el árbol de movimientos de stock en anchura (BFS) sin recursión."""
            result = []
            queue = deque([(root_moves, 0)])
            while queue:
                moves, depth = queue.popleft()
                if depth >= MAX_DEPTH:
                    continue
                for move in moves:
                    result.append(move)
                    child = move.move_orig_ids
                    if child:
                        queue.append((child, depth + 1))
            return result

        def _delivery_mo_s1(p):
            """Estrategia 1: campo directo raw_material_production_id (usa prefetch)."""
            if not _has_raw_mo:
                return None
            for mv in p.move_ids:
                if mv.raw_material_production_id:
                    return mv.raw_material_production_id
            return None

        def _delivery_info(p):
            """Para un picking de entrega devuelve (po_name, finished_product).
            Busca la OF de subcontratación por 4 estrategias y extrae ambos datos."""
            # Estrategia 1: campo directo en el move (usa prefetch, O(1))
            mo = _delivery_mo_s1(p)
            # Estrategia 2: trazar move_dest_ids (versión iterativa)
            if not mo:
                _moves = _trace_mo_iter(p.move_ids)
                for _mv in _moves:
                    if _has_raw_mo and _mv.raw_material_production_id:
                        mo = _mv.raw_material_production_id
                        break
                    if _mv.production_id:
                        mo = _mv.production_id
                        break
            # Estrategia 3: desde líneas de la OC
            if not mo and p.purchase_id:
                for line in p.purchase_id.order_line:
                    for mv in line.move_ids:
                        if _has_raw_mo and mv.raw_material_production_id:
                            mo = mv.raw_material_production_id
                            break
                    if mo:
                        break
            # Estrategia 4: por grupo de abastecimiento (fallback)
            if not mo and p.group_id:
                mo = self.env['mrp.production'].search(
                    [('procurement_group_id', '=', p.group_id.id)], limit=1
                )

            finished = (mo.product_id.display_name if mo and mo.product_id else None) or '—'

            po_name = '—'
            if mo and _has_po_line:
                try:
                    if mo.purchase_line_id and mo.purchase_line_id.order_id:
                        po_name = mo.purchase_line_id.order_id.name
                except Exception:
                    pass

            return po_name, finished

        def _pick_dict(p, include_lines=False):
            """Serializa un stock.picking a dict listo para el frontend.

            Detecta si el picking es una recepción o una entrega a subcontratista
            para poblar 'po_name' y 'finished_product' de la fuente correcta.
            Cuando include_lines=True adjunta las líneas de movimiento con cantidades
            (demanda vs. reservado/recibido), filtrando moves ya procesados o cancelados.

            :param p: stock.picking — picking a serializar.
            :param include_lines: bool — si True incluye las líneas de movimiento.
            :returns: dict con campos del picking y, opcionalmente, 'lines'.
            """
            avail = _pick_avail(p)
            is_incoming = p.picking_type_code == 'incoming'
            if is_incoming:
                po_name  = p.purchase_id.name if p.purchase_id else '—'
                finished = None
            else:
                po_name, finished = _delivery_info(p)
            result = {
                'id':               p.id,
                'name':             p.name,
                'po_name':          po_name,
                'finished_product': finished,
                'partner':          p.partner_id.display_name if p.partner_id else '',
                'scheduled_date': p.scheduled_date.strftime('%d/%m/%Y') if p.scheduled_date else '—',
                'state':          p.state,
                'overdue':        bool(p.scheduled_date and p.scheduled_date < now),
                'days_late':      max(0, (now - p.scheduled_date).days) if p.scheduled_date and p.scheduled_date < now else 0,
                'availability':   avail,
                'availability_label': _AVAIL_LABEL.get(avail, '—'),
                'lines':          [],
                'is_incoming':    is_incoming,
            }
            if include_lines:
                # Para recepciones: quantity (campo "done" en Odoo 18) se pre-rellena
                # automáticamente igual a la demanda cuando el picking es assigned.
                # Solo mostrar como recibido si el picking fue efectivamente validado (done).
                result['lines'] = [{
                    'product':  m.product_id.display_name,
                    'demand':   m.product_uom_qty,
                    'reserved': (getattr(m, 'quantity', 0) or 0) if (is_incoming and p.state == 'done')
                                else (0 if is_incoming else _move_qty(m)),
                    'uom':      m.product_uom.name if m.product_uom else '',
                } for m in p.move_ids if m.product_id and m.state not in ('done', 'cancel')]
            return result

        rfqs_list       = PO.search(rfq_dom,     order=po_order)
        to_approve_list = PO.search(approve_dom, order=po_order)

        # ── Separar servicios ────────────────────────────────────────────────
        # Los servicios se excluyen SIEMPRE de las listas de OC (bienes).
        # Solo se muestran en la pestaña de servicios cuando show_svc=True.
        show_svc = bool(cfg and cfg.show_po_services_tab)

        def _is_svc(po):
            """Retorna True si la OC tiene líneas y todas son de tipo servicio."""
            lines = po.order_line.filtered(lambda l: l.product_id)
            return bool(lines) and all(l.product_id.type == 'service' for l in lines)

        rfqs_svc        = rfqs_list.filtered(_is_svc)
        rfqs_list       = rfqs_list - rfqs_svc
        approve_svc     = to_approve_list.filtered(_is_svc)
        to_approve_list = to_approve_list - approve_svc
        approved_svc    = approved.filtered(_is_svc)
        approved        = approved - approved_svc
        overdue         = overdue - approved_svc
        pending         = pending - approved_svc

        if show_svc:
            services_rs = (rfqs_svc | approve_svc | approved_svc).sorted(po_f, reverse=_rev)
        else:
            services_rs = self.env['purchase.order']

        overdue_list  = overdue.sorted(po_f,  reverse=_rev)
        all_pos_list  = approved.sorted(po_f, reverse=_rev)
        pending_list  = pending.sorted(po_f,  reverse=_rev)

        # Sort por nombre de partner (no por ID): hacerlo en Python para que
        # sea correcto en todas las páginas, no solo la primera.
        if sort_field == 'partner':
            _pk = lambda r: (r.partner_id.display_name or '').lower()
            rfqs_list       = rfqs_list.sorted(_pk,       reverse=_rev)
            to_approve_list = to_approve_list.sorted(_pk, reverse=_rev)
            overdue_list    = overdue_list.sorted(_pk,    reverse=_rev)
            all_pos_list    = all_pos_list.sorted(_pk,    reverse=_rev)
            pending_list    = pending_list.sorted(_pk,    reverse=_rev)
            services_rs     = services_rs.sorted(_pk,     reverse=_rev)



        rfqs_pg       = rfqs_list[offset:offset + page_size]
        to_approve_pg = to_approve_list[offset:offset + page_size]
        overdue_pg    = overdue_list[offset:offset + page_size]
        all_pos_pg    = all_pos_list[offset:offset + page_size]
        pending_pg    = pending_list[offset:offset + page_size]

        # ── Recepciones (incoming pickings linked to POs) ────────────────────
        receipt_sc = []
        if filter_type == 'purchase':
            receipt_sc = [('purchase_id.subcontract_production_ids', '=', False)]
        elif filter_type == 'subcontract':
            receipt_sc = [('purchase_id.subcontract_production_ids', '!=', False)]

        receipts = Picking.search([
            ('state', 'in', ['waiting', 'confirmed', 'assigned']),
            ('picking_type_code', '=', 'incoming'),
            ('purchase_id', '!=', False),
            ('return_id', '=', False),
        ] + receipt_sc, order=pick_order)

        overdue_receipts = receipts.filtered(lambda p: p.scheduled_date and p.scheduled_date < now)

        # ── Entregas (component deliveries to subcontractors) ───────────────
        # La OC no es un M2O en estos pickings, es texto. El único campo
        # confiable es el destino: ubicación de subcontratación.
        # Incluye 'done' para que el usuario vea las entregas ya realizadas.
        deliveries = Picking.search([
            ('state', '!=', 'cancel'),
            ('location_dest_id.is_subcontracting_location', '=', True),
        ] + sched_domain, order=pick_order)

        # Prefetch para evitar N+1 en sort y en _pick_dict
        (receipts | deliveries).mapped('move_ids')
        if deliveries and _has_raw_mo:
            deliveries.mapped('move_ids.raw_material_production_id.product_id')
            if _has_po_line:
                deliveries.mapped('move_ids.raw_material_production_id.purchase_line_id.order_id')

        # Sort por partner/availability/po_name en pickings (Python, cross-página)
        if sort_field == 'partner':
            _ppk = lambda p: (p.partner_id.display_name or '').lower()
            receipts   = receipts.sorted(_ppk,   reverse=_rev)
            deliveries = deliveries.sorted(_ppk, reverse=_rev)
        elif sort_field == 'availability':
            _AO = {'assigned': 0, 'partially_available': 1, 'confirmed': 2, 'waiting': 3}
            _ak = lambda p: _AO.get(_pick_avail(p), 99)
            receipts   = receipts.sorted(_ak,   reverse=_rev)
            deliveries = deliveries.sorted(_ak, reverse=_rev)
        elif sort_field == 'finished_product':
            def _fpk(p):
                mo = _delivery_mo_s1(p)
                return (mo.product_id.display_name if mo and mo.product_id else '').lower()
            deliveries = deliveries.sorted(_fpk, reverse=_rev)
        elif sort_field == 'po_name':
            def _dok(p):
                mo = _delivery_mo_s1(p)
                if mo and _has_po_line:
                    try:
                        if mo.purchase_line_id and mo.purchase_line_id.order_id:
                            return mo.purchase_line_id.order_id.name.lower()
                    except Exception:
                        pass
                return ''
            receipts   = receipts.sorted(lambda p: (p.purchase_id.name or '').lower(), reverse=_rev)
            deliveries = deliveries.sorted(_dok, reverse=_rev)

        receipts_pg        = receipts[offset:offset + page_size]
        deliveries_pg      = deliveries[offset:offset + page_size]
        services_pg        = services_rs[offset:offset + page_size]
        overdue_deliveries = deliveries.filtered(lambda p: p.scheduled_date and p.scheduled_date < now)

        return {
            'kpis': {
                'rfq':              len(rfqs_list),
                'to_approve':       len(to_approve_list),
                'total':            len(approved),
                'pending':          len(pending),
                'overdue':          len(overdue),
                'overdue_critical': len(overdue.filtered(
                    lambda p: (now - p.date_planned).days >= po_crit_days
                )),
                'receipts_total':    len(receipts),
                'receipts_overdue':  len(overdue_receipts),
                'deliveries_total':  len(deliveries),
                'deliveries_overdue': len(overdue_deliveries),
                'services_total':    len(services_rs),
                'po_critical_days':  po_crit_days,
            },
            'show_services_tab': show_svc,
            'rfqs':        [_po_dict(p) for p in rfqs_pg],
            'to_approve':  [_po_dict(p) for p in to_approve_pg],
            'overdue':     [_po_dict(p) for p in overdue_pg],
            'all_pos':     [_po_dict(p) for p in all_pos_pg],
            'pending_pos': [_po_dict(p) for p in pending_pg],
            'receipts':    [_pick_dict(p, True)  for p in receipts_pg],
            'deliveries':  [_pick_dict(p, True)  for p in deliveries_pg],
            'services':    [_po_dict(p) for p in services_pg],
        }
