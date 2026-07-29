# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Mixin: cálculos pesados de forecast separados de mrp_planner_dashboard_forecast.py.
Contiene _fc_rotation_data, _fc_build_rows y _fc_no_fc_stats.
"""
from odoo import models, fields


def _cov_days(stock, period_days, demand):
    return round(stock * period_days / demand, 1) if demand > 0 else None


def _cov_months(stock, period_days, demand):
    return round(stock * period_days / demand / 30, 1) if demand > 0 else None


class MrpForecastCalcMixin(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    def _fc_rotation_data(self, all_product_ids_list, rotation_method, dt_from_str, dt_to_str,
                          location_ids=None):
        """
        Consulta los datos de rotación de inventario según el método configurado.
        Retorna un dict con los subdicts necesarios para el cálculo de rot_days/rot_months.

        :param location_ids: list[int] | None — cuando se pasa (filtro de depósito), los
            flujos se miden cruzando la frontera de EXACTAMENTE esas ubicaciones, quedando
            consistente con el snapshot de stock actual. Cuando es None se usa la frontera
            interno/externo a nivel compañía.
        """
        # Roll-back desde el stock actual: en vez de reconstruir el on-hand sumando TODO el
        # historial, se miden solo los flujos que cruzan la frontera del conjunto de
        # ubicaciones DENTRO del período y en la cola (fin del período → hoy). El widget
        # ancla en el stock actual (exacto, de stock.quant) y rueda hacia atrás:
        #   stock_fin    = actual − entradas_cola   + salidas_cola
        #   stock_inicio = stock_fin − entradas_per. + salidas_per.
        qty_in_period  = {}
        qty_out_period = {}
        qty_in_tail    = {}
        qty_out_tail   = {}

        if rotation_method == 'units' and all_product_ids_list:
            try:
                # sudo(): usuario no tiene acceso directo a stock.move; sólo se lee el agregado
                SM = self.env['stock.move'].sudo()
                _sm_base = [
                    ('state', '=', 'done'),
                    ('product_id', 'in', all_product_ids_list),
                    ('company_id', '=', self.env.company.id),
                ]
                if location_ids:
                    # Cruce de la frontera del conjunto de ubicaciones: entradas desde afuera
                    # (+) / salidas hacia afuera (−). Las transferencias internas dentro del
                    # conjunto no cruzan y se excluyen. Consistente con el snapshot de stock.
                    in_dom  = [('location_dest_id', 'in', location_ids),
                               ('location_id', 'not in', location_ids)]
                    out_dom = [('location_id', 'in', location_ids),
                               ('location_dest_id', 'not in', location_ids)]
                else:
                    # Frontera interno/externo a nivel compañía.
                    in_dom  = [('location_dest_id.usage', '=', 'internal'),
                               ('location_id.usage', '!=', 'internal')]
                    out_dom = [('location_id.usage', '=', 'internal'),
                               ('location_dest_id.usage', '!=', 'internal')]

                now_str    = fields.Datetime.to_string(fields.Datetime.now())
                period_dom = [('date', '>=', dt_from_str), ('date', '<=', dt_to_str)]
                tail_dom   = [('date', '>', dt_to_str), ('date', '<=', now_str)]  # vacío si el período termina en el futuro

                def _sum(loc_dom, date_dom, target):
                    for g in SM.read_group(_sm_base + loc_dom + date_dom,
                                           ['product_id', 'product_qty:sum'], ['product_id']):
                        if g['product_id']:
                            target[g['product_id'][0]] = g['product_qty'] or 0.0

                _sum(in_dom,  period_dom, qty_in_period)
                _sum(out_dom, period_dom, qty_out_period)
                _sum(in_dom,  tail_dom,   qty_in_tail)
                _sum(out_dom, tail_dom,   qty_out_tail)
            except Exception:
                pass

        cogs     = {}
        inv_start = {}
        inv_end   = {}
        sales_rev = {}

        if rotation_method in ('cogs', 'sales') and 'stock.valuation.layer' in self.env:
            try:
                # sudo(): usuario no tiene acceso directo a stock.valuation.layer
                SVL = self.env['stock.valuation.layer'].sudo()
                # COGS: capas con valor negativo (salidas) dentro del período
                for g in SVL.read_group([
                    ('product_id', 'in', all_product_ids_list),
                    ('create_date', '>=', dt_from_str),
                    ('create_date', '<=', dt_to_str),
                    ('value', '<', 0),
                    ('company_id', '=', self.env.company.id),
                ], ['product_id', 'value:sum'], ['product_id']):
                    if g['product_id']:
                        cogs[g['product_id'][0]] = -(g['value'] or 0.0)

                for g in SVL.read_group([
                    ('product_id', 'in', all_product_ids_list),
                    ('create_date', '<', dt_from_str),
                    ('company_id', '=', self.env.company.id),
                ], ['product_id', 'value:sum'], ['product_id']):
                    if g['product_id']:
                        inv_start[g['product_id'][0]] = g['value'] or 0.0

                for g in SVL.read_group([
                    ('product_id', 'in', all_product_ids_list),
                    ('create_date', '<=', dt_to_str),
                    ('company_id', '=', self.env.company.id),
                ], ['product_id', 'value:sum'], ['product_id']):
                    if g['product_id']:
                        inv_end[g['product_id'][0]] = g['value'] or 0.0
            except Exception:
                pass

        if rotation_method == 'sales':
            try:
                # sudo(): usuario no tiene acceso directo a sale.order.line
                for g in self.env['sale.order.line'].sudo().read_group([
                    ('order_id.state', 'in', ('sale', 'done')),
                    ('order_id.date_order', '>=', dt_from_str),
                    ('order_id.date_order', '<=', dt_to_str),
                    ('product_id', 'in', all_product_ids_list),
                    ('company_id', '=', self.env.company.id),
                ], ['product_id', 'price_subtotal:sum'], ['product_id']):
                    if g['product_id']:
                        sales_rev[g['product_id'][0]] = g['price_subtotal'] or 0.0
            except Exception:
                pass

        return {
            'qty_in_period':  qty_in_period,
            'qty_out_period': qty_out_period,
            'qty_in_tail':    qty_in_tail,
            'qty_out_tail':   qty_out_tail,
            'cogs':          cogs,
            'inv_start':     inv_start,
            'inv_end':       inv_end,
            'sales_rev':     sales_rev,
        }

    def _fc_build_rows(self, query, cfg, months, n_months, period_days):
        """
        Construye la lista de filas del dashboard a partir de los datos de consulta pre-cargados.
        Retorna la lista `rows` ordenada por nombre de producto.
        """
        fc_data          = query['fc_data']
        mo_data          = query['mo_data']
        del_data         = query['del_data']
        del_by_order_month = query['del_by_order_month']
        so_data          = query['so_data']
        demand_del_data  = query['demand_del_data']
        stock_data       = query['stock_data']
        rotation         = query['rotation']
        all_product_ids  = query['all_product_ids']

        acc_formula            = cfg['acc_formula']
        precision_source       = cfg['precision_source']
        coverage_demand_source = cfg['coverage_demand_source']
        coverage_unit          = cfg['coverage_unit']
        rotation_method        = cfg['rotation_method']
        rotation_unit          = cfg['rotation_unit']

        period_days_rot = n_months * 30

        # Categorías de venta por product.template (batch, un solo SELECT)
        tmpl_ids = [fc_data[pid].get('product_tmpl_id') for pid in all_product_ids
                    if fc_data[pid].get('product_tmpl_id')]
        if tmpl_ids:
            tmpl_info = {}
            _tmpl_rows = self.env['product.template'].browse(tmpl_ids).read(
                ['id', 'x_sale_category', 'categ_id', 'x_product_type_ids', 'list_price']
            )
            _categ_ids = list({r['categ_id'][0] for r in _tmpl_rows if r['categ_id']})
            _categ_names = {c['id']: c['name'] for c in
                            self.env['product.category'].browse(_categ_ids).read(['id', 'name'])}
            _type_ids_all = list({tid for r in _tmpl_rows for tid in (r['x_product_type_ids'] or [])})
            _type_names = {tp['id']: tp['name'] for tp in
                           self.env['x.product.type'].browse(_type_ids_all).read(['id', 'name'])} \
                          if _type_ids_all else {}
            for _tr in _tmpl_rows:
                _categ_id = _tr['categ_id'][0] if _tr['categ_id'] else False
                tmpl_info[_tr['id']] = {
                    'sale_category': _tr.get('x_sale_category') or '',
                    'product_categ': _categ_names.get(_categ_id, '') if _categ_id else '',
                    'product_types': ', '.join(_type_names.get(tid, '') for tid in (_tr['x_product_type_ids'] or [])),
                    'list_price':    round(_tr.get('list_price') or 0.0, 2),
                }
        else:
            tmpl_info = {}

        rows = []
        for pid in all_product_ids:
            pname    = fc_data[pid]['product']
            pid_del  = del_data.get(pid, {})
            pid_so   = so_data.get(pid, {})
            stock_qty = round(stock_data.get(pid, 0.0), 2)
            cells            = []
            tot_fc           = 0.0
            tot_mos          = 0.0
            tot_del          = 0.0
            tot_so           = 0.0
            _mape_acc_sum    = 0.0
            _mape_acc_count  = 0
            _wape_abs_err    = 0.0
            _wmape_abs_err   = 0.0

            for ym in months:
                fc_qty  = fc_data[pid].get(ym, 0.0)
                mo_qty  = mo_data.get(pid, {}).get(ym, 0.0)
                del_qty = pid_del.get(ym, 0.0)
                so_qty  = pid_so.get(ym, 0.0)
                pct            = round(mo_qty  / fc_qty * 100, 1) if fc_qty > 0 else 0.0
                svc_rate       = round(del_qty / so_qty * 100, 1) if so_qty > 0 else None
                dd_qty         = round(demand_del_data.get(pid, {}).get(ym, 0.0), 2)
                dd_svc_rate    = round(dd_qty / so_qty * 100, 1) if so_qty > 0 else None

                actual  = del_qty if precision_source == 'delivery' else so_qty
                abs_err = abs(actual - fc_qty)
                # MAPE: promedio de la precisión por período; solo períodos con real > 0
                # (la APE es indefinida cuando real = 0).
                if actual > 0:
                    _mape_acc_sum   += max(0.0, 100.0 - abs_err / actual * 100)
                    _mape_acc_count += 1
                # WAPE/WMAPE: el error absoluto se acumula sobre TODOS los períodos (incluye meses
                # con real = 0 o forecast = 0); la ponderación la da el denominador global
                # (Σreal para WAPE, Σforecast para WMAPE). Excluir esos meses subestimaba el error.
                _wape_abs_err   += abs_err
                _wmape_abs_err  += abs_err
                if acc_formula in ('mape', 'wape'):
                    fc_acc = round(max(0.0, 100.0 - abs_err / actual * 100), 1) if actual > 0 else None
                elif acc_formula == 'wmape':
                    fc_acc = round(max(0.0, 100.0 - abs_err / fc_qty * 100), 1) if fc_qty > 0 else None
                elif acc_formula == 'bias':
                    fc_acc = round((actual - fc_qty) / fc_qty * 100, 1) if fc_qty > 0 else None
                else:  # simple
                    fc_acc = round(actual / fc_qty * 100, 1) if fc_qty > 0 else None

                demand_gap_pct = round((so_qty - fc_qty) / fc_qty * 100, 1) if fc_qty > 0 else None

                cells.append({
                    'month':              ym,
                    'forecast':           round(fc_qty,  2),
                    'mos':                round(mo_qty,  2),
                    'pct':                pct,
                    'delivered':          round(del_qty, 2),
                    'so_demand':          round(so_qty,  2),
                    'service_rate':       svc_rate,
                    'demand_delivered':   dd_qty,
                    'demand_service_rate': dd_svc_rate,
                    'forecast_acc':       fc_acc,
                    'demand_gap_pct':     demand_gap_pct,
                })
                tot_fc  += fc_qty
                tot_mos += mo_qty
                tot_del += del_qty
                tot_so  += so_qty

            demand_del_qty  = round(sum(demand_del_data.get(pid, {}).values()), 2)
            demand_svc_rate = round(demand_del_qty / tot_so * 100, 1) if tot_so > 0 else None

            tot_pct = round(tot_mos / tot_fc * 100, 1) if tot_fc > 0 else 0.0
            tot_svc = round(tot_del / tot_so * 100, 1) if tot_so > 0 else None
            # El "real" de los totales de precisión respeta la fuente configurada
            # (demanda OV o entregas), igual que las celdas y el KPI global.
            tot_actual = tot_del if precision_source == 'delivery' else tot_so
            if acc_formula == 'mape':
                tot_acc = round(_mape_acc_sum / _mape_acc_count, 1) if _mape_acc_count > 0 else None
            elif acc_formula == 'wape':
                tot_acc = round(max(0.0, 100.0 - _wape_abs_err / tot_actual * 100), 1) if tot_actual > 0 else None
            elif acc_formula == 'wmape':
                tot_acc = round(max(0.0, 100.0 - _wmape_abs_err / tot_fc * 100), 1) if tot_fc > 0 else None
            elif acc_formula == 'bias':
                tot_acc = round((tot_actual - tot_fc) / tot_fc * 100, 1) if tot_fc > 0 else None
            else:
                tot_acc = round(tot_actual / tot_fc * 100, 1) if tot_fc > 0 else None

            rot_months = None
            rot_days   = None
            avg_stock_qty = stock_qty
            if rotation_method == 'units':
                # Roll-back desde el stock actual (exacto, de quants) hacia atrás:
                #   stock_fin    = actual − entradas_cola   + salidas_cola
                #   stock_inicio = stock_fin − entradas_per. + salidas_per.
                stock_end   = stock_qty - rotation['qty_in_tail'].get(pid, 0.0) \
                                        + rotation['qty_out_tail'].get(pid, 0.0)
                stock_start = stock_end - rotation['qty_in_period'].get(pid, 0.0) \
                                        + rotation['qty_out_period'].get(pid, 0.0)
                avg_stock_qty = (max(0.0, stock_start) + max(0.0, stock_end)) / 2.0
                avg_monthly_del = tot_del / n_months
                if avg_monthly_del > 0:
                    rot_months = round(avg_stock_qty / avg_monthly_del, 1)
                    rot_days   = int(round(avg_stock_qty / avg_monthly_del * 30))
            elif rotation_method in ('cogs', 'sales'):
                inv_s   = rotation['inv_start'].get(pid, 0.0)
                inv_e   = rotation['inv_end'].get(pid, 0.0)
                avg_inv = (inv_s + inv_e) / 2.0
                if avg_inv > 0:
                    base = rotation['cogs'].get(pid, 0.0) if rotation_method == 'cogs' \
                           else rotation['sales_rev'].get(pid, 0.0)
                    if base > 0:
                        dio        = period_days_rot * avg_inv / base
                        rot_days   = int(round(dio))
                        rot_months = round(dio / 30.0, 1)

            _demand_for_cov = {'forecast': tot_fc, 'so_demand': tot_so, 'delivered': tot_del}.get(
                coverage_demand_source, tot_fc)

            rows.append({
                'product_id':         pid,
                'product_tmpl_id':    fc_data[pid].get('product_tmpl_id'),
                'product':            pname,
                'cells':              cells,
                'stock_qty':          stock_qty,
                'avg_stock_qty':      round(avg_stock_qty, 2),
                'rotation_days':      rot_days,
                'rotation_months':    rot_months,
                'coverage_days':      _cov_days(stock_qty, period_days, _demand_for_cov),
                'coverage_months':    _cov_months(stock_qty, period_days, _demand_for_cov),
                'total_forecast':     round(tot_fc,  2),
                'total_mos':          round(tot_mos, 2),
                'total_pct':          tot_pct,
                'total_delivered':             round(tot_del, 2),
                'total_so_demand':             round(tot_so,  2),
                'total_service_rate':          tot_svc,
                'total_demand_delivered':      demand_del_qty,
                'total_demand_service_rate':   demand_svc_rate,
                'del_by_order_month':          del_by_order_month.get(pid, {}),
                'total_forecast_acc': tot_acc,
                'demand_gap_pct': round((tot_so - tot_fc) / tot_fc * 100, 1) if tot_fc > 0 else None,
                'acc_all': {
                    'simple': round(tot_actual / tot_fc * 100, 1) if tot_fc > 0 else None,
                    'mape':   round(_mape_acc_sum / _mape_acc_count, 1) if _mape_acc_count > 0 else None,
                    'wape':   round(max(0.0, 100.0 - _wape_abs_err / tot_actual * 100), 1) if tot_actual > 0 else None,
                    'wmape':  round(max(0.0, 100.0 - _wmape_abs_err / tot_fc * 100), 1) if tot_fc > 0 else None,
                    'bias':   round((tot_actual - tot_fc) / tot_fc * 100, 1) if tot_fc > 0 else None,
                },
                'sale_category':      tmpl_info.get(fc_data[pid].get('product_tmpl_id'), {}).get('sale_category', ''),
                'product_categ':      tmpl_info.get(fc_data[pid].get('product_tmpl_id'), {}).get('product_categ', ''),
                'product_types':      tmpl_info.get(fc_data[pid].get('product_tmpl_id'), {}).get('product_types', ''),
                'list_price':         tmpl_info.get(fc_data[pid].get('product_tmpl_id'), {}).get('list_price', 0.0),
                '_mape_acc_sum':      _mape_acc_sum,
                '_mape_acc_count':    _mape_acc_count,
                '_wape_abs_err':      _wape_abs_err,
                '_wmape_abs_err':     _wmape_abs_err,
            })

        rows.sort(key=lambda r: r['product'].lower())
        return rows

    def _fc_no_fc_stats(self, mo_data, all_product_ids, all_product_ids_list, dt_from, dt_to,
                        exclude_services=False):
        """
        Calcula estadísticas de OFs, entregas y demanda para productos SIN línea de forecast.
        Retorna la tupla (mos_no_fc, delivered_no_fc, demand_delivered_no_fc, so_demand_no_fc).

        :param exclude_services: bool — con el toggle de Ajustes activo, la demanda
            sin FC no cuenta líneas de productos de tipo Servicio (que inflan el
            denominador de las tasas sin aportar entregas).
        """
        # Producción de OFs para productos SIN línea de forecast (solo vendibles)
        no_fc_mo_pids = [pid for pid in mo_data if pid not in all_product_ids]
        mos_no_fc = 0.0
        if no_fc_mo_pids:
            sale_ok_pids = set(
                self.env['product.product'].browse(no_fc_mo_pids)
                .filtered(lambda p: p.sale_ok).ids
            )
            mos_no_fc = round(sum(
                sum(v.values()) for pid, v in mo_data.items()
                if pid not in all_product_ids and pid in sale_ok_pids
            ), 2)

        # Entregado para productos SIN línea de forecast (solo vendibles)
        delivered_no_fc = 0.0
        try:
            no_fc_del_domain = [
                ('state', '=', 'done'),
                ('picking_id.picking_type_id.code', '=', 'outgoing'),
                ('date', '>=', fields.Datetime.to_string(dt_from)),
                ('date', '<=', fields.Datetime.to_string(dt_to)),
                ('product_id.sale_ok', '=', True),
                ('company_id', '=', self.env.company.id),
            ]
            if all_product_ids_list:
                no_fc_del_domain.append(('product_id', 'not in', all_product_ids_list))
            groups = self.env['stock.move.line'].read_group(no_fc_del_domain, ['quantity:sum'], [])
            delivered_no_fc = round((groups[0]['quantity'] or 0.0) if groups else 0.0, 2)
        except Exception:
            delivered_no_fc = 0.0

        # Cumplimiento de demanda para productos SIN línea de forecast
        demand_delivered_no_fc = 0.0
        try:
            if all_product_ids_list:
                _so_no_fc = self.env['sale.order'].search([
                    ('state', 'in', ('sale', 'done')),
                    ('date_order', '>=', fields.Datetime.to_string(dt_from)),
                    ('date_order', '<=', fields.Datetime.to_string(dt_to)),
                    ('company_id', '=', self.env.company.id),
                ])
                _so_no_fc_ids = _so_no_fc.ids
                if _so_no_fc_ids:
                    _dd_no_fc_domain = [
                        ('state', '=', 'done'),
                        ('picking_id.picking_type_id.code', '=', 'outgoing'),
                        ('picking_id.sale_id', 'in', _so_no_fc_ids),
                        ('product_id.sale_ok', '=', True),
                        ('product_id', 'not in', all_product_ids_list),
                        ('company_id', '=', self.env.company.id),
                    ]
                    _dd_groups = self.env['stock.move.line'].read_group(_dd_no_fc_domain, ['quantity:sum'], [])
                    demand_delivered_no_fc = round(
                        (_dd_groups[0]['quantity'] or 0.0) if _dd_groups else 0.0, 2)
        except Exception:
            demand_delivered_no_fc = 0.0

        # Demanda de SOs en el período para productos SIN línea de forecast (solo vendibles)
        so_demand_no_fc = 0.0
        try:
            no_fc_domain = [
                ('order_id.state', 'in', ('sale', 'done')),
                ('order_id.date_order', '>=', fields.Datetime.to_string(dt_from)),
                ('order_id.date_order', '<=', fields.Datetime.to_string(dt_to)),
                ('product_id.sale_ok', '=', True),
                ('company_id', '=', self.env.company.id),
            ]
            if exclude_services:
                no_fc_domain.append(('product_id.type', '!=', 'service'))
            if all_product_ids_list:
                no_fc_domain.append(('product_id', 'not in', all_product_ids_list))
            groups = self.env['sale.order.line'].read_group(no_fc_domain, ['product_uom_qty:sum'], [])
            so_demand_no_fc = round((groups[0]['product_uom_qty'] or 0.0) if groups else 0.0, 2)
        except Exception:
            so_demand_no_fc = 0.0

        return mos_no_fc, delivered_no_fc, demand_delivered_no_fc, so_demand_no_fc
