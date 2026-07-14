"""
Módulo: mrp_partner_category.py
Modelo: extensión de mrp.reschedule.config

Clasificación ABC/RFM automática de artículos de venta, proveedores y clientes.

Responsabilidades:
- Asignar categorías A–E a product.template mediante distintos métodos de venta
  (demanda absoluta, participación de mercado, rotación de inventario).
- Asignar categorías A–E a res.partner (proveedores) según volumen, frecuencia,
  RFM, porcentaje de entregas a tiempo, varianza de precio o calidad de cantidad.
- Asignar categorías A–E a res.partner (clientes) según volumen, frecuencia o RFM.
- Exponer métodos de cron para la ejecución programada de cada clasificación.

Relacionado con:
- mrp.reschedule.config: modelo base que se extiende; provee la configuración de
  umbrales Pareto (abc_pct_a/b/c/d), métodos y horizontes temporales.
- product.template: recibe el campo x_sale_category con la categoría calculada.
- res.partner: recibe x_supplier_category y x_customer_category.
- stock.move.line / stock.picking / purchase.order / sale.order: fuentes de datos
  para los distintos métodos de clasificación.
"""
import logging
from datetime import date, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .mrp_abc_helpers import _abc_thresholds, _assign_abc_pareto, _assign_abc_pareto_lower

_logger = logging.getLogger(__name__)


