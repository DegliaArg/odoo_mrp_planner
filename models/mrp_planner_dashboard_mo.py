# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_planner_dashboard_mo.py
Modelo: extensión de 'mrp.planner.dashboard'

Agrega al dashboard del planificador MRP los métodos de consulta de Órdenes
de Fabricación (OFs), alertas y programaciones de producción que alimentan
los widgets del panel principal.

Responsabilidades:
- Retornar listas paginadas de OFs activas, finalizadas y con reprogramación pendiente.
- Calcular KPIs (totales, en progreso, retrasadas, finalizadas, parciales) coherentes
  con los botones de navegación del frontend.
- Proveer contadores de alertas del sistema (retrasos, urgencias, desfases de cantidad).
- Construir la comparativa producido vs. programado por producto en un rango de fechas.
- Exponer acciones de navegación hacia los sub-paneles de detalle (OFs, POs, programaciones).

Relacionado con:
- mrp.planner.dashboard: modelo base que este mixin extiende con widgets de OFs.
- mrp.production: fuente principal de órdenes de fabricación consultadas.
- mrp.reschedule.alert: tabla de alertas usada por get_alert_stats.
- mrp.production.request: programaciones activas consultadas por get_request_widget_data.
- mrp.planner.detail.dashboard: destino de las acciones de navegación backwards-compat.
- mrp.schedule.mixin.no_subcontract_domain: helper que excluye OFs subcontratadas.
"""
import logging
from datetime import datetime

from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain

_logger = logging.getLogger(__name__)


class MrpPlannerDashboardMo(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Widget OFs filtrable ─────────────────────────────────────────────────

    @api.model
    def get_filtered_mos(self, date_from, date_to, warehouse_id=None):
        """
        Retorna OFs activas que solapan con el rango de fechas, excluyendo subcontratadas.

        Usado por el widget simplificado de OFs del dashboard (sin paginación ni KPIs).
        Si se especifica warehouse_id, filtra solo las OFs de ese almacén.

        :param date_from: str con formato 'YYYY-MM-DD', inicio del rango.
        :param date_to: str con formato 'YYYY-MM-DD', fin del rango (se extiende a 23:59:59).
        :param warehouse_id: int|None — ID del almacén a filtrar; None para todos los permitidos.
        :returns: list[dict] con campos id, name, product, qty, date_finished, state,
                  delayed (bool) y reschedule (bool) por cada OF encontrada.
        """
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        no_sc = no_subcontract_domain(self.env)
        wh_mo = [('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._wh_domain_mo(self._get_allowed_wh_ids())
        domain = [
            ('state', 'not in', ('done', 'cancel')),
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            '&',
            ('date_finished', '=', False),
            ('date_start', '>=', fields.Datetime.to_string(first_day)),
        ] + no_sc + wh_mo

        mos = self.env['mrp.production'].search(domain, order='date_finished asc')

        now = fields.Datetime.now()
        result = []
        for mo in mos:
            result.append({
                'id':            mo.id,
                'name':          mo.name,
                'product':       mo.product_id.display_name if mo.product_id else '',
                'qty':           mo.product_qty,
                'date_finished': mo.date_finished.strftime('%d/%m/%Y') if mo.date_finished else '',
                'state':         mo.state,
                'delayed':       bool(mo.date_finished and mo.date_finished < now),
                'reschedule':    bool(mo.x_reschedule_needed),
            })
        return result

    # ── Widget Alertas ───────────────────────────────────────────────────────

    @api.model
    def get_alert_stats(self, states=None):
        """
        Retorna contadores de alertas activas (no resueltas), excluyendo las de OFs subcontratadas.

        Las alertas sin OF asociada (ej. recepciones, OCs) siempre se incluyen; solo se
        excluyen las alertas cuya production_id apunta a una OF subcontratada.

        :param states: parámetro reservado para uso futuro; actualmente no se aplica.
        :returns: dict con claves:
                  - mo_delayed (int): alertas de tipo 'mo_delayed'.
                  - mo_upcoming (int): alertas de tipo 'mo_upcoming'.
                  - mo_in_progress (int): OFs actualmente en estado progress o to_close.
                  - qty_mismatch (int): alertas de tipo 'qty_mismatch'.
                  - critical (int): alertas con severidad 'critical'.
        """
        Alert = self.env['mrp.reschedule.alert']
        base  = [('resolved', '=', False)]
        sc_loc_ids = self.env['stock.location'].search(
            [('is_subcontracting_location', '=', True)]
        ).ids
        sc_mo_ids = self.env['mrp.production'].search(
            [('location_src_id', 'in', sc_loc_ids)]
        ).ids if sc_loc_ids else []
        # Incluir alertas sin OF (recepciones, OCs); excluir solo las de OFs SBC
        no_sc = ['|', ('production_id', '=', False),
                 ('production_id', 'not in', sc_mo_ids)] if sc_mo_ids else []
        wh_alert = self._wh_domain_alert(self._get_allowed_wh_ids())
        wh_mo    = self._wh_domain_mo(self._get_allowed_wh_ids())

        def cnt(alert_type):
            return Alert.search_count(base + no_sc + wh_alert + [('alert_type', '=', alert_type)])

        mo_in_progress = self.env['mrp.production'].search_count(
            [('state', 'in', ('progress', 'to_close'))] + no_subcontract_domain(self.env) + wh_mo
        )

        return {
            'mo_delayed':     cnt('mo_delayed'),
            'mo_upcoming':    cnt('mo_upcoming'),
            'mo_in_progress': mo_in_progress,
            'qty_mismatch':   cnt('qty_mismatch'),
            'critical':       Alert.search_count(base + no_sc + wh_alert + [('severity', '=', 'critical')]),
            'sc_loc_ids':     sc_loc_ids,
        }

    # ── Widget OFs con pestañas ──────────────────────────────────────────────

    @api.model
    def get_mo_widget_data(self, date_from, date_to, warehouse_id=None, sort_field=None, sort_dir='asc', page=1, page_size=50, states=None):
        """
        Retorna KPIs de OFs y la página de registros solicitada para el widget principal de OFs.

        Incluye tanto las OFs activas que solapan el rango como las OFs finalizadas ('done')
        dentro del mismo rango. Los KPIs se calculan sobre el conjunto completo (sin paginar)
        para que los contadores del encabezado sean siempre consistentes.

        Además calcula en batch las entregas salientes pendientes por producto para evitar
        N+1 queries dentro del loop de serialización.

        :param date_from: str 'YYYY-MM-DD', inicio del rango.
        :param date_to: str 'YYYY-MM-DD', fin del rango.
        :param warehouse_id: int|None — ID del almacén a filtrar; None para todos los permitidos.
        :param sort_field: str|None — campo lógico de ordenamiento
                           ('name', 'product', 'qty', 'date_finished', 'state', 'delayed', 'reschedule').
        :param sort_dir: 'asc' o 'desc'.
        :param page: int — página a devolver (base 1).
        :param page_size: int — cantidad máxima de registros por página.
        :param states: list[str]|None — estados a incluir; si es None se excluyen 'done' y 'cancel'.
        :returns: dict con:
                  - kpis (dict): total, in_progress, delayed, reschedule, done, partial.
                  - mos (list[dict]): registros de la página con campos id, name, product, qty,
                    date_finished, state, delayed, reschedule, pending_delivery.
        """
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _MO_FIELD = {
            'name': 'name', 'product': 'product_id', 'qty': 'product_qty',
            'date_finished': 'date_finished', 'state': 'state',
            'delayed': 'date_finished', 'reschedule': 'x_reschedule_needed',
        }
        mo_f     = _MO_FIELD.get(sort_field, 'date_finished')
        mo_order = f'{mo_f} {_sd}'

        no_sc = no_subcontract_domain(self.env)
        wh_mo = [('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._wh_domain_mo(self._get_allowed_wh_ids())
        # Estados activos seleccionados (excluye 'done' que tiene su propio dominio)
        active_states = [s for s in (states or []) if s != 'done'] if states else []
        state_clause  = [('state', 'in', active_states)] if active_states else [('state', 'not in', ('done', 'cancel'))]
        domain = state_clause + [
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            '&',
            ('date_finished', '=', False),
            ('date_start', '>=', fields.Datetime.to_string(first_day)),
        ] + no_sc + wh_mo

        mos = self.env['mrp.production'].search(domain, order=mo_order)

        # OFs finalizadas en el mismo rango de fechas
        done_domain = [
            ('state', '=', 'done'),
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            ('date_finished', '<=', fields.Datetime.to_string(last_day)),
        ] + no_sc + wh_mo
        done_mos = self.env['mrp.production'].search(done_domain)

        offset   = (max(1, page) - 1) * page_size
        mos_page = mos[offset:offset + page_size]

        now = fields.Datetime.now()

        # Batch-compute pending outgoing deliveries per product (ítem 7)
        product_ids = list({mo.product_id.id for mo in mos_page if mo.product_id})
        if product_ids:
            out_moves = self.env['stock.move'].search([
                ('product_id', 'in', product_ids),
                ('state', 'not in', ('done', 'cancel')),
                ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ])
            pending_out = {}
            for m in out_moves:
                pid = m.product_id.id
                pending_out[pid] = pending_out.get(pid, 0.0) + m.product_uom_qty
        else:
            pending_out = {}

        def _mo_dict(mo):
            return {
                'id':               mo.id,
                'name':             mo.name,
                'product':          mo.product_id.display_name if mo.product_id else '',
                'qty':              mo.product_qty,
                'date_finished':    mo.date_finished.strftime('%d/%m/%Y') if mo.date_finished else '',
                'state':            mo.state,
                'delayed':          bool(mo.date_finished and mo.date_finished < now),
                'reschedule':       bool(mo.x_reschedule_needed),
                'pending_delivery': round(pending_out.get(mo.product_id.id, 0.0), 2),
            }

        return {
            'kpis': {
                'total':       len(mos),
                'in_progress': len(mos.filtered(lambda m: m.state in ('progress', 'to_close'))),
                'delayed':     len(mos.filtered(lambda m: m.date_finished and m.date_finished < now)),
                'reschedule':  len(mos.filtered(lambda m: m.x_reschedule_needed)),
                'done':        len(done_mos),
                'partial':     len(mos.filtered(lambda m: m.state == 'to_close')),
            },
            'mos': [_mo_dict(m) for m in mos_page],
        }

    @api.model
    def get_mo_kpi_counts(self, date_from, date_to, warehouse_id=None):
        """
        Retorna contadores de KPIs usando los mismos dominios que los botones de navegación del frontend.

        :param date_from: str 'YYYY-MM-DD', inicio del rango.
        :param date_to: str 'YYYY-MM-DD', fin del rango.
        :param warehouse_id: int|None — ID del almacén a filtrar; None para todos los permitidos.
        :returns: dict con claves total, in_progress, delayed, reschedule, done, partial (int cada una).
        """
        now   = fields.Datetime.now()
        MO    = self.env['mrp.production']
        no_sc = no_subcontract_domain(self.env)
        wh_mo = [('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._wh_domain_mo(self._get_allowed_wh_ids())
        dFrom = date_from + ' 00:00:00'
        dTo   = date_to   + ' 23:59:59'
        active = [('state', 'not in', ('done', 'cancel', 'draft'))]
        now_s  = fields.Datetime.to_string(now)

        cfg  = self.env['mrp.reschedule.config'].get_config()
        mode = (cfg.comparison_date_mode if cfg else None) or 'finish_date'
        if mode == 'start_date':
            date_d = [('date_start', '>=', dFrom), ('date_start', '<=', dTo)]
        elif mode in ('overlap', 'proportional'):
            date_d = [('date_start', '<=', dTo), '|',
                      ('date_finished', '>=', dFrom), ('date_finished', '=', False)]
        else:
            date_d = [('date_finished', '>=', dFrom), ('date_finished', '<=', dTo)]

        def _cnt(domain):
            return MO.search_count(domain)

        return {
            'total':       _cnt(active + date_d + no_sc + wh_mo),
            'in_progress': _cnt([('state', 'in', ('progress', 'to_close'))] + date_d + no_sc + wh_mo),
            'delayed':     _cnt(active + [('date_finished', '<', now_s)] + date_d + no_sc + wh_mo),
            'reschedule':  _cnt(active + [('x_reschedule_needed', '=', True)] + date_d + no_sc + wh_mo),
            'done':        _cnt([('state', '=', 'done')] + date_d + no_sc + wh_mo),
            'partial':     _cnt([('state', '=', 'to_close')] + date_d + no_sc + wh_mo),
        }

    @api.model
    def get_request_widget_data(self, sort_field=None, sort_dir='asc', page=1, page_size=50):
        """
        Retorna KPIs y la página de programaciones de producción activas (confirmed + calculated).

        Cada programación incluye un resumen de sus OFs: total, finalizadas y retrasadas.
        El KPI 'reschedule' cuenta programaciones confirmadas que tienen al menos una OF
        con x_reschedule_needed activado.

        :param sort_field: str|None — campo lógico de ordenamiento ('name', 'start_from', 'state').
        :param sort_dir: 'asc' o 'desc'.
        :param page: int — página a devolver (base 1).
        :param page_size: int — cantidad máxima de registros por página.
        :returns: dict con:
                  - kpis (dict): total, active (confirmed), calculated, reschedule, mos_delayed.
                  - requests (list[dict]): registros de la página con id, name, start_from, state,
                    mos_total, mos_done, mos_delayed.
        """
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _REQ_FIELD = {'name': 'name', 'start_from': 'start_from', 'state': 'state'}
        req_f = _REQ_FIELD.get(sort_field, 'id')

        confirmed  = Req.search([('state', '=', 'confirmed')])
        calculated = Req.search([('state', '=', 'calculated')])
        all_active = (confirmed | calculated).sorted(req_f, reverse=(_sd == 'desc'))
        all_mos    = confirmed.mapped('item_ids.production_id').filtered(lambda m: m.id)

        offset          = (max(1, page) - 1) * page_size
        all_active_page = all_active[offset:offset + page_size]

        def _req_dict(r):
            mos = r.item_ids.mapped('production_id').filtered(lambda m: m.id)
            return {
                'id':          r.id,
                'name':        r.name,
                'start_from':  r.start_from.strftime('%d/%m/%Y') if r.start_from else '—',
                'state':       r.state,
                'mos_total':   len(mos),
                'mos_done':    len(mos.filtered(lambda m: m.state == 'done')),
                'mos_delayed': len(mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )),
            }

        return {
            'kpis': {
                'total':       len(all_active),
                'active':      len(confirmed),
                'calculated':  len(calculated),
                'reschedule':  len(confirmed.filtered(
                    lambda r: any(
                        it.production_id and it.production_id.x_reschedule_needed
                        for it in r.item_ids
                    )
                )),
                'mos_delayed': len(all_mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )),
            },
            'requests': [_req_dict(r) for r in all_active_page],
        }

    @api.model
    def get_comparison_data(self, date_from, date_to, warehouse_id=None, page=1, page_size=50, sort_field=None, sort_dir='desc'):
        """
        Retorna la comparativa producido vs. programado agrupada por producto para el rango dado.

        :param date_from: str 'YYYY-MM-DD', inicio del rango.
        :param date_to: str 'YYYY-MM-DD', fin del rango.
        :param warehouse_id: int|None — ID del almacén a filtrar; None para todos los permitidos.
        :returns: dict con:
                  - kpis (dict): planned (float), produced (float), pct (float, % de cumplimiento),
                    ofs_done (int).
                  - items (list[dict], máx. 20): product_id, product, uom, planned_qty,
                    produced_qty, pct por producto, ordenados por planned_qty desc.
        """
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        no_sc = no_subcontract_domain(self.env)
        wh_mo = [('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._wh_domain_mo(self._get_allowed_wh_ids())

        cfg  = self.env['mrp.reschedule.config'].get_config()
        mode = (cfg.comparison_date_mode if cfg else None) or 'finish_date'

        mo_states = []
        if cfg:
            if cfg.forecast_mo_state_draft:     mo_states.append('draft')
            if cfg.forecast_mo_state_confirmed: mo_states.append('confirmed')
            if cfg.forecast_mo_state_progress:  mo_states.append('progress')
            if cfg.forecast_mo_state_to_close:  mo_states.append('to_close')
            if cfg.forecast_mo_state_done:      mo_states.append('done')
        if not mo_states:
            mo_states = ['confirmed', 'progress', 'to_close']

        first_day_str = fields.Datetime.to_string(first_day)
        last_day_str  = fields.Datetime.to_string(last_day)

        state_domain = [('state', 'in', mo_states)]

        if mode == 'finish_date':
            all_mos = self.env['mrp.production'].search(state_domain + [
                ('date_finished', '>=', first_day_str),
                ('date_finished', '<=', last_day_str),
            ] + no_sc + wh_mo)
        elif mode == 'start_date':
            all_mos = self.env['mrp.production'].search(state_domain + [
                ('date_start', '>=', first_day_str),
                ('date_start', '<=', last_day_str),
            ] + no_sc + wh_mo)
        else:
            # overlap y proportional: toda OF que solape el período
            all_mos = self.env['mrp.production'].search(state_domain + [
                ('date_start', '<=', last_day_str),
                '|',
                ('date_finished', '>=', first_day_str),
                ('date_finished', '=', False),
            ] + no_sc + wh_mo)

        product_data = {}

        if mode == 'proportional':
            all_mos.mapped('move_finished_ids')  # prefetch en un batch
            for mo in all_mos:
                pid = mo.product_id.id
                if not pid:
                    continue
                mo_start = mo.date_start
                mo_end   = mo.date_finished
                if mo_start and mo_end and mo_start < mo_end:
                    total_secs   = (mo_end - mo_start).total_seconds()
                    ov_start     = max(mo_start, first_day)
                    ov_end       = min(mo_end, last_day)
                    overlap_secs = max(0.0, (ov_end - ov_start).total_seconds())
                    planned_qty  = mo.product_qty * (overlap_secs / total_secs)
                else:
                    planned_qty = mo.product_qty
                # Producido real: movimientos de salida del producto principal con fecha en el período
                done_in_period = mo.move_finished_ids.filtered(
                    lambda m, p=mo.product_id: (
                        m.state == 'done'
                        and m.product_id == p
                        and m.date >= first_day
                        and m.date <= last_day
                    )
                )
                produced_qty = sum(
                    getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                    for m in done_in_period
                )
                if pid not in product_data:
                    product_data[pid] = {
                        'product_id':   pid,
                        'product':      mo.product_id.display_name,
                        'uom':          mo.product_uom_id.name if mo.product_uom_id else '',
                        'planned_qty':  0.0,
                        'produced_qty': 0.0,
                    }
                product_data[pid]['planned_qty']  += planned_qty
                product_data[pid]['produced_qty'] += produced_qty
        else:
            for mo in all_mos:
                pid = mo.product_id.id
                if not pid:
                    continue
                if pid not in product_data:
                    product_data[pid] = {
                        'product_id':   pid,
                        'product':      mo.product_id.display_name,
                        'uom':          mo.product_uom_id.name if mo.product_uom_id else '',
                        'planned_qty':  0.0,
                        'produced_qty': 0.0,
                    }
                product_data[pid]['planned_qty']  += mo.product_qty
                product_data[pid]['produced_qty'] += mo.qty_produced

        items = sorted(product_data.values(), key=lambda x: x['planned_qty'], reverse=True)
        for item in items:
            item['pct'] = round(
                item['produced_qty'] / item['planned_qty'] * 100, 1
            ) if item['planned_qty'] > 0 else 0.0
            item['planned_qty']  = round(item['planned_qty'],  2)
            item['produced_qty'] = round(item['produced_qty'], 2)

        total_planned  = sum(x['planned_qty']  for x in items)
        total_produced = sum(x['produced_qty'] for x in items)
        pct = round(total_produced / total_planned * 100, 1) if total_planned > 0 else 0.0

        # Ordenamiento por campo solicitado
        _sort_map = {'product': 'product', 'planned_qty': 'planned_qty',
                     'produced_qty': 'produced_qty', 'pct': 'pct'}
        sf = _sort_map.get(sort_field)
        if sf:
            reverse = sort_dir != 'asc'
            if sf == 'product':
                items = sorted(items, key=lambda x: (x.get('product') or '').lower(), reverse=reverse)
            else:
                items = sorted(items, key=lambda x: x.get(sf) or 0, reverse=reverse)

        # Paginación
        total = len(items)
        page      = max(1, int(page))
        page_size = min(200, max(1, int(page_size)))
        offset    = (page - 1) * page_size

        # ofs_done siempre por date_finished en rango, independiente del modo,
        # porque es el KPI "terminadas en el período" que tiene sentido operativo.
        ofs_done = self.env['mrp.production'].search_count([
            ('state', '=', 'done'),
            ('date_finished', '>=', first_day_str),
            ('date_finished', '<=', last_day_str),
        ] + no_sc + wh_mo)

        return {
            'kpis': {
                'planned':  round(total_planned,  2),
                'produced': round(total_produced, 2),
                'pct':      pct,
                'ofs_done': ofs_done,
            },
            'items':         items[offset:offset + page_size],
            'total':         total,
            'mo_mode':       mode,
        }

    # ── Backwards compat (paneles de detalle) ─────────────────────────────────

    def action_open_mos_dashboard(self):
        """Abre el sub-panel de detalle de Órdenes de Fabricación."""
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('mos')

    def action_open_pos_dashboard(self):
        """Abre el sub-panel de detalle de Órdenes de Compra."""
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('pos')

    def action_open_requests_dashboard(self):
        """Abre el sub-panel de detalle de Programaciones de Producción."""
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('requests')
