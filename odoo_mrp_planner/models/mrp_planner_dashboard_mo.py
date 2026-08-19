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
- mrp.planner.detail.dashboard: destino de las acciones de navegación backwards-compat.
- mrp_planner_helpers.no_subcontract_domain: helper que excluye OFs subcontratadas.
"""
import logging
from datetime import datetime
from pytz import timezone as _tz, utc as _pytz_utc

from odoo import models, fields, api, _
from odoo.exceptions import AccessError
from odoo.tools import float_round
from odoo.addons.odoo_mrp_planner.models.mrp_planner_helpers import no_subcontract_domain


def _local_to_utc(env, datestr, end_of_day=False):
    """Convert a user-local date string 'YYYY-MM-DD' to a naive UTC datetime.
    Avoids the bug where OFs near UTC midnight fall in the wrong local-date bucket.
    """
    tz_name = env.context.get('tz') or env.user.tz or 'UTC'
    if end_of_day:
        naive = datetime.strptime(datestr, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    else:
        naive = datetime.strptime(datestr, '%Y-%m-%d')
    return _tz(tz_name).localize(naive).astimezone(_pytz_utc).replace(tzinfo=None)

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
        if warehouse_id:
            allowed_ids = self._get_allowed_wh_ids()
            if allowed_ids is not None and int(warehouse_id) not in allowed_ids:
                raise AccessError(_("Acceso denegado al depósito seleccionado"))

        first_day = _local_to_utc(self.env, date_from)
        last_day  = _local_to_utc(self.env, date_to, end_of_day=True)

        no_sc = no_subcontract_domain(self.env)
        wh_mo = ([('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._get_wh_domains().mo) + [('company_id', '=', self.env.company.id)]
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
        # Acota a la empresa activa (consistente con el resto de los paneles): la regla de
        # registro scopea a las empresas activas del selector, pero los KPIs deben reflejar
        # solo la empresa activa como los demás widgets.
        base  = [('resolved', '=', False), ('company_id', '=', self.env.company.id)]
        sc_loc_ids = self.env['stock.location'].search(
            [('is_subcontracting_location', '=', True)]
        ).ids
        sc_mo_ids = self.env['mrp.production'].search(
            [('location_src_id', 'in', sc_loc_ids)]
        ).ids if sc_loc_ids else []
        # Incluir alertas sin OF (recepciones, OCs); excluir solo las de OFs SBC
        no_sc = ['|', ('production_id', '=', False),
                 ('production_id', 'not in', sc_mo_ids)] if sc_mo_ids else []
        wh = self._get_wh_domains()
        wh_alert = wh.alert
        wh_mo    = wh.mo + [('company_id', '=', self.env.company.id)]

        def cnt(alert_type):
            return Alert.search_count(base + no_sc + wh_alert + [('alert_type', '=', alert_type)])

        mo_in_progress = self.env['mrp.production'].search_count(
            [('state', 'in', ('progress', 'to_close'))] + no_subcontract_domain(self.env) + wh_mo
        )

        # Días de atraso de las OFs atrasadas (C5 del backlog): estadístico
        # configurable en Ajustes → Alertas (máximo por defecto = el atraso más
        # viejo, o promedio) que acompaña al conteo en la card. Se calcula
        # desde la fecha de fin planificada de la OF de cada alerta activa.
        cfg = self.env['mrp.reschedule.config'].get_config()
        delay_stat = (cfg and cfg.alert_delay_stat) or 'max'
        delayed_alerts = Alert.search(
            base + no_sc + wh_alert + [('alert_type', '=', 'mo_delayed')])
        today = fields.Date.context_today(self)
        delay_days = [
            (today - a.production_id.date_finished.date()).days
            for a in delayed_alerts
            if a.production_id and a.production_id.date_finished
        ]
        delay_days = [d for d in delay_days if d >= 0]
        mo_delayed_days = None
        if delay_days:
            mo_delayed_days = (max(delay_days) if delay_stat == 'max'
                               else round(sum(delay_days) / len(delay_days)))

        return {
            'mo_delayed':      len(delayed_alerts),
            'mo_delayed_days': mo_delayed_days,
            'delay_stat':      delay_stat,
            'mo_upcoming':    cnt('mo_upcoming'),
            'mo_in_progress': mo_in_progress,
            'qty_mismatch':   cnt('qty_mismatch'),
            'critical':       Alert.search_count(base + no_sc + wh_alert + [('severity', '=', 'critical')]),
            'sc_loc_ids':     sc_loc_ids,
        }

    # ── Widget OFs con pestañas ──────────────────────────────────────────────

    @api.model
    def get_mo_widget_data(self, date_from, date_to, warehouse_id=None, sort_field=None, sort_dir='asc', page=1, page_size=50, states=None, search=None):
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
        :param search: str|None — filtro de texto sobre nombre de OF, producto u origen.
        :returns: dict con:
                  - kpis (dict): total, in_progress, delayed, reschedule, done, partial.
                  - mos (list[dict]): registros de la página con campos id, name, product, qty,
                    date_finished, state, delayed, reschedule, pending_delivery.
        """
        if warehouse_id:
            allowed_ids = self._get_allowed_wh_ids()
            if allowed_ids is not None and int(warehouse_id) not in allowed_ids:
                raise AccessError(_("Acceso denegado al depósito seleccionado"))

        first_day = _local_to_utc(self.env, date_from)
        last_day  = _local_to_utc(self.env, date_to, end_of_day=True)

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _MO_FIELD = {
            'name': 'name', 'product': 'product_id', 'qty': 'product_qty',
            'date_finished': 'date_finished', 'state': 'state',
            'delayed': 'date_finished', 'reschedule': 'x_reschedule_needed',
        }
        mo_f     = _MO_FIELD.get(sort_field, 'date_finished')
        mo_order = f'{mo_f} {_sd}'

        no_sc = no_subcontract_domain(self.env)
        wh_mo = ([('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._get_wh_domains().mo) + [('company_id', '=', self.env.company.id)]
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

        if search:
            _s = search.strip().lower()
            mos = mos.filtered(
                lambda m: _s in (m.name or '').lower()
                or _s in (m.product_id.display_name or '').lower()
            )

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
                ('company_id', '=', self.env.company.id),
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
        if warehouse_id:
            allowed_ids = self._get_allowed_wh_ids()
            if allowed_ids is not None and int(warehouse_id) not in allowed_ids:
                raise AccessError(_("Acceso denegado al depósito seleccionado"))

        now   = fields.Datetime.now()
        MO    = self.env['mrp.production']
        no_sc = no_subcontract_domain(self.env)
        wh_mo = ([('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._get_wh_domains().mo) + [('company_id', '=', self.env.company.id)]
        dFrom = fields.Datetime.to_string(_local_to_utc(self.env, date_from))
        dTo   = fields.Datetime.to_string(_local_to_utc(self.env, date_to, end_of_day=True))
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
            'mode':        mode,
        }

    @api.model
    def _comparison_unit_weights(self, product_ids, mode):
        """Peso por unidad de cada producto para ponderar el cumplimiento del
        comparativo, según el modo elegido en Ajustes.

        - qty: 1 (suma de cantidades, como el criterio histórico).
        - sale_price / cost: precio de venta o costo estándar del artículo.
        - wc_hours: tiempo estándar por unidad de la ruta de la BoM (horas):
          Σ tiempo de las operaciones ÷ cantidad de la BoM ÷ 60.

        :returns: (weights, missing) — weights {product_id: peso}; missing =
                  cantidad de productos cuyo peso es 0 porque falta el dato que
                  el modo necesita (precio/costo/ruta), para avisarlo en el panel.
        """
        product_ids = list(product_ids)
        if not product_ids:
            return {}, 0
        if mode == 'qty':
            return {pid: 1.0 for pid in product_ids}, 0
        products = self.env['product.product'].browse(product_ids)
        weights, missing = {}, 0
        if mode in ('sale_price', 'cost'):
            field = 'list_price' if mode == 'sale_price' else 'standard_price'
            for p in products:
                w = p[field] or 0.0
                weights[p.id] = w
                if w <= 0:
                    missing += 1
            return weights, missing
        if mode == 'wc_hours':
            try:
                bom_by_product = self.env['mrp.bom']._bom_find(products)
            except Exception:
                bom_by_product = {p: p.bom_ids[:1] for p in products}
            for p in products:
                bom = bom_by_product.get(p)
                w = 0.0
                if bom and bom.operation_ids and (bom.product_qty or 0.0) > 0:
                    mins = sum((getattr(op, 'time_cycle', 0.0) or 0.0)
                               for op in bom.operation_ids)
                    w = (mins / bom.product_qty) / 60.0  # horas por unidad
                weights[p.id] = w
                if w <= 0:
                    missing += 1
            return weights, missing
        return {pid: 1.0 for pid in product_ids}, 0

    @api.model
    def get_comparison_data(self, date_from, date_to, warehouse_id=None, page=1, page_size=50, sort_field=None, sort_dir='desc', search=None, tag_ids=None, product_type_ids=None, shift_ids=None):
        """
        Retorna la comparativa producido vs. programado agrupada por producto para el rango dado.

        :param date_from: str 'YYYY-MM-DD', inicio del rango.
        :param date_to: str 'YYYY-MM-DD', fin del rango.
        :param warehouse_id: int|None — ID del almacén a filtrar; None para todos los permitidos.
        :param page: int — página a devolver (base 1).
        :param page_size: int — registros por página (default 50, máx. 200).
        :param sort_field: str|None — 'product', 'planned_qty', 'produced_qty' o 'pct';
                           None ordena por planned_qty desc.
        :param sort_dir: 'asc' o 'desc' (default 'desc').
        :param search: str|None — filtro de texto sobre el nombre del producto.
        :returns: dict con:
                  - kpis (dict): planned (float), produced (float), pct (float|None, % de
                    cumplimiento), ofs_done (int), desvio (float, planificado − producido)
                    y ofs_in_progress (int, OFs en estado 'progress').
                  - items (list[dict], página solicitada): product_id, product, uom,
                    planned_qty, produced_qty, pct por producto.
                  - total (int): cantidad de productos tras filtrar (para paginar).
                  - mo_mode (str): modo de fechas usado (comparison_date_mode de config).
        """
        if warehouse_id:
            allowed_ids = self._get_allowed_wh_ids()
            if allowed_ids is not None and int(warehouse_id) not in allowed_ids:
                raise AccessError(_("Acceso denegado al depósito seleccionado"))

        first_day = _local_to_utc(self.env, date_from)
        last_day  = _local_to_utc(self.env, date_to, end_of_day=True)

        no_sc = no_subcontract_domain(self.env)
        wh_mo = ([('picking_type_id.warehouse_id', '=', int(warehouse_id))] if warehouse_id else self._get_wh_domains().mo) + [('company_id', '=', self.env.company.id)]
        # Filtro de sector (tag de CT) para el Análisis de producción; None en el
        # panel principal ⇒ no altera su comportamiento.
        if tag_ids:
            wh_mo = wh_mo + [('workorder_ids.workcenter_id.tag_ids', 'in', list(tag_ids))]
        if product_type_ids:
            wh_mo = wh_mo + [('product_id.product_tmpl_id.x_product_type_ids', 'in', list(product_type_ids))]

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

        if shift_ids:
            all_mos = self._pa_shift_filter_mos(all_mos, shift_ids)

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
                elif mo_end and first_day <= mo_end <= last_day:
                    # Sin fecha de inicio válida: fallback a la fecha de cierre (igual que el
                    # forecast). Se atribuye la cantidad completa solo si el cierre cae en el período.
                    planned_qty = mo.product_qty
                else:
                    planned_qty = 0.0
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
                        'uom_rounding': mo.product_uom_id.rounding or 0.01,
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
                        'uom_rounding': mo.product_uom_id.rounding or 0.01,
                        'planned_qty':  0.0,
                        'produced_qty': 0.0,
                    }
                product_data[pid]['planned_qty']  += mo.product_qty
                product_data[pid]['produced_qty'] += mo.qty_produced

        items = sorted(product_data.values(), key=lambda x: x['planned_qty'], reverse=True)
        force_integer = bool(cfg and cfg.comparison_force_integer and mode == 'proportional')
        for item in items:
            # pct = None señala "sin plan / sobreproducción": se produjo sin cantidad
            # programada, caso en que un 0% sería engañoso. El frontend lo muestra como "s/plan".
            if item['planned_qty'] > 0:
                item['pct'] = round(item['produced_qty'] / item['planned_qty'] * 100, 1)
            elif item['produced_qty'] > 0:
                item['pct'] = None
            else:
                item['pct'] = 0.0
            # Redondeo según la precisión de la UdM del producto: en unidades queda
            # entero, en kg/l conserva los decimales de la unidad. Relevante en modo
            # proporcional, donde el prorrateo por duración genera fracciones.
            # Con comparison_force_integer activo (solo modo proporcional) se fuerza
            # entero sin importar la UdM — presentación del tablero, no toca las OFs.
            if force_integer:
                rounding = 1.0
                item.pop('uom_rounding', None)
            else:
                rounding = item.pop('uom_rounding', 0.01)
            item['planned_qty']  = round(float_round(item['planned_qty'],  precision_rounding=rounding), 2)
            item['produced_qty'] = round(float_round(item['produced_qty'], precision_rounding=rounding), 2)

        # ── KPI global ponderado (representativo del mix) ────────────────────
        # Ponderación por cantidad / valor / horas según Ajustes, con tope al
        # 100% por producto opcional (la sobreproducción de uno no compensa el
        # faltante de otro). El conteo "en target" es mix-justo: cada producto
        # cuenta una vez, sin ponderar.
        weight_mode = (cfg.comparison_weight if cfg else None) or 'cost'
        fill_cap    = bool(cfg.comparison_fill_cap) if cfg else True
        green       = (cfg.comparison_pct_green if cfg else 0) or 90
        weights, excluded = self._comparison_unit_weights(
            [x['product_id'] for x in items], weight_mode)

        wp = wprod = wprod_cap = w_abs_dev = 0.0
        on_target = planned_products = 0
        for x in items:
            w  = weights.get(x['product_id'], 0.0)
            pl = x['planned_qty']
            pr = x['produced_qty']
            wp        += pl * w
            wprod     += pr * w
            wprod_cap += min(pr, pl) * w
            w_abs_dev += abs(pr - pl) * w
            if pl > 0:
                planned_products += 1
                if pr / pl * 100 >= green:
                    on_target += 1
        num = wprod_cap if fill_cap else wprod
        if wp > 0:
            pct = round(num / wp * 100, 1)
        elif wprod > 0:
            pct = None   # sin plan / sobreproducción a nivel total
        else:
            pct = 0.0
        total_planned   = wp
        total_produced  = wprod
        desvio          = round(wp - wprod, 2)
        accuracy_plan   = round(100 - w_abs_dev / wp * 100, 1) if wp > 0 else None
        bias_plan       = round((wprod - wp) / wp * 100, 1) if wp > 0 else None
        accuracy_method = (cfg.prod_plan_accuracy_method if cfg else None) or 'accuracy'
        ofs_in_progress = sum(1 for mo in all_mos if mo.state == 'progress')

        if search:
            _s = search.strip().lower()
            items = [x for x in items if _s in (x.get('product') or '').lower()]

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
                'planned':         round(total_planned,  2),
                'produced':        round(total_produced, 2),
                'pct_green':       green,
                'pct_warn':        (cfg.comparison_pct_warn if cfg else 0) or 50,
                'pct':             pct,
                'ofs_done':        ofs_done,
                'desvio':           desvio,
                'accuracy_plan':    accuracy_plan,
                'bias_plan':        bias_plan,
                'accuracy_method':  accuracy_method,
                'ofs_in_progress':  ofs_in_progress,
                'weight_mode':      weight_mode,
                'fill_cap':         fill_cap,
                'on_target':       on_target,
                'planned_products': planned_products,
                'excluded':        excluded,
            },
            'items':         items[offset:offset + page_size],
            'total':         total,
            'mo_mode':       mode,
        }