class MrpPartnerCategory(models.Model):
    """
    Extensión de mrp.reschedule.config que agrega la clasificación ABC/RFM
    para artículos vendibles, proveedores y clientes.

    No define campos propios; toda la lógica se apoya en los campos de configuración
    ya declarados en mrp.reschedule.config (abc_pct_a/b/c/d, sale_cat_mode,
    supplier_cat_method, customer_cat_method, etc.).
    """

    _inherit = 'mrp.reschedule.config'

    def action_auto_assign_sale_categories(self):
        """
        Asigna categorías de venta A–E a todos los productos con sale_ok=True.

        Soporta tres modos configurables en sale_cat_mode:
        - 'demand': umbrales absolutos de cantidad mensual promedio demandada
          (unidades en órdenes de venta confirmadas del período).
        - 'share': Pareto acumulado sobre unidades entregadas (units) o valor (pxq = precio × cantidad).
        - 'automatic' (por defecto): días de cobertura usando stock promedio del período
          dividido por promedio mensual de entregas. Menor cobertura → categoría A.

        El horizonte de análisis es sale_cat_lookback_months (por defecto 3 meses).

        Requiere permiso de Administrador: escribe en product.template.x_sale_category.

        :returns: dict ir.actions.client con notificación de éxito.
        :raises UserError: si el usuario no tiene permisos de administrador.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
        config = self.search([], limit=1)
        if not config:
            return

        months   = config.sale_cat_lookback_months or 3
        end      = date.today()
        start    = end - timedelta(days=months * 30)
        start_dt = fields.Datetime.to_datetime(str(start))
        end_dt   = fields.Datetime.to_datetime(str(end))

        # ── Entregas outgoing del período (para modos rotation y share) ───────
        del_groups = self.env['stock.move.line'].read_group([
            ('state', '=', 'done'),
            ('picking_id.picking_type_code', '=', 'outgoing'),
            ('date', '>=', start_dt),
            ('date', '<=', end_dt),
            ('product_id', '!=', False),
        ], ['product_id', 'quantity:sum'], ['product_id'])
        del_by_pid = {g['product_id'][0]: (g['quantity'] or 0.0)
                      for g in del_groups if g['product_id']}

        # ── Demanda OVs confirmadas del período (para modo demand) ────────────
        so_groups = self.env['sale.order.line'].sudo().read_group([
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', str(start)),
            ('order_id.date_order', '<=', str(end)),
            ('product_id', '!=', False),
        ], ['product_id', 'product_uom_qty:sum'], ['product_id'])
        demand_by_pid = {g['product_id'][0]: (g['product_uom_qty'] or 0.0)
                         for g in so_groups if g['product_id']}

        templates = self.env['product.template'].search([('sale_ok', '=', True)])
        updated   = 0

        # Agrega cantidades por variante a nivel de plantilla
        del_by_tmpl    = {}
        demand_by_tmpl = {}
        for tmpl in templates:
            for v in tmpl.product_variant_ids:
                del_by_tmpl[tmpl.id]    = del_by_tmpl.get(tmpl.id,    0.0) + del_by_pid.get(v.id,    0.0)
                demand_by_tmpl[tmpl.id] = demand_by_tmpl.get(tmpl.id, 0.0) + demand_by_pid.get(v.id, 0.0)

        if config.sale_cat_mode == 'demand':
            a_q = config.sale_cat_demand_a_qty
            b_q = config.sale_cat_demand_b_qty
            c_q = config.sale_cat_demand_c_qty
            d_q = config.sale_cat_demand_d_qty
            for tmpl in templates:
                avg_monthly = demand_by_tmpl.get(tmpl.id, 0.0) / months
                if   avg_monthly >= a_q: cat = 'A'
                elif avg_monthly >= b_q: cat = 'B'
                elif avg_monthly >= c_q: cat = 'C'
                elif avg_monthly >= d_q: cat = 'D'
                else:                    cat = 'E'
                tmpl.x_sale_category = cat
                updated += 1

        elif config.sale_cat_mode == 'share':
            metric = config.sale_cat_share_metric or 'units'
            a_pct  = (config.sale_cat_share_a_pct or 50.0) / 100.0
            b_pct  = (config.sale_cat_share_b_pct or 80.0) / 100.0
            c_pct  = (config.sale_cat_share_c_pct or 95.0) / 100.0
            d_pct  = (config.sale_cat_share_d_pct or 99.0) / 100.0

            tmpl_value = {}
            for tmpl in templates:
                qty = del_by_tmpl.get(tmpl.id, 0.0)
                tmpl_value[tmpl.id] = qty * (tmpl.list_price or 0.0) if metric == 'pxq' else qty

            total = sum(tmpl_value.values())
            if total <= 0:
                for tmpl in templates:
                    tmpl.x_sale_category = 'E'
                    updated += 1
            else:
                sorted_tmpls = sorted(templates, key=lambda t: tmpl_value.get(t.id, 0.0), reverse=True)
                cumulative = 0.0
                for tmpl in sorted_tmpls:
                    cumulative += tmpl_value.get(tmpl.id, 0.0) / total
                    if   cumulative <= a_pct: cat = 'A'
                    elif cumulative <= b_pct: cat = 'B'
                    elif cumulative <= c_pct: cat = 'C'
                    elif cumulative <= d_pct: cat = 'D'
                    else:                     cat = 'E'
                    tmpl.x_sale_category = cat
                    updated += 1

        else:  # automatic (rotation) — usa stock promedio del período
            a_d = config.sale_cat_a_days
            b_d = config.sale_cat_b_days
            c_d = config.sale_cat_c_days
            d_d = config.sale_cat_d_days

            # Stock actual (snapshot al cierre del período)
            quants = self.env['stock.quant'].read_group(
                [('location_id.usage', '=', 'internal'), ('product_id', '!=', False)],
                ['product_id', 'quantity:sum'],
                ['product_id'],
            )
            stock_now_by_pid = {g['product_id'][0]: (g['quantity'] or 0.0) for g in quants}

            # Ingresos del período para reconstruir stock de inicio
            in_groups = self.env['stock.move.line'].read_group([
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('date', '>=', start_dt),
                ('date', '<=', end_dt),
                ('product_id', '!=', False),
            ], ['product_id', 'quantity:sum'], ['product_id'])
            qty_in_pid = {g['product_id'][0]: (g['quantity'] or 0.0)
                          for g in in_groups if g['product_id']}

            for tmpl in templates:
                stock_now   = sum(stock_now_by_pid.get(v.id, 0.0) for v in tmpl.product_variant_ids)
                qty_in      = sum(qty_in_pid.get(v.id,        0.0) for v in tmpl.product_variant_ids)
                qty_out     = sum(del_by_pid.get(v.id,         0.0) for v in tmpl.product_variant_ids)
                # Deshace los movimientos del período para obtener stock al inicio
                stock_start = max(0.0, stock_now - qty_in + qty_out)
                avg_stock   = (stock_start + stock_now) / 2.0

                avg_monthly_base = demand_by_tmpl.get(tmpl.id, 0.0) \
                    if config.sale_cat_rotation_source == 'demand' \
                    else del_by_tmpl.get(tmpl.id, 0.0)
                avg_monthly = avg_monthly_base / months
                if avg_monthly <= 0:
                    cat = 'E'
                else:
                    rot = round(avg_stock / avg_monthly * 30)
                    if   rot <= a_d: cat = 'A'
                    elif rot <= b_d: cat = 'B'
                    elif rot <= c_d: cat = 'C'
                    elif rot <= d_d: cat = 'D'
                    else:            cat = 'E'
                tmpl.x_sale_category = cat
                updated += 1

        return {
            'type':   'ir.actions.client',
            'tag':    'display_notification',
            'params': {
                'title':   'Categorías asignadas',
                'message': f'{updated} artículos actualizados.',
                'type':    'success',
            },
        }

    @api.model
    def _cron_auto_assign_sale_categories(self):
        """Punto de entrada del cron para recategorización automática de artículos de venta."""
        _logger.info('MRP Planner cron: inicio actualización categorías de venta')
        config = self.search([], limit=1)
        if not config or not config.sale_cat_auto_cron or config.sale_cat_mode == 'manual':
            _logger.info('MRP Planner cron: categorías de venta omitidas (desactivado o modo manual)')
            return
        config.action_auto_assign_sale_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de venta')

    def action_compute_supplier_categories(self):
        """
        Asigna categorías A–E a todos los proveedores activos (supplier_rank > 0).

        Soporta los siguientes métodos configurables en supplier_cat_method:
        - 'abc_volume': Pareto descendente sobre monto total de compras (12 meses).
        - 'abc_frequency': Pareto descendente sobre cantidad de órdenes de compra.
        - 'abc_rfm': Puntuación RFM (Recency, Frequency, Monetary) con score 3–9;
          A ≥ 8, B ≥ 6, C ≥ 4, D ≥ 3, E < 3.
        - 'abc_delivery_pct': Pareto descendente sobre % de recepciones a tiempo.
        - 'abc_price_var': Pareto ascendente sobre varianza promedio de precio vs. costo
          estándar (menor varianza = mejor proveedor = A).
        - 'abc_quality_qty': Pareto descendente sobre % de líneas recibidas con cantidad exacta.
        - 'abc_quality_returns': Pareto ascendente sobre cantidad de devoluciones al proveedor.
        - 'abc_quality_combo': Pareto descendente sobre promedio de % entregas a tiempo
          y % cantidad exacta (composite score).

        El horizonte de análisis es siempre los últimos 365 días desde hoy.

        Requiere permiso de Administrador: escribe en res.partner.x_supplier_category.

        :returns: dict ir.actions.client con notificación de éxito o advertencia (modo manual).
        :raises UserError: si el usuario no tiene permisos de administrador.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
        config = self.search([], limit=1)
        if not config or config.supplier_cat_method == 'manual':
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Modo manual', 'message': 'Las categorías en modo manual se asignan desde la ficha del proveedor.', 'type': 'warning'}}

        start = date.today() - timedelta(days=365)
        suppliers = self.env['res.partner'].search([('supplier_rank', '>', 0), ('active', '=', True)])
        updated = 0

        if config.supplier_cat_method in ('abc_volume', 'abc_frequency'):
            groups = self.env['purchase.order'].read_group(
                [('state', 'in', ('purchase', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count'],
                ['partner_id'],
            )
            if config.supplier_cat_method == 'abc_volume':
                value_by_id = {g['partner_id'][0]: g['amount_total'] for g in groups}
            else:
                value_by_id = {g['partner_id'][0]: g['partner_id_count'] for g in groups}
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_rfm':
            start_dt = fields.Datetime.to_datetime(str(start))
            now_dt   = fields.Datetime.now()
            groups = self.env['purchase.order'].read_group(
                [('state', 'in', ('purchase', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count', 'date_order:max'],
                ['partner_id'],
            )
            data = {g['partner_id'][0]: {
                'M': g['amount_total'] or 0.0,
                'F': g['partner_id_count'] or 0,
                'R': (now_dt - g['date_order']).days if g.get('date_order') else 999,
            } for g in groups}

            # Puntúa cada dimensión RFM en 1–3: recencia (R), frecuencia (F) y monto (M).
            # El score total (3–9) se traduce luego a categoría A–E.
            for p in suppliers:
                d = data.get(p.id)
                if not d:
                    p.x_supplier_category = 'E'
                    updated += 1
                    continue
                # R < 30 días: compra reciente (alta recencia); R < 90: moderada; ≥ 90: baja.
                r_score = 3 if d['R'] < 30 else (2 if d['R'] < 90 else 1)
                # F > 10 órdenes: alta frecuencia; F ≥ 3: moderada; < 3: baja.
                f_score = 3 if d['F'] > 10 else (2 if d['F'] >= 3 else 1)
                # M se puntúa respecto a los terciles del universo, calculados más abajo.
                data[p.id]['r_score'] = r_score
                data[p.id]['f_score'] = f_score

            m_vals = sorted([d['M'] for d in data.values() if d.get('M', 0) > 0])
            # Percentil 33 y 66 del monto para dividir en tres bandas de forma dinámica.
            m_p33 = m_vals[len(m_vals) // 3] if m_vals else 0
            m_p66 = m_vals[2 * len(m_vals) // 3] if m_vals else 0

            for p in suppliers:
                d = data.get(p.id)
                if not d or p.x_supplier_category == 'E':
                    continue
                m_score = 3 if d['M'] >= m_p66 else (2 if d['M'] >= m_p33 else 1)
                total_score = d['r_score'] + d['f_score'] + m_score
                # Score máximo = 9 (3+3+3); mínimo significativo = 3 (1+1+1).
                if   total_score >= 8: cat = 'A'
                elif total_score >= 6: cat = 'B'
                elif total_score >= 4: cat = 'C'
                elif total_score >= 3: cat = 'D'
                else:                  cat = 'E'
                p.x_supplier_category = cat
                updated += 1

        elif config.supplier_cat_method == 'abc_delivery_pct':
            picks = self.env['stock.picking'].search([
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'incoming'),
                ('purchase_id.partner_id', 'in', suppliers.ids),
                ('purchase_id.date_order', '>=', str(start)),
            ])
            pct_data = {}
            for pick in picks:
                pid = pick.purchase_id.partner_id.id
                if pid not in pct_data:
                    pct_data[pid] = {'total': 0, 'on_time': 0}
                pct_data[pid]['total'] += 1
                if pick.scheduled_date and pick.date_done and pick.date_done <= pick.scheduled_date:
                    pct_data[pid]['on_time'] += 1
            value_by_id = {
                pid: (d['on_time'] / d['total'] * 100) if d['total'] > 0 else 0.0
                for pid, d in pct_data.items()
            }
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_price_var':
            po_lines = self.env['purchase.order.line'].search([
                ('order_id.state', 'in', ('purchase', 'done')),
                ('order_id.date_order', '>=', str(start)),
                ('order_id.partner_id', 'in', suppliers.ids),
                ('product_id', '!=', False),
            ])
            prod_ids     = list({ln.product_id.id for ln in po_lines})
            price_method = config.supplier_price_var_method or 'standard'
            std_map = {r['id']: r['standard_price']
                       for r in self.env['product.product'].search_read(
                           [('id', 'in', prod_ids)], ['id', 'standard_price']
                       )} if prod_ids else {}
            si_tmpl_map   = {}
            prod_tmpl_map = {}
            if price_method == 'pricelist' and prod_ids:
                prod_tmpl_map = {r['id']: r['product_tmpl_id'][0]
                                 for r in self.env['product.product'].sudo().search_read(
                                     [('id', 'in', prod_ids)], ['id', 'product_tmpl_id'])}
                all_tmpl_ids = list(set(prod_tmpl_map.values()))
                for si in self.env['product.supplierinfo'].sudo().search_read(
                    [('partner_id', 'in', suppliers.ids), ('product_tmpl_id', 'in', all_tmpl_ids)],
                    ['partner_id', 'product_tmpl_id', 'price'],
                ):
                    if not si['partner_id'] or not si['product_tmpl_id']:
                        continue
                    key = (si['partner_id'][0], si['product_tmpl_id'][0])
                    if key not in si_tmpl_map or si['price'] < si_tmpl_map[key]:
                        si_tmpl_map[key] = si['price']
            pvar_data = {}
            for ln in po_lines:
                pid     = ln.order_id.partner_id.id
                prod_id = ln.product_id.id
                if price_method == 'pricelist':
                    tmpl_id = prod_tmpl_map.get(prod_id)
                    ref = si_tmpl_map.get((pid, tmpl_id), 0.0) if tmpl_id else 0.0
                else:
                    ref = std_map.get(prod_id, 0.0)
                if ref > 0 and ln.price_unit > 0:
                    var = abs((ln.price_unit - ref) / ref * 100)
                    if pid not in pvar_data:
                        pvar_data[pid] = {'sum': 0.0, 'count': 0}
                    pvar_data[pid]['sum'] += var
                    pvar_data[pid]['count'] += 1
            avg_var_by_id = {
                pid: d['sum'] / d['count'] if d['count'] > 0 else None
                for pid, d in pvar_data.items()
            }
            _assign_abc_pareto_lower(suppliers, avg_var_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_qty':
            moves = self.env['stock.move'].search([
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('picking_id.purchase_id.partner_id', 'in', suppliers.ids),
                ('picking_id.purchase_id.date_order', '>=', str(start)),
            ])
            qty_data = {}
            for mv in moves:
                pid = mv.picking_id.purchase_id.partner_id.id
                if pid not in qty_data:
                    qty_data[pid] = {'total': 0, 'exact': 0}
                qty_data[pid]['total'] += 1
                if abs(mv.quantity - mv.product_uom_qty) < 0.001:
                    qty_data[pid]['exact'] += 1
            value_by_id = {
                pid: (d['exact'] / d['total'] * 100) if d['total'] > 0 else 0.0
                for pid, d in qty_data.items()
            }
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_returns':
            returns_by_partner = {}
            # Verificación en tiempo de ejecución: el campo return_id existe solo si está
            # instalado el módulo de devoluciones de Odoo (stock_picking_return o similar).
            _has_return_id = 'return_id' in self.env['stock.picking']._fields
            if _has_return_id:
                ret_picks = self.env['stock.picking'].search([
                    ('state', '=', 'done'),
                    ('return_id', '!=', False),
                    ('return_id.purchase_id', '!=', False),
                    ('return_id.purchase_id.partner_id', 'in', suppliers.ids),
                    ('return_id.purchase_id.date_order', '>=', str(start)),
                ])
                for pick in ret_picks:
                    pid = pick.return_id.purchase_id.partner_id.id
                    returns_by_partner[pid] = returns_by_partner.get(pid, 0) + 1
            _assign_abc_pareto_lower(suppliers, returns_by_partner, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        elif config.supplier_cat_method == 'abc_quality_combo':
            picks = self.env['stock.picking'].search([
                ('state', '=', 'done'),
                ('picking_type_code', '=', 'incoming'),
                ('purchase_id.partner_id', 'in', suppliers.ids),
                ('purchase_id.date_order', '>=', str(start)),
            ])
            combo_data = {}
            for pick in picks:
                pid = pick.purchase_id.partner_id.id
                if pid not in combo_data:
                    combo_data[pid] = {'total': 0, 'on_time': 0}
                combo_data[pid]['total'] += 1
                if pick.scheduled_date and pick.date_done and pick.date_done <= pick.scheduled_date:
                    combo_data[pid]['on_time'] += 1
            moves = self.env['stock.move'].search([
                ('state', '=', 'done'),
                ('picking_id.picking_type_code', '=', 'incoming'),
                ('picking_id.purchase_id.partner_id', 'in', suppliers.ids),
                ('picking_id.purchase_id.date_order', '>=', str(start)),
            ])
            qty_data = {}
            for mv in moves:
                pid = mv.picking_id.purchase_id.partner_id.id
                if pid not in qty_data:
                    qty_data[pid] = {'total': 0, 'exact': 0}
                qty_data[pid]['total'] += 1
                if abs(mv.quantity - mv.product_uom_qty) < 0.001:
                    qty_data[pid]['exact'] += 1
            value_by_id = {}
            for p in suppliers:
                on_t = combo_data.get(p.id, {})
                qt   = qty_data.get(p.id, {})
                on_time_pct = (on_t.get('on_time', 0) / on_t['total'] * 100) if on_t.get('total') else None
                qty_pct     = (qt.get('exact', 0) / qt['total'] * 100) if qt.get('total') else None
                scores = [s for s in [on_time_pct, qty_pct] if s is not None]
                if scores:
                    value_by_id[p.id] = sum(scores) / len(scores)
            _assign_abc_pareto(suppliers, value_by_id, 'x_supplier_category', _abc_thresholds(config))
            updated = len(suppliers)

        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Categorías de proveedor asignadas',
                           'message': f'{updated} proveedores actualizados.', 'type': 'success'}}

    @api.model
    def _cron_compute_supplier_categories(self):
        """Punto de entrada del cron para recategorización automática de proveedores."""
        _logger.info('MRP Planner cron: inicio actualización categorías de proveedor')
        config = self.search([], limit=1)
        if not config or not config.enable_supplier_categories or config.supplier_cat_method == 'manual':
            _logger.info('MRP Planner cron: categorías de proveedor omitidas (desactivado o modo manual)')
            return
        config.action_compute_supplier_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de proveedor')

    def action_compute_customer_categories(self):
        """
        Asigna categorías A–E a todos los clientes activos (customer_rank > 0).

        Soporta los siguientes métodos configurables en customer_cat_method:
        - 'abc_volume': Pareto descendente sobre monto total de ventas (12 meses).
        - 'abc_frequency': Pareto descendente sobre cantidad de órdenes de venta.
        - 'abc_rfm': Puntuación RFM (Recency, Frequency, Monetary) idéntica a la
          de proveedores pero usando sale.order en lugar de purchase.order.
          Score total 3–9: A ≥ 8, B ≥ 6, C ≥ 4, D ≥ 3, E < 3.

        El horizonte de análisis es siempre los últimos 365 días desde hoy.

        Requiere permiso de Administrador: escribe en res.partner.x_customer_category.

        :returns: dict ir.actions.client con notificación de éxito o advertencia (modo manual).
        :raises UserError: si el usuario no tiene permisos de administrador.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_('Esta acción está restringida a administradores del planificador.'))
        config = self.search([], limit=1)
        if not config or config.customer_cat_method == 'manual':
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Modo manual', 'message': 'Las categorías en modo manual se asignan desde la ficha del cliente.', 'type': 'warning'}}

        start = date.today() - timedelta(days=365)
        customers = self.env['res.partner'].search([('customer_rank', '>', 0), ('active', '=', True)])
        updated = 0

        if config.customer_cat_method in ('abc_volume', 'abc_frequency'):
            groups = self.env['sale.order'].read_group(
                [('state', 'in', ('sale', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count'],
                ['partner_id'],
            )
            if config.customer_cat_method == 'abc_volume':
                value_by_id = {g['partner_id'][0]: g['amount_total'] for g in groups}
            else:
                value_by_id = {g['partner_id'][0]: g['partner_id_count'] for g in groups}
            _assign_abc_pareto(customers, value_by_id, 'x_customer_category', _abc_thresholds(config))
            updated = len(customers)

        elif config.customer_cat_method == 'abc_rfm':
            start_dt = fields.Datetime.to_datetime(str(start))
            now_dt   = fields.Datetime.now()
            groups = self.env['sale.order'].read_group(
                [('state', 'in', ('sale', 'done')), ('date_order', '>=', str(start))],
                ['partner_id', 'amount_total:sum', 'id:count', 'date_order:max'],
                ['partner_id'],
            )
            data = {g['partner_id'][0]: {
                'M': g['amount_total'] or 0.0,
                'F': g['partner_id_count'] or 0,
                'R': (now_dt - g['date_order']).days if g.get('date_order') else 999,
            } for g in groups}

            # Puntúa cada dimensión RFM en 1–3: recencia (R), frecuencia (F) y monto (M).
            for p in customers:
                d = data.get(p.id)
                if not d:
                    p.x_customer_category = 'E'
                    updated += 1
                    continue
                # R < 30 días: compra reciente (alta recencia); R < 90: moderada; ≥ 90: baja.
                r_score = 3 if d['R'] < 30 else (2 if d['R'] < 90 else 1)
                # F > 10 órdenes: alta frecuencia; F ≥ 3: moderada; < 3: baja.
                f_score = 3 if d['F'] > 10 else (2 if d['F'] >= 3 else 1)
                data[p.id]['r_score'] = r_score
                data[p.id]['f_score'] = f_score

            m_vals = sorted([d['M'] for d in data.values() if d.get('M', 0) > 0])
            # Percentil 33 y 66 del monto para dividir en tres bandas de forma dinámica.
            m_p33 = m_vals[len(m_vals) // 3] if m_vals else 0
            m_p66 = m_vals[2 * len(m_vals) // 3] if m_vals else 0

            for p in customers:
                d = data.get(p.id)
                if not d or p.x_customer_category == 'E':
                    continue
                m_score = 3 if d['M'] >= m_p66 else (2 if d['M'] >= m_p33 else 1)
                total_score = d['r_score'] + d['f_score'] + m_score
                # Score máximo = 9 (3+3+3); mínimo significativo = 3 (1+1+1).
                if   total_score >= 8: cat = 'A'
                elif total_score >= 6: cat = 'B'
                elif total_score >= 4: cat = 'C'
                elif total_score >= 3: cat = 'D'
                else:                  cat = 'E'
                p.x_customer_category = cat
                updated += 1

        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Categorías de cliente asignadas',
                           'message': f'{updated} clientes actualizados.', 'type': 'success'}}

    @api.model
    def _cron_compute_customer_categories(self):
        """Punto de entrada del cron para recategorización automática de clientes."""
        _logger.info('MRP Planner cron: inicio actualización categorías de cliente')
        config = self.search([], limit=1)
        if not config or not config.enable_customer_categories or config.customer_cat_method == 'manual':
            _logger.info('MRP Planner cron: categorías de cliente omitidas (desactivado o modo manual)')
            return
        config.action_compute_customer_categories()
        _logger.info('MRP Planner cron: fin actualización categorías de cliente')
