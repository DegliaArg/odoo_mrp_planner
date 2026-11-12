"""
Módulo: mrp_production_needs.py
Modelo: mrp.production.needs (TransientModel)

Motor de necesidades de producción — "Panel 1".

Replica dentro de Odoo la hoja PLANIFICACION del Excel que hoy se usa a mano para
decidir qué fabricar y cuánto. Para un mes a programar y una ventana de promedio de
forecast, recorre los artículos relevantes y calcula por SKU:

    Posición de stock (K)   = cantidad pronosticada (virtual_available) del almacén
    Promedio forecast (L)   = SUM(forecast en ventana) / Nº FIJO de meses de la ventana
    Forecast del mes (M)    = forecast del mes a programar
    Stock de seguridad (N)  = ROUNDUP(L × factor)
    Stock objetivo (O)      = N + M
    Necesidad neta (P)      = MAX(0, ROUNDUP(O − K))
    Cantidad a fabricar (Q) = 0 si no es producción interna; si P>0 → MAX(mínimo_turno, P)
    Cobertura (R / S)       = K/L  y  (K+Q)/L   (en meses)
    Estado (T)              = cascada de validaciones

No crea órdenes ni modifica datos: devuelve filas calculadas para el panel. El disparo
de la OF es una acción posterior, con aprobación humana.

Ver docs/plan_panel1_motor_necesidades.md para el detalle y las decisiones.
"""
import math
from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpProductionNeeds(models.TransientModel):
    _name = 'mrp.production.needs'
    _description = 'Motor de necesidades de producción (Panel 1)'

    # Estados posibles (col T del Excel). Se exponen para que el panel pueda
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
        vuln_wh = cfg.manufacturing_warehouse_id
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

        # ── Maestro: tipo de origen, categoría ────────────────────────────────
        templates = products.mapped('product_tmpl_id')
        tmpl_type = {t.id: t.x_product_type_ids[:1] for t in templates}
        tmpl_categ = {t.id: (t.categ_id.name or '') for t in templates}

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

        # ── Resolución final → vulcanizado (de dónde leer máquina + mínimo) ───
        # La máquina y el mínimo por turno son un dato del nivel VULCANIZADO, no del
        # artículo final. Para cada final se resuelve de qué producto leerlos
        # (override manual → componente de la BOM cuyo almacén de fabricación es el
        # de vulcanizado → el propio final como fallback). Varios finales pueden
        # compartir el mismo vulcanizado (muchos-a-uno): el dato vive una sola vez.
        manuf_ids = {
            p.id for p in products
            if manuf_type_id and tmpl_type.get(p.product_tmpl_id.id)
            and tmpl_type[p.product_tmpl_id.id].id == manuf_type_id
        }
        vuln_source = self._resolve_vulcanizado_sources(products, vuln_wh, manuf_ids)

        # Mínimo por turno y máquina preferida, leídos de la plantilla fuente (VL).
        source_tmpl_ids = {t.id for t in vuln_source.values()} | set(templates.ids)
        source_tmpls = self.env['product.template'].browse(list(source_tmpl_ids))
        tmpl_min = {t.id: (t.min_per_shift or 0.0) for t in source_tmpls}
        pref = {}
        for wc in self.env['mrp.product.workcenter'].search([
            ('product_tmpl_id', 'in', list(source_tmpl_ids)),
            ('is_preferred', '=', True),
            ('active', '=', True),
        ]):
            pref.setdefault(wc.product_tmpl_id.id, wc.workcenter_id.display_name or '')

        rows = []
        for p in products:
            tmpl_id = p.product_tmpl_id.id
            origin = tmpl_type.get(tmpl_id)
            origin_name = origin.name if origin else ''
            is_manuf = bool(manuf_type_id and origin and origin.id == manuf_type_id)
            bom = boms_by_product.get(p)
            bom_lead = ((bom.produce_delay or 0) + (bom.days_to_prepare_mo or 0)) if bom else 0
            lead_days = bom_lead or (lead_map.get(origin.id, 0) if origin else 0)

            K = stock_map.get(p.id, 0.0)
            has_fc = p.id in fc_window
            L = (fc_window[p.id] / n_months) if has_fc else None
            M = fc_month.get(p.id, 0.0)

            src = vuln_source.get(p.id)
            src_tmpl_id = src.id if src else tmpl_id
            wc_name = pref.get(src_tmpl_id, '') or pref.get(tmpl_id, '')
            # Mínimo por turno: preferimos el del vulcanizado resuelto; si ese no tiene,
            # usamos el del propio final (el Excel ya trae el mínimo resuelto por final).
            mn = tmpl_min.get(src_tmpl_id) or tmpl_min.get(tmpl_id) or 0.0
            min_shift = mn if mn else None

            N = math.ceil(L * factor) if L is not None else None
            # Stock objetivo = forecast del mes + demanda durante lead time + stock de seguridad
            if L is not None and lead_days and lead_days > 0:
                O = math.ceil(M + L * lead_days / days_per_month + N)
                P = max(0, math.ceil(O - K))
            else:
                O = P = None

            if is_manuf and P and P > 0:
                Q = max(min_shift or 0.0, P)
            else:
                Q = 0.0

            R = (K / L) if L else None
            S = ((K + Q) / L) if L else None

            state, reason = self._compute_state(
                origin, is_manuf, L, O, P, Q, min_shift, S, coverage_threshold)

            rows.append({
                'product_id': p.id,
                'product_tmpl_id': tmpl_id,
                'code': p.default_code or '',
                'name': p.display_name,
                'origin': origin_name,
                'categ': tmpl_categ.get(tmpl_id, ''),
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

    # ── Resolución final → vulcanizado ─────────────────────────────────────────

    def _resolve_vulcanizado_sources(self, products, vuln_wh, manuf_ids):
        """Para cada producto devuelve la plantilla desde la que leer máquina y mínimo.

        Precedencia:
          1. vulcanizado_id manual del final  (override, equivale a BD_VULCANIZADO).
          2. componente de la BOM cuyo almacén de fabricación es el de vulcanizado
             (auto-detección por la ruta de reabastecimiento del componente).
          3. el propio artículo final  (fallback: nunca bloquea ni rompe el panel).

        Sólo resuelve para los productos de producción interna; el resto usa su propia
        plantilla. Soporta cadenas que atraviesan varios almacenes/sectores (recorre la
        BOM multinivel). Cualquier error al explorar la BOM cae al fallback.

        :returns: {product_id: product.template} (siempre una plantilla no vacía)
        """
        sources = {}
        cache = {}
        for p in products:
            tmpl = p.product_tmpl_id
            if p.id not in manuf_ids:
                sources[p.id] = tmpl
                continue
            if tmpl.vulcanizado_id:
                sources[p.id] = tmpl.vulcanizado_id.product_tmpl_id
                continue
            if vuln_wh:
                try:
                    vl = self._find_warehouse_product(p, vuln_wh.id, set(), cache, 0)
                except Exception:
                    vl = self.env['product.product']
                sources[p.id] = vl.product_tmpl_id if vl else tmpl
            else:
                sources[p.id] = tmpl
        return sources

    def _product_supplier_wh_ids(self, product):
        """Almacenes donde se fabrica/abastece el producto, según el supplier_wh_id de
        sus rutas de reabastecimiento (dato nativo de Odoo, sin duplicar)."""
        return {r.supplier_wh_id.id for r in product.route_ids if r.supplier_wh_id}

    def _find_warehouse_product(self, product, vuln_wh_id, seen, cache, depth):
        """Recorre la BOM multinivel y devuelve el primer componente cuyo almacén de
        fabricación (supplier_wh_id de su ruta) es el de vulcanizado. product.product
        vacío si no lo encuentra. Maneja cadenas de más de dos almacenes."""
        empty = self.env['product.product']
        if product.id in cache:
            return cache[product.id]
        if depth > 15 or product.id in seen:
            return empty
        seen.add(product.id)
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        result = empty
        if bom:
            for line in bom.bom_line_ids:
                comp = line.product_id
                if vuln_wh_id in self._product_supplier_wh_ids(comp):
                    result = comp
                    break
                sub = self._find_warehouse_product(comp, vuln_wh_id, seen, cache, depth + 1)
                if sub:
                    result = sub
                    break
        cache[product.id] = result
        return result

    # ── Lógica de estado (col T del Excel) ─────────────────────────────────────

    def _compute_state(self, origin, is_manuf, L, O, P, Q, min_shift, S, coverage_threshold):
        """Cascada de estado del motor (Excel "Modelo Planificación"). Devuelve (estado, motivo)."""
        if not origin:
            return self.STATE_REVISAR_ORIGEN, 'El artículo no tiene tipo de origen asignado.'
        if L is None:
            return self.STATE_SIN_FORECAST, 'No hay forecast cargado en la ventana seleccionada.'
        if not is_manuf:
            return self.STATE_NO_FABRICAR, 'El origen no es producción interna (se repone por compra).'
        if O is None:
            return self.STATE_REVISAR_ORIGEN, 'Falta el lead time del origen para calcular el stock objetivo.'
        if P is not None and P <= 0:
            return self.STATE_STOCK_SUFICIENTE, 'La posición de stock cubre el stock objetivo.'
        if Q and Q > 0 and S is not None and coverage_threshold and S > coverage_threshold:
            return self.STATE_ANALIZAR_COBERTURA, (
                'La cobertura con programa (%.1f meses) supera el umbral de %g.' % (S, coverage_threshold))

        flags = []
        if P and Q is not None and Q < L:
            flags.append('Revisar cantidad')
        if min_shift is None:
            flags.append('Revisar mínimo')
        if Q is not None and P is not None and Q > P:
            flags.append('Aplica mínimo')
        if Q is not None and Q >= L and min_shift is not None:
            flags.append(self.STATE_PROGRAMAR)

        if not flags:
            return self.STATE_PROGRAMAR, 'Listo para programar.'
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

        # Fecha de inicio prevista = primer día del mes a programar, nunca en el pasado.
        date_start = False
        if target_month:
            start = datetime.combine(fields.Date.to_date(target_month).replace(day=1), time(8, 0))
            now = fields.Datetime.now()
            date_start = start if start > now else now

        Production = self.env['mrp.production']
        created = Production.browse()
        for it in items:
            product = self.env['product.product'].browse(int(it['product_id']))
            vals = {
                'product_id': product.id,
                'product_qty': float(it['qty']),
                'product_uom_id': product.uom_id.id,
                'company_id': self.env.company.id,
            }
            if picking_type:
                vals['picking_type_id'] = picking_type.id
            if date_start:
                vals['date_start'] = date_start
            mo = Production.create(vals)
            mo.action_confirm()
            created |= mo

        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Orden de fabricación'),
                'res_model': 'mrp.production',
                'res_id': created.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de fabricación generadas'),
            'res_model': 'mrp.production',
            'domain': [('id', 'in', created.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }
