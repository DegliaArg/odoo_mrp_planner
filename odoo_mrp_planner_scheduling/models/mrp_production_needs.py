"""
Módulo: mrp_production_needs.py
Modelo: mrp.production.needs (TransientModel)

Motor de necesidades de producción — "Panel 1".

Para un mes a programar y una ventana de promedio de forecast, recorre los artículos
relevantes y calcula por SKU:

    Posición de stock   = cantidad pronosticada (virtual_available) del almacén
    Promedio forecast   = SUM(forecast en ventana) / Nº FIJO de meses de la ventana
    Forecast del mes    = forecast del mes a programar
    Stock de seguridad  = ROUNDUP(promedio × factor)
    Stock objetivo      = stock de seguridad + forecast del mes (+ demanda de lead time)
    Necesidad neta      = MAX(0, ROUNDUP(objetivo − posición))
    Cantidad a fabricar = 0 si no es producible; si necesidad>0 → MAX(lote mínimo, necesidad)
    Cobertura           = posición/promedio y (posición+a fabricar)/promedio (en meses)
    Estado              = cascada de validaciones

No crea órdenes ni modifica datos: devuelve filas calculadas para el panel. El disparo
de la OF es una acción posterior, con aprobación humana.
"""
import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpProductionNeeds(models.TransientModel):
    _name = 'mrp.production.needs'
    _description = 'Motor de necesidades de producción (Panel 1)'

    # Estados posibles. Se exponen para que el panel pueda
    # ofrecerlos como filtro sin recalcular.
    STATE_REVISAR_ORIGEN = 'Revisar origen'
    STATE_SIN_FORECAST = 'Sin forecast'
    STATE_NO_FABRICAR = 'No fabricar'
    STATE_STOCK_SUFICIENTE = 'Stock suficiente'
    STATE_ANALIZAR_COBERTURA = 'Analizar cobertura'
    STATE_PROGRAMAR = 'Programar'

    def _compute_display_name(self):
        """El panel es un TransientModel sin campo de nombre; sin esto el
        breadcrumb mostraría 'mrp.production.needs,<id>'."""
        for rec in self:
            rec.display_name = _('Planificación')

    # ── API pública ───────────────────────────────────────────────────────────

    @api.model
    def get_needs_data(self, target_month, date_from, date_to, warehouse_id=None):
        """Calcula las necesidades de producción para el panel.

        :param target_month: fecha (string o date) del mes a programar. Se normaliza
            al día 1 del mes.
        :param date_from: fecha del primer mes incluido en el promedio de forecast.
        :param date_to: fecha del último mes incluido en el promedio.
        :param warehouse_id: almacén cuyo stock pronosticado se usa como posición.
            Si es None se toma el de la configuración, y si tampoco hay, todos.
        :returns: dict {'rows': [...], 'kpis': {...}, 'meta': {...}}
        """
        tm = fields.Date.to_date(target_month).replace(day=1)
        df = fields.Date.to_date(date_from).replace(day=1)
        dt = fields.Date.to_date(date_to).replace(day=1)
        n_months = max(1, (dt.year - df.year) * 12 + (dt.month - df.month) + 1)

        cfg = self.env['mrp.reschedule.config'].get_config()
        factor = cfg.safety_factor or 0.3
        days_per_month = cfg.days_per_month or 30.4375
        coverage_threshold = cfg.coverage_threshold or 0.0
        # None = no se pasó (usar config); False = "Todos" explícito desde el panel
        wh_id = warehouse_id if warehouse_id is not None else (cfg.planning_warehouse_id.id or False)
        manuf_type_id = cfg.manufacturing_type_id.id or False
        company = self.env.company

        meta = {
            'target_month': fields.Date.to_string(tm),
            'date_from': fields.Date.to_string(df),
            'date_to': fields.Date.to_string(dt),
            'n_months': n_months,
            'safety_factor': factor,
            'coverage_threshold': coverage_threshold,
            'warehouse_id': wh_id,
            'warehouse_name': self.env['stock.warehouse'].browse(wh_id).display_name
                if wh_id else _('Todos los almacenes'),
            'manufacturing_type_set': bool(manuf_type_id),
        }

        # ── Forecast en ventana y en el mes (batch) ──────────────────────────
        Forecast = self.env['mrp.forecast.line']
        fc_company = [('company_id', '=', company.id)]
        fc_window = {
            g['product_id'][0]: (g['forecast_qty'] or 0.0)
            for g in Forecast.read_group(
                [('product_id', '!=', False), ('period', '>=', df), ('period', '<=', dt)] + fc_company,
                ['product_id', 'forecast_qty:sum'], ['product_id'])
            if g['product_id']
        }
        fc_month = {
            g['product_id'][0]: (g['forecast_qty'] or 0.0)
            for g in Forecast.read_group(
                [('product_id', '!=', False), ('period', '=', tm)] + fc_company,
                ['product_id', 'forecast_qty:sum'], ['product_id'])
            if g['product_id']
        }

        # ── Universo de artículos relevantes ─────────────────────────────────
        # Almacenables activos que son vendibles o que tienen forecast en la
        # ventana (señal de planificación). Evita volcar materias primas sin uso.
        Product = self.env['product.product']
        storable = [('is_storable', '=', True)] if 'is_storable' in Product._fields \
            else [('type', '=', 'product')]
        base = [('active', '=', True)] + storable + \
               ['|', ('company_id', '=', company.id), ('company_id', '=', False)]
        sellable_ids = set(Product.search(base + [('sale_ok', '=', True)]).ids)
        universe = sorted(sellable_ids | set(fc_window.keys()))
        products = Product.browse(universe).exists()
        if not products:
            return {'rows': [], 'kpis': self._empty_kpis(), 'meta': meta}

        # ── Posición de stock (virtual_available) por almacén ────────────────
        scoped = products.with_context(warehouse=wh_id) if wh_id else products
        stock_map = {p.id: (p.virtual_available or 0.0) for p in scoped}

        # ── Maestro: tipo de origen, categorías, precio ───────────────────────
        templates = products.mapped('product_tmpl_id')
        tmpl_type = {t.id: t.x_product_type_ids[:1] for t in templates}
        tmpl_categ = {t.id: (t.categ_id.name or '') for t in templates}
        has_sale_cat = 'x_sale_category' in self.env['product.template']._fields
        tmpl_sale_cat = {t.id: (getattr(t, 'x_sale_category', '') or '') for t in templates} \
            if has_sale_cat else {}
        tmpl_price = {t.id: (t.list_price or 0.0) for t in templates}

        # Lead time: se toma de la BOM aplicable (Plazo de fabricación + Días para
        # preparar la OF); si el artículo no se fabrica, se usa el lead del origen
        # (mrp.product.type.lead_time_days) como respaldo (compra-venta nacional/importado).
        origin_ids = list({o.id for o in tmpl_type.values() if o})
        lead_map = {t.id: (t.lead_time_days or 0)
                    for t in self.env['mrp.product.type'].browse(origin_ids)}
        try:
            boms_by_product = self.env['mrp.bom']._bom_find(products)
        except Exception:
            boms_by_product = {}

        # ── Resolución final → componente fabricado (de dónde leer máquina + mínimo) ─
        # La máquina y el mínimo por turno son un dato del nivel del COMPONENTE
        # FABRICADO, no del artículo final. Para cada final se resuelve de qué producto
        # leerlos (override manual → componente de la BOM cuyo almacén de fabricación es
        # el configurado → el propio final como fallback). Varios finales pueden
        # compartir el mismo componente fabricado (muchos-a-uno): el dato vive una sola vez.
        manuf_ids = {
            p.id for p in products
            if manuf_type_id and tmpl_type.get(p.product_tmpl_id.id)
            and tmpl_type[p.product_tmpl_id.id].id == manuf_type_id
        }
        # Lee el campo precalculado (manufactured_product_id); no recorre la BOM aquí.
        manuf_source = self._resolve_manufactured_sources(products, manuf_ids)

        # Mínimo por turno y máquina preferida, leídos de la plantilla fuente.
        source_tmpl_ids = {t.id for t in manuf_source.values()} | set(templates.ids)
        source_tmpls = self.env['product.template'].browse(list(source_tmpl_ids))
        tmpl_min = {t.id: (t.min_per_shift or 0.0) for t in source_tmpls}
        pref = {}
        for wc in self.env['mrp.product.workcenter'].search([
            ('product_tmpl_id', 'in', list(source_tmpl_ids)),
            ('is_preferred', '=', True),
            ('active', '=', True),
        ]):
            pref.setdefault(wc.product_tmpl_id.id, wc.workcenter_id.display_name or '')

        # ── Compra-venta: mínimo y lead time del proveedor preferido ──────────
        # Los artículos de compra-venta igual disparan una OF (las rutas generan la OC
        # hacia atrás), pero el lote mínimo y el plazo salen del proveedor. El proveedor
        # no está en el final (pasa por envasado) sino en el componente que se compra,
        # precalculado en purchase_product_id. Si no hay componente, se usa el propio
        # final (caso: el final ya tiene proveedor directo).
        purch_by_tmpl = {t.id: t.purchase_product_id for t in templates}
        purch_prod_ids = set(products.ids)
        purch_tmpl_ids = set(templates.ids)
        for bp in purch_by_tmpl.values():
            if bp:
                purch_prod_ids.add(bp.id)
                purch_tmpl_ids.add(bp.product_tmpl_id.id)
        sup_by_variant, sup_by_tmpl = {}, {}
        for s in self.env['product.supplierinfo'].search(
                ['|', ('product_tmpl_id', 'in', list(purch_tmpl_ids)),
                      ('product_id', 'in', list(purch_prod_ids))],
                order='sequence, min_qty desc, id'):
            if s.product_id:
                sup_by_variant.setdefault(s.product_id.id, s)
            elif s.product_tmpl_id:
                sup_by_tmpl.setdefault(s.product_tmpl_id.id, s)

        rows = []
        for p in products:
            tmpl_id = p.product_tmpl_id.id
            origin = tmpl_type.get(tmpl_id)
            origin_name = origin.name if origin else ''
            is_manuf = bool(manuf_type_id and origin and origin.id == manuf_type_id)
            # Proveedor del componente comprado (precalculado) o del propio final.
            seller = None
            if not is_manuf:
                bp = purch_by_tmpl.get(tmpl_id)
                if bp:
                    seller = sup_by_variant.get(bp.id) or sup_by_tmpl.get(bp.product_tmpl_id.id)
                else:
                    seller = sup_by_variant.get(p.id) or sup_by_tmpl.get(tmpl_id)
            # Compra-venta = no es producción interna pero tiene proveedor de compra.
            is_purchase = bool(not is_manuf and seller)
            is_producible = is_manuf or is_purchase
            origin_lead = lead_map.get(origin.id, 0) if origin else 0

            K = stock_map.get(p.id, 0.0)
            has_fc = p.id in fc_window
            L = (fc_window[p.id] / n_months) if has_fc else None
            M = fc_month.get(p.id, 0.0)

            if is_manuf:
                # Producción interna: lead de la BOM, mínimo por turno del componente fabricado.
                bom = boms_by_product.get(p)
                bom_lead = ((bom.produce_delay or 0) + (bom.days_to_prepare_mo or 0)) if bom else 0
                lead_days = bom_lead or origin_lead
                src = manuf_source.get(p.id)
                src_tmpl_id = src.id if src else tmpl_id
                wc_name = pref.get(src_tmpl_id, '') or pref.get(tmpl_id, '')
                mn = tmpl_min.get(src_tmpl_id) or tmpl_min.get(tmpl_id) or 0.0
            elif is_purchase:
                # Compra-venta: lead y lote mínimo del proveedor preferido.
                lead_days = seller.delay or origin_lead
                wc_name = seller.partner_id.display_name or ''
                mn = seller.min_qty or 0.0
            else:
                lead_days = origin_lead
                wc_name = ''
                mn = 0.0
            min_shift = mn if mn else None

            N = math.ceil(L * factor) if L is not None else None
            # Stock objetivo = forecast del mes + demanda durante lead time + stock de seguridad
            if L is not None and lead_days and lead_days > 0:
                O = math.ceil(M + L * lead_days / days_per_month + N)
                P = max(0, math.ceil(O - K))
            else:
                O = P = None

            if is_producible and P and P > 0:
                Q = max(min_shift or 0.0, P)
            else:
                Q = 0.0

            R = (K / L) if L else None
            S = ((K + Q) / L) if L else None

            state, reason = self._compute_state(
                origin, is_producible, is_manuf, L, O, P, Q, min_shift, S, coverage_threshold)

            rows.append({
                'product_id': p.id,
                'product_tmpl_id': tmpl_id,
                'code': p.default_code or '',
                'name': p.display_name,
                'origin': origin_name,
                'categ': tmpl_categ.get(tmpl_id, ''),
                'sale_category': tmpl_sale_cat.get(tmpl_id, ''),
                'list_price': tmpl_price.get(tmpl_id, 0.0),
                'machine': wc_name,
                'min_per_shift': min_shift,
                'stock_position': K,
                'avg_forecast': L,
                'month_forecast': M,
                'safety_stock': N,
                'target_stock': O,
                'net_need': P,
                'suggested_qty': Q,
                'coverage_now': R,
                'coverage_plan': S,
                'state': state,
                'state_reason': reason,
            })

        return {'rows': rows, 'kpis': self._compute_kpis(rows), 'meta': meta}

    # ── Resolución final → componente fabricado ─────────────────────────────────

    def _resolve_manufactured_sources(self, products, manuf_ids):
        """Plantilla desde la que leer máquina y mínimo para cada producto interno.

        Lee el campo precalculado (no recorre la BOM en cada carga):
          1. manufactured_product_id manual del final  (override).
          2. el propio artículo final  (fallback).
        manufactured_product_id lo completa el recálculo (que recorre la BOM una sola vez).
        """
        sources = {}
        for p in products:
            tmpl = p.product_tmpl_id
            if p.id in manuf_ids:
                mp = tmpl.manufactured_product_id
                sources[p.id] = mp.product_tmpl_id if mp else tmpl
            else:
                sources[p.id] = tmpl
        return sources

    # ── Recorrido de BOM (sólo en el recálculo, no en cada carga) ──────────────

    def _product_supplier_wh_ids(self, product):
        """Almacenes donde se fabrica/abastece el producto, según el supplier_wh_id de
        sus rutas de reabastecimiento (dato nativo de Odoo, sin duplicar)."""
        return {r.supplier_wh_id.id for r in product.route_ids if r.supplier_wh_id}

    def _all_bom_components(self, product):
        """Componentes de TODAS las BOM del producto (un artículo puede tener varias: una
        para fabricar y otra para comprar/envasar). _bom_find devolvería sólo una."""
        boms = self.env['mrp.bom'].search([
            '|', ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
                 ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ])
        return boms.mapped('bom_line_ids').mapped('product_id')

    def _find_warehouse_product(self, product, manuf_wh_id, manuf_route, seen, cache, depth):
        """Recorre las BOM multinivel y devuelve el primer componente que se fabrica en el
        almacén configurado (supplier_wh_id de su ruta) y además tiene la ruta
        "Manufactura" tildada (debe ser un ítem que se fabrica, no que se compra)."""
        empty = self.env['product.product']
        if product.id in cache:
            return cache[product.id]
        if depth > 15 or product.id in seen:
            return empty
        seen.add(product.id)
        result = empty
        for comp in self._all_bom_components(product):
            if (manuf_wh_id in self._product_supplier_wh_ids(comp)
                    and (not manuf_route or manuf_route.id in comp.route_ids.ids)):
                result = comp
                break
            sub = self._find_warehouse_product(comp, manuf_wh_id, manuf_route, seen, cache, depth + 1)
            if sub:
                result = sub
                break
        cache[product.id] = result
        return result

    @staticmethod
    def _code_digits(code):
        return ''.join(ch for ch in (code or '') if ch.isdigit())

    def _common_tail_len(self, a, b):
        """Cantidad de dígitos finales que comparten dos códigos (el semiterminado que se
        compra comparte la cola del código con el artículo final; el packaging no). Sólo
        se usa como desempate cuando quedan varios componentes comprables."""
        da, db = self._code_digits(a), self._code_digits(b)
        i = 0
        while i < len(da) and i < len(db) and da[-1 - i] == db[-1 - i]:
            i += 1
        return i

    def _is_purchasable(self, product, buy_route):
        """Un componente cuenta como comprable si tiene marcado "Se puede comprar"
        (purchase_ok) y la ruta "Comprar" tildada. Así se descartan los semiterminados
        que se fabrican (ruta Fabricar) aunque compartan código."""
        if not product.purchase_ok:
            return False
        if buy_route and buy_route.id not in product.route_ids.ids:
            return False
        return True

    def _gather_purchasable(self, product, buy_route, seen, acc, depth):
        """Junta los componentes COMPRABLES (purchase_ok + ruta Comprar) de todas las BOM
        multinivel; el ítem que se compra suele estar 2 o más niveles hacia abajo, y un
        artículo puede tener una BOM de fabricación y otra de compra."""
        if depth > 15 or product.id in seen:
            return
        seen.add(product.id)
        for comp in self._all_bom_components(product):
            if self._is_purchasable(comp, buy_route):
                acc.append(comp)
            self._gather_purchasable(comp, buy_route, seen, acc, depth + 1)

    def _find_purchased_product(self, product):
        """Componente que realmente se compra al proveedor. Criterio principal: el
        componente es comprable (purchase_ok + ruta "Comprar"), lo que descarta los
        semiterminados que se fabrican. Si queda más de un comprable (p. ej. el semi y el
        packaging), desempata por el que comparte el código con el artículo final."""
        empty = self.env['product.product']
        buy_route = self.env.ref('purchase_stock.route_warehouse0_buy', raise_if_not_found=False)
        acc = []
        self._gather_purchasable(product, buy_route, set(), acc, 0)
        uniq = {c.id: c for c in acc}
        cands = list(uniq.values())
        if not cands:
            return empty
        if len(cands) == 1:
            return cands[0]
        best, best_len = empty, 0
        for comp in cands:
            n = self._common_tail_len(product.default_code, comp.default_code)
            if n > best_len:
                best, best_len = comp, n
        return best if best_len >= 4 else empty

    @api.model
    def _recompute_planning_sources(self):
        """Precalcula, recorriendo la BOM una sola vez, los campos de planificación:
        manufactured_product_id (producción interna) y purchase_product_id (compra-venta).
        Lo invoca el botón de configuración y el cron. Así el panel no explora la BOM en
        cada carga. Sólo escribe cuando detecta un valor; si no, respeta lo cargado."""
        cfg = self.env['mrp.reschedule.config'].get_config()
        manuf_type_id = cfg.manufacturing_type_id.id or False
        manuf_wh = cfg.manufacturing_warehouse_id
        manuf_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
        Product = self.env['product.product']
        storable = [('is_storable', '=', True)] if 'is_storable' in Product._fields \
            else [('type', '=', 'product')]
        prods = Product.search(
            [('active', '=', True)] + storable
            + [('product_tmpl_id.x_product_type_ids', '!=', False)])
        cache_wh, done = {}, set()
        n_manuf = n_buy = 0
        for p in prods:
            tmpl = p.product_tmpl_id
            if tmpl.id in done:
                continue
            done.add(tmpl.id)
            origin = tmpl.x_product_type_ids[:1]
            is_manuf = bool(manuf_type_id and origin and origin.id == manuf_type_id)
            # El recálculo sólo escribe cuando DETECTA algo; si no encuentra, no toca el
            # campo (respeta el valor cargado a mano). Como la detección es determinística,
            # cuando encuentra debería coincidir, así que pisar es seguro.
            if is_manuf:
                if not manuf_wh:
                    continue
                try:
                    mp = self._find_warehouse_product(p, manuf_wh.id, manuf_route, set(), cache_wh, 0)
                except Exception:
                    mp = Product
                if mp and tmpl.manufactured_product_id.id != mp.id:
                    tmpl.manufactured_product_id = mp.id
                    n_manuf += 1
            else:
                try:
                    bp = self._find_purchased_product(p)
                except Exception:
                    bp = Product
                if bp and tmpl.purchase_product_id.id != bp.id:
                    tmpl.purchase_product_id = bp.id
                    n_buy += 1
        return {'manufactured': n_manuf, 'purchase': n_buy, 'products': len(prods)}

    # ── Lógica de estado ───────────────────────────────────────────────────────

    def _compute_state(self, origin, is_producible, is_manuf, L, O, P, Q, min_shift, S, coverage_threshold):
        """Cascada de estado del motor. Devuelve (estado, motivo).

        Aplica tanto a producción interna como a compra-venta (ambas disparan OF): la
        diferencia es sólo de dónde salen el mínimo y el lead time. Para compra-venta,
        un mínimo 0 es válido (no exige revisión); para producción interna, un mínimo
        ausente sí se marca para revisar (falta el dato del componente fabricado)."""
        if not origin:
            return self.STATE_REVISAR_ORIGEN, 'El artículo no tiene tipo de origen asignado.'
        if L is None:
            return self.STATE_SIN_FORECAST, 'No hay forecast cargado en la ventana seleccionada.'
        if not is_producible:
            # Tiene demanda (forecast) pero no se pudo resolver cómo abastecerlo: no es
            # producción interna y no se detectó el componente que se compra. Se marca para
            # revisar (cargar el proveedor o el componente comprado manual) en vez de
            # ocultarlo como "No fabricar".
            return 'Revisar abastecimiento', (
                'No se detectó el componente que se compra ni hay proveedor. Cargá el '
                'proveedor del componente o el "Componente comprado (manual)" del artículo.')
        if O is None:
            return self.STATE_REVISAR_ORIGEN, 'Falta el lead time (BOM o proveedor) para calcular el stock objetivo.'
        if P is not None and P <= 0:
            return self.STATE_STOCK_SUFICIENTE, 'La posición de stock cubre el stock objetivo.'
        if Q and Q > 0 and S is not None and coverage_threshold and S > coverage_threshold:
            return self.STATE_ANALIZAR_COBERTURA, (
                'La cobertura con programa (%.1f meses) supera el umbral de %g.' % (S, coverage_threshold))

        flags = []
        if P and Q is not None and L and Q < L:
            flags.append('Revisar cantidad')
        # El mínimo sólo es obligatorio en producción interna (dato del componente fabricado);
        # en compra-venta un mínimo 0 significa "sin lote mínimo" y es válido.
        if is_manuf and min_shift is None:
            flags.append('Revisar mínimo')
        if Q is not None and P is not None and Q > P:
            flags.append('Aplica mínimo')

        blocking = any(f.startswith('Revisar') for f in flags)
        if not blocking:
            flags.append(self.STATE_PROGRAMAR)
            reason = ('Listo para programar.' if len(flags) == 1
                      else 'Listo para programar (necesidad %s u.).' % (int(P) if P is not None else 0))
            return ' | '.join(flags), reason
        return ' | '.join(flags), 'Necesidad %s u.; revisar los puntos indicados.' % (
            int(P) if P is not None else 0)

    # ── KPIs superiores del panel ──────────────────────────────────────────────

    def _compute_kpis(self, rows):
        a_programar = sum(1 for r in rows if self.STATE_PROGRAMAR in (r['state'] or ''))
        need_fab = sum((r['suggested_qty'] or 0.0) for r in rows)
        a_revisar = sum(1 for r in rows if 'Revisar' in (r['state'] or ''))
        con_necesidad = sum(1 for r in rows if (r['net_need'] or 0) > 0)
        return {
            'total': len(rows),
            'a_programar': a_programar,
            'con_necesidad': con_necesidad,
            'necesidad_fabricacion': round(need_fab, 2),
            'a_revisar': a_revisar,
        }

    def _empty_kpis(self):
        return {'total': 0, 'a_programar': 0, 'con_necesidad': 0,
                'necesidad_fabricacion': 0.0, 'a_revisar': 0}

    # ── Apertura del panel ──────────────────────────────────────────────────────

    @api.model
    def _ensure_scheduling_group(self):
        """El panel es de Planificación: deja pasar al grupo de scheduling y admins."""
        if not self.env['mrp.reschedule.config']._user_in_scheduling_group():
            raise UserError(_('No tiene permisos para acceder al panel de planificación.'))

    @api.model
    def action_open_needs(self):
        """Abre el Panel 1 (vista form sin barra de control, como los demás paneles)."""
        self._ensure_scheduling_group()
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Planificación'),
            'res_model': 'mrp.production.needs',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'odoo_mrp_planner_scheduling.mrp_production_needs_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_needs(self):
        return self.action_open_needs()

    # ── Disparo de OF ───────────────────────────────────────────────────────────

    def _lead_days_for_product(self, product, cfg):
        """Lead time (días) de un artículo, con la misma lógica que el panel:
        producción interna → BOM (produce_delay + days_to_prepare_mo); compra-venta →
        delay del proveedor preferido; respaldo → lead del tipo de origen."""
        tmpl = product.product_tmpl_id
        origin = tmpl.x_product_type_ids[:1]
        manuf_type_id = cfg.manufacturing_type_id.id or False
        is_manuf = bool(manuf_type_id and origin and origin.id == manuf_type_id)
        origin_lead = (origin.lead_time_days or 0) if origin else 0
        if is_manuf:
            try:
                bom = self.env['mrp.bom']._bom_find(product).get(product)
            except Exception:
                bom = False
            bom_lead = ((bom.produce_delay or 0) + (bom.days_to_prepare_mo or 0)) if bom else 0
            return bom_lead or origin_lead
        # Compra-venta: lead del proveedor del componente comprado (manual o detectado).
        purchase = tmpl.purchase_product_id or product
        seller = purchase.seller_ids[:1]
        if seller:
            return seller.delay or origin_lead
        return origin_lead

    @api.model
    def action_generate_mo(self, items, target_month=None):
        """Crea y confirma una OF del producto final por cada ítem.

        Decisión 7: se dispara 1 OF del producto terminado en el almacén de la
        configuración (su operación de Fabricación); las OF/OC de los componentes
        las genera Odoo hacia atrás por las rutas de abastecimiento. La OF queda
        confirmada pero es responsabilidad del usuario revisarla/planificarla.

        :param items: lista de dicts [{'product_id': int, 'qty': float}, ...]
        :param target_month: mes a programar; fija la fecha de inicio prevista de
            la OF (primer día del mes, sin planificar en el pasado).
        :returns: acción que abre la(s) OF generada(s).
        """
        self._ensure_scheduling_group()
        items = [it for it in (items or []) if it.get('product_id') and (it.get('qty') or 0) > 0]
        if not items:
            raise UserError(_('No hay artículos con cantidad a fabricar para generar OF.'))

        cfg = self.env['mrp.reschedule.config'].get_config()
        wh_id = cfg.planning_warehouse_id.id or False
        warehouse = self.env['stock.warehouse'].browse(wh_id) if wh_id else \
            self.env['stock.warehouse'].search(
                [('company_id', '=', self.env.company.id)], limit=1)
        picking_type = warehouse.manu_type_id if warehouse else False

        now = fields.Datetime.now()
        Production = self.env['mrp.production']
        created = Production.browse()
        for it in items:
            product = self.env['product.product'].browse(int(it['product_id']))
            # Fecha programada = hoy + lead time del artículo (BOM para producción
            # interna; delay del proveedor para compra-venta).
            lead_days = self._lead_days_for_product(product, cfg)
            date_start = now + timedelta(days=lead_days)
            vals = {
                'product_id': product.id,
                'product_qty': float(it['qty']),
                'product_uom_id': product.uom_id.id,
                'company_id': self.env.company.id,
                'date_start': date_start,
            }
            if picking_type:
                vals['picking_type_id'] = picking_type.id
            mo = Production.create(vals)
            mo.action_confirm()
            # Trazabilidad: deja constancia en el chatter de que la OF nació del panel
            # de Planificación (mes, cantidad y lead aplicado).
            try:
                mes = fields.Date.to_string(fields.Date.to_date(target_month).replace(day=1)) \
                    if target_month else _('sin especificar')
                mo.message_post(body=_(
                    'Orden de fabricación generada desde el panel de <b>Planificación</b> '
                    '(motor de necesidades). Mes a programar: %(mes)s · cantidad sugerida: %(qty)s · '
                    'fecha programada: hoy + %(lead)s días de lead time.',
                    mes=mes, qty=float(it['qty']), lead=lead_days,
                ))
            except Exception:
                pass
            created |= mo

        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Orden de fabricación'),
                'res_model': 'mrp.production',
                'res_id': created.id,
                'views': [(False, 'form')],
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de fabricación generadas'),
            'res_model': 'mrp.production',
            'domain': [('id', 'in', created.ids)],
            'views': [(False, 'list'), (False, 'form')],
            'view_mode': 'list,form',
            'target': 'current',
        }
