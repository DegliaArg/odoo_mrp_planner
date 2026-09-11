"""
Mixin: MrpDemandExpansionMixin — expansión del árbol de demanda (BOM, rutas, WC).

Responsabilidades:
- Determinar el método de abastecimiento de cada producto (fabricar, comprar,
  subcontratar, stock).
- Buscar la LdM aplicable y calcular duraciones de operaciones escaladas.
- Construir recursivamente el árbol de demanda multinivel (dict por nodo).
- Explotar kits phantom en el nodo padre (Odoo no crea OF para un kit).
- Aplicar overrides manuales de centros de trabajo sobre el árbol ya construido.
- Resolver el WC preferido para un producto desde x_centros_compatibles.
- Retornar el start más temprano del árbol para el artículo.

Invariante de UoM: la `qty` que recibe `_build_demand_tree` y la `comp_qty` que
recibe `_expand_component` SIEMPRE están expresadas en la UoM de stock del propio
producto (product.uom_id). Todas las conversiones desde UoMs de LdM/línea se hacen
al cruzar cada frontera, con `_compute_quantity` (patrón estándar de Odoo).
"""
import logging

from odoo import models, _


_logger = logging.getLogger(__name__)


class MrpDemandExpansionMixin(models.AbstractModel):
    _name = 'mrp.demand.expansion.mixin'
    _description = 'Mixin de expansión del árbol de demanda'

    # ── Rutas y método de abastecimiento ─────────────────────────────────────

    def _get_supply_method(self, product, cache=None):
        """
        Determina cómo se abastece un producto según las rutas configuradas.

        Evalúa en orden de prioridad:
        1. Subcontratación: existe LdM de tipo 'subcontract'.
        2. Fabricación: alguna regla de ruta tiene action == 'manufacture'.
        3. Compra: alguna regla de ruta tiene action == 'buy'.
        4. Fallback por BOM genérica o purchase_ok.

        :param product: product.product — producto a evaluar.
        :param cache: dict | None — caché {product_id: método} para no recalcular el
            mismo producto (aparece repetido en árboles con componentes compartidos).
        :returns: str — 'subcontract' | 'manufacture' | 'buy' | 'stock'.
        """
        if cache is not None and product.id in cache:
            return cache[product.id]

        # Subcontratación: tiene una LdM de tipo subcontract (máxima prioridad)
        sub_bom = self.env['mrp.bom'].search([
            ('type', '=', 'subcontract'),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ], limit=1)
        if sub_bom:
            method = 'subcontract'
        else:
            # Rutas configuradas en el producto/categoría. Usar rule.action (campo
            # semántico de Odoo 18) en lugar de picking_type_id.code, que no es
            # confiable con rutas personalizadas (ej. "Mecanizado: suministrar…").
            found = set()
            routes = product.route_ids | product.categ_id.total_route_ids
            for route in routes:
                for rule in route.rule_ids.filtered('active'):
                    if rule.action == 'manufacture':
                        found.add('manufacture')
                    elif rule.action == 'buy':
                        found.add('buy')
            if 'manufacture' in found:
                method = 'manufacture'
            elif 'buy' in found:
                method = 'buy'
            elif self._find_bom(product, cache=None):
                method = 'manufacture'
            elif product.purchase_ok:
                method = 'buy'
            else:
                method = 'stock'

        if cache is not None:
            cache[product.id] = method
        return method

    def _get_purchase_lead_days(self, product):
        """Retorna el plazo de entrega en días del proveedor principal del producto.

        Usa el delay del primer seller_id (menor sequence); si no hay sellers,
        cae a purchase_delay del producto o a 7 días por defecto.

        :param product: product.product — producto a consultar.
        :returns: int — días de plazo de entrega (mínimo 1).
        """
        if product.seller_ids:
            main = product.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
            if main:
                return int(main.delay or 0) or 1
        return int(getattr(product, 'purchase_delay', 0) or 7)

    def _find_bom(self, product, cache=None):
        """Busca la LdM de fabricación activa para el producto (excluye phantom y
        subcontract).

        Intenta primero con el método oficial _bom_find de Odoo (robusto pero
        puede lanzar excepciones en versiones con API inestable); si falla,
        realiza una búsqueda directa excluyendo tipos 'phantom' y 'subcontract'.

        :param product: product.product — producto para el que se busca la LdM.
        :param cache: dict | None — caché {product_id: mrp.bom} para evitar queries
            repetidas del mismo producto.
        :returns: mrp.bom — primera LdM encontrada, o recordset vacío si no existe.
        """
        if cache is not None and product.id in cache:
            return cache[product.id]
        bom = self.env['mrp.bom']
        try:
            result = self.env['mrp.bom']._bom_find(
                product, company_id=self.env.company.id, bom_type='normal',
            )
            bom = (result.get(product) if isinstance(result, dict) else result) or self.env['mrp.bom']
        except Exception:
            bom = self.env['mrp.bom']
        if not bom:
            bom = self.env['mrp.bom'].search([
                ('type', 'not in', ['phantom', 'subcontract']),
                ('company_id', 'in', [False, self.env.company.id]),
                '|',
                ('product_id', '=', product.id),
                '&', ('product_id', '=', False),
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ], limit=1, order='sequence, id')
        if cache is not None:
            cache[product.id] = bom
        return bom

    def _find_bom_any(self, product, cache=None):
        """LdM aplicable al producto INCLUYENDO phantom/subcontract.

        Se usa para detectar kits phantom (que se explotan en el padre) y no para
        elegir la LdM de fabricación. Cachea por product_id.

        :param product: product.product — producto a consultar.
        :param cache: dict | None — caché {product_id: mrp.bom}.
        :returns: mrp.bom — LdM aplicable de mayor prioridad, o recordset vacío.
        """
        if cache is not None and product.id in cache:
            return cache[product.id]
        bom = self.env['mrp.bom']
        try:
            result = self.env['mrp.bom']._bom_find(product, company_id=self.env.company.id)
            bom = (result.get(product) if isinstance(result, dict) else result) or self.env['mrp.bom']
        except Exception:
            bom = self.env['mrp.bom'].search([
                ('company_id', 'in', [False, self.env.company.id]),
                '|',
                ('product_id', '=', product.id),
                '&', ('product_id', '=', False),
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ], limit=1, order='sequence, id')
        if cache is not None:
            cache[product.id] = bom
        return bom

    def _get_op_duration_hours(self, op, bom_factor, default_min=60.0):
        """Calcula la duración en horas de una operación de LdM escalada por bom_factor.

        Modela la duración como lo hace Odoo (fix M2):
          - tiempo de ciclo (time_cycle_manual tiene prioridad sobre time_cycle),
            escalado por bom_factor y ajustado por la eficiencia del CT;
          - más el setup+limpieza del CT (time_start + time_stop), una sola vez por
            operación (no escala con la cantidad).
        Solo cae a `default_min` cuando el total es 0 (sin datos de tiempo): así no
        colapsa un time_cycle 0 legítimo que igual tiene setup/limpieza.

        :param op: mrp.routing.workcenter — operación de la LdM.
        :param bom_factor: float — factor de escala (qty_solicitada / bom.product_qty).
        :param default_min: float — mínimo operativo en minutos si no hay datos.
        :returns: float — duración en horas.
        """
        wc = op.workcenter_id
        cycle = op.time_cycle_manual or op.time_cycle or 0.0
        eff = ((wc.time_efficiency or 100.0) / 100.0) if wc else 1.0
        cycle_scaled = (cycle * bom_factor) / (eff or 1.0)
        setup = ((wc.time_start or 0.0) + (wc.time_stop or 0.0)) if wc else 0.0
        total_min = cycle_scaled + setup
        if total_min <= 0:
            total_min = default_min
        return total_min / 60.0

    # ── Normalización de UoM ──────────────────────────────────────────────────

    def _bom_factor(self, product, qty, bom):
        """Cantidad de corridas de LdM necesarias para `qty` unidades del producto.

        Normaliza la UoM del pedido (product.uom_id) a la UoM de la LdM
        (bom.product_uom_id) antes de dividir por bom.product_qty. Sin esta
        conversión, una LdM definida en docenas/kg contra un pedido en unidades daba
        un factor errado (×12, /1000, etc.) y toda la explosión salía mal (fix #2).

        :param product: product.product — producto que produce la LdM.
        :param qty: float — cantidad pedida, en la UoM de stock del producto.
        :param bom: mrp.bom — LdM aplicable.
        :returns: float — factor de escala de la LdM.
        """
        qty_bom_uom = product.uom_id._compute_quantity(qty, bom.product_uom_id)
        return qty_bom_uom / (bom.product_qty or 1.0)

    def _bom_line_qty(self, bom_line, bom_factor):
        """Cantidad de un componente en su UoM de stock, escalada por bom_factor.

        Convierte de la UoM de la línea de LdM (bom_line.product_uom_id) a la UoM del
        producto componente (product.uom_id), de modo que la cantidad devuelta sea
        directamente comparable con free_qty y reutilizable como `qty` del componente
        en la recursión (mantiene el invariante de UoM, fix #2).

        :param bom_line: mrp.bom.line — línea de LdM.
        :param bom_factor: float — factor de escala de la LdM padre.
        :returns: float — cantidad del componente en su UoM de stock.
        """
        qty_line_uom = bom_line.product_qty * bom_factor
        return bom_line.product_uom_id._compute_quantity(
            qty_line_uom, bom_line.product_id.uom_id,
        )

    # ── Árbol de demanda ──────────────────────────────────────────────────────

    def _get_tree_earliest_start(self, node):
        """Retorna el scheduled_start más temprano entre todos los nodos 'manufacture' del árbol.

        :param node: dict — nodo raíz del árbol de demanda.
        :returns: datetime | None — fecha de inicio más temprana, o None si no hay nodos programados.
        """
        result = None
        if node.get('type') == 'manufacture' and node.get('scheduled_start'):
            result = node['scheduled_start']
        for child in node.get('children', []):
            child_start = self._get_tree_earliest_start(child)
            if child_start:
                result = min(result, child_start) if result else child_start
        return result

    def _node_key(self, item_id, node):
        """Identidad estable de un nodo: item + path completo de productos desde la raíz.

        El path completo (no solo el padre inmediato) elimina la colisión de un
        mismo producto que aparece en dos ramas distintas al mismo nivel: cada
        aparición tiene un path único desde la raíz. Keyea anclas (forced_start)
        y overrides de CT sin que se apliquen a la rama equivocada.

        :param item_id: int — ID del mrp.production.request.item raíz del árbol.
        :param node: dict — nodo con clave 'path' (lista de product_ids raíz→nodo).
        :returns: str — clave estable, ej. "12|100/205/330".
        """
        path = node.get('path') or [node['product'].id]
        return f"{item_id}|" + "/".join(str(p) for p in path)

    def _apply_wc_overrides(self, node, item_id, overrides):
        """Aplica los centros de trabajo editados manualmente al árbol de demanda.

        Reemplaza las operaciones del nodo con el WC guardado en overrides para el
        node_key (item + path completo). La duración total se preserva.

        :param node: dict — nodo del árbol a procesar (se modifica en-place).
        :param item_id: int — ID del mrp.production.request.item al que pertenece el árbol.
        :param overrides: dict — {node_key: workcenter} con los overrides.
        """
        if node.get('type') == 'manufacture' and node.get('operations'):
            key = self._node_key(item_id, node)
            if key in overrides:
                wc = overrides[key]
                # operations son 4-tuplas (primario, candidatos, duración, pin). El
                # override es una elección manual del usuario sobre un único CT. Se
                # marca el PIN de las operaciones que tienen ese CT como candidato,
                # SIN colapsar la lista de candidatos: así la operación sigue sabiendo
                # a qué otros centros puede ir, y se la puede volver a reasignar desde
                # el tablero. Si el CT no es candidato de ninguna (viene del dominio
                # amplio de compatibles), se pinnea toda la ruta a ese CT como
                # respaldo, agregándolo a los candidatos para que la elección sea válida.
                matched = False
                new_ops = []
                for primary, candidates, dur, _pin in node['operations']:
                    if any(c.id == wc.id for c in candidates):
                        new_ops.append((primary, candidates, dur, wc))
                        matched = True
                    else:
                        new_ops.append((primary, candidates, dur, _pin))
                if not matched:
                    new_ops = [
                        (primary,
                         candidates if any(c.id == wc.id for c in candidates) else list(candidates) + [wc],
                         dur, wc)
                        for primary, candidates, dur, _pin in node['operations']
                    ]
                node['operations'] = new_ops
        for child in node.get('children', []):
            self._apply_wc_overrides(child, item_id, overrides)

    def _get_preferred_workcenter(self, product):
        """Devuelve el WC preferido activo del producto desde x_centros_compatibles.

        Si hay varios centros compatibles, prioriza el marcado como is_preferred;
        de lo contrario, toma el primero de la lista. Retorna None si no hay centros.

        :param product: product.product — producto a consultar.
        :returns: mrp.workcenter | None — centro de trabajo preferido, o None.
        """
        centros = product.product_tmpl_id.x_centros_compatibles.filtered('active')
        if not centros:
            return None
        preferred = centros.filtered('is_preferred')
        return (preferred[:1] if preferred else centros[:1]).workcenter_id or None

    def _wc_candidates(self, wc, op=None):
        """CTs candidatos para una operación: el primario + los alternativos
        definidos en la operación de la LdM (alternative_workcenter_ids).

        Si la operación tiene alternativos configurados, se usan SOLO esos
        (ignorando los alternativos nativos del CT). Si no hay alternativos
        en la operación, se devuelve solo el primario.

        El primario va PRIMERO en la lista → desempata a su favor cuando dos
        candidatos terminan al mismo tiempo.

        :param wc: mrp.workcenter | None — centro primario de la operación.
        :param op: mrp.routing.workcenter | None — operación de la LdM.
        :returns: list[mrp.workcenter] — candidatos ([] si no hay centro).
        """
        if not wc:
            return []
        if op and hasattr(op, 'alternative_workcenter_ids'):
            alts = op.alternative_workcenter_ids.filtered('active')
            if alts:
                return [wc] + [a for a in alts if a.id != wc.id]
        return [wc]

    # ── Nodos hoja ────────────────────────────────────────────────────────────

    def _stock_node(self, product, qty, level, path, warning_type, warning_message):
        """Construye un nodo hoja de tipo 'stock' (cubierto por stock o reorden auto)."""
        return {
            'type':            'stock',
            'product':         product,
            'qty':             qty,
            'level':           level,
            'path':            path,
            'warning_type':    warning_type,
            'warning_message': warning_message,
            'operations':      [],
            'children':        [],
            'scheduled_start': None,
            'scheduled_end':   None,
        }

    def _purchase_node(self, product, qty, method, level, path):
        """Construye un nodo hoja de compra/subcontratación con lead y calendario."""
        lead_days  = self._get_purchase_lead_days(product)
        seller_rec = product.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
        supplier_cal = self._get_supplier_calendar(
            seller_rec.partner_id if seller_rec else self.env['res.partner']
        )
        return {
            'type':              method,
            'product':           product,
            'qty':               qty,
            'bom':               None,
            'level':             level,
            'path':              path,
            'lead_days':         lead_days,
            'supplier_name':     seller_rec.partner_id.display_name if seller_rec else '',
            'supplier_calendar': supplier_cal,
            'warning_type':      '',
            'warning_message':   '',
            'operations':        [],
            'children':          [],
            'scheduled_start':   None,
            'scheduled_end':     None,
        }

    # ── Cachés por nivel ──────────────────────────────────────────────────────

    def _scheduling_constants(self):
        """Constantes de duración parametrizables (leídas una vez por cálculo).

        Se leen del singleton de config; 0/None cae al default (no tiene sentido una
        OF de 0 h ni una operación de 0 min sin datos). Ver `default_of_hours` y
        `default_op_minutes` en mrp.reschedule.config.

        :returns: dict — {'of_hours': float, 'op_minutes': float}.
        """
        cfg = self.env['mrp.reschedule.config'].get_config()
        of_hours   = (cfg.default_of_hours   if cfg and cfg.default_of_hours   else 8.0)
        op_minutes = (cfg.default_op_minutes if cfg and cfg.default_op_minutes else 60.0)
        return {'of_hours': of_hours, 'op_minutes': op_minutes}

    def _new_caches(self):
        """Contenedor de cachés compartidos durante la construcción de un árbol.

        Se pasa por referencia en toda la recursión para evitar el N+1 (fix #9):
          - orderpoint: {product_id: bool} regla de reorden auto activa.
          - bom:        {product_id: mrp.bom} LdM de fabricación (excl. phantom).
          - bom_any:    {product_id: mrp.bom} LdM aplicable (incl. phantom).
          - supply:     {product_id: str} método de abastecimiento.
          - stock_used: {product_id: float} stock libre ya asignado en este cálculo,
            para no contar el mismo free_qty dos veces entre ramas/artículos (fix M1).
          - of_hours / op_minutes: constantes de duración parametrizables.
        """
        caches = {'orderpoint': {}, 'bom': {}, 'bom_any': {}, 'supply': {}, 'stock_used': {}}
        caches.update(self._scheduling_constants())
        return caches

    def _prefetch_level_caches(self, bom, caches):
        """Precarga en batch los cachés de orderpoints y LdM aplicable para todos
        los componentes de un nivel de LdM, con un único query por concepto en vez
        de uno por componente (fix #9).

        :param bom: mrp.bom — LdM cuyo nivel de componentes se precarga.
        :param caches: dict — contenedor de cachés (ver _new_caches).
        """
        comps = bom.bom_line_ids.mapped('product_id')
        if not comps:
            return

        op_cache = caches['orderpoint']
        pending_op = comps.filtered(lambda p: p.id not in op_cache)
        if pending_op:
            found = self.env['stock.warehouse.orderpoint'].search([
                ('product_id', 'in', pending_op.ids),
                ('active',     '=', True),
                ('trigger',    '=', 'auto'),
            ]).mapped('product_id')
            found_ids = set(found.ids)
            for p in pending_op:
                op_cache[p.id] = p.id in found_ids

        # Warm del caché de LdM aplicable (incluye phantom) en un solo _bom_find.
        bom_any_cache = caches['bom_any']
        pending_bom = comps.filtered(lambda p: p.id not in bom_any_cache)
        if pending_bom:
            try:
                res = self.env['mrp.bom']._bom_find(
                    pending_bom, company_id=self.env.company.id,
                )
                for p in pending_bom:
                    bom_any_cache[p.id] = res.get(p, self.env['mrp.bom'])
            except Exception:
                pass  # se resolverá individualmente en _find_bom_any

    # ── Construcción y expansión ──────────────────────────────────────────────

    def _build_demand_tree(self, product, qty, level, visited=None, caches=None, path=None):
        """
        Construye recursivamente el árbol de demanda multinivel para un producto.

        Cada nodo del árbol es un dict con las claves: type, product, qty, bom,
        level, operations, children, scheduled_start, scheduled_end.
        Los tipos de nodo posibles son:
          - 'manufacture': se debe fabricar (nodo interno, puede tener hijos).
          - 'buy' / 'subcontract': se debe comprar/subcontratar (nodo hoja).
          - 'stock': cubierto por stock existente o reorden automático (nodo hoja).

        Para cada componente de la LdM se evalúa (en _expand_component): reorden
        automático, kit phantom, stock disponible y método de abastecimiento.

        :param product: product.product — producto raíz o componente a evaluar.
        :param qty: float — cantidad necesaria, en la UoM de stock del producto.
        :param level: int — profundidad en el árbol (0 = artículo raíz de la solicitud).
        :param visited: set | None — productos ya visitados en la rama actual (evita ciclos).
        :param caches: dict | None — cachés compartidos por la recursión (ver _new_caches).
        :param path: list | None — product_ids raíz→padre (identidad estable del nodo).
        :returns: dict | None — nodo raíz del árbol, o None si no existe LdM fabricable.
        """
        if visited is None:
            visited = set()
        if product.id in visited:
            return None
        visited = visited | {product.id}

        # Path de productos desde la raíz hasta este nodo (identidad estable del
        # nodo, ver _node_key). Root: [product.id]; cada nivel agrega su producto.
        node_path = (path or []) + [product.id]

        if caches is None:
            caches = self._new_caches()

        bom = self._find_bom(product, cache=caches['bom'])
        if not bom or bom.type == 'phantom':
            return None  # No se puede fabricar el artículo raíz

        bom_factor = self._bom_factor(product, qty, bom)

        preferred_wc = self._get_preferred_workcenter(product)
        # sudo(): ir.config_parameter solo es legible con permisos de admin; usuarios de wizard no lo tienen
        # El parámetro se escribe con sufijo de empresa; se lee con fallback encadenado
        # (empresa → global → default), igual que 'priority' en mrp_reschedule_cascade_mixin.
        _icp = self.env['ir.config_parameter'].sudo()
        company_id = self.env.company.id
        wc_fallback = (
            _icp.get_param(f'mrp_reschedule.wc_fallback.{company_id}')
            or _icp.get_param('mrp_reschedule.wc_fallback', 'ldm')
        )
        # Cada operación guarda (primario, candidatos, duración, pin). candidatos =
        # primario + sus alternativos activos (universo estable para elegir y para
        # reasignar desde el tablero — NUNCA se colapsa). La ELECCIÓN del CT se hace
        # al programar (según carga), salvo que haya un pin (override manual). pin =
        # None por defecto; _apply_wc_overrides lo setea al reasignar.
        op_minutes = caches.get('op_minutes', 60.0)
        of_hours   = caches.get('of_hours', 8.0)
        operations = []
        dur_bom = (
            sum(self._get_op_duration_hours(op, bom_factor, default_min=op_minutes)
                for op in bom.operation_ids)
            if bom.operation_ids else of_hours
        )
        if preferred_wc:
            operations = [(preferred_wc, [preferred_wc], dur_bom, None)]
        elif bom.operation_ids and wc_fallback == 'ldm':
            for op in bom.operation_ids.sorted('sequence'):
                wc = op.workcenter_id
                operations.append((wc, self._wc_candidates(wc, op=op),
                                   self._get_op_duration_hours(op, bom_factor,
                                                               default_min=op_minutes),
                                   None))
        else:
            operations = [(None, [], dur_bom, None)]

        node = {
            'type':     'manufacture',
            'product':  product,
            'qty':      qty,
            'bom':      bom,
            'level':    level,
            'path':     node_path,
            'operations': operations,
            'children': [],
            'scheduled_start': None,
            'scheduled_end':   None,
        }

        # Precarga batch de cachés (orderpoints + LdM) para los componentes de este
        # nivel: un query por concepto en vez de uno por componente (fix #9).
        self._prefetch_level_caches(bom, caches)

        child_level = level + 1
        for bom_line in bom.bom_line_ids:
            comp     = bom_line.product_id
            comp_qty = self._bom_line_qty(bom_line, bom_factor)
            self._expand_component(node, comp, comp_qty, child_level,
                                   node_path, visited, caches)

        return node

    def _expand_component(self, parent, comp, comp_qty, level, parent_path, visited, caches):
        """Procesa un componente de LdM y agrega el/los nodo(s) a parent['children'].

        Orden de resolución:
        1. Reorden automático (mín/máx) → nodo stock_ok.
        2. Kit phantom → se explotan sus líneas en el padre (fix #3).
        3. Split de stock libre (free_qty) → nodo stock total/parcial.
        4. Método de abastecimiento del remanente (fabricar/comprar/subcontratar).

        :param parent: dict — nodo padre (se modifica en-place).
        :param comp: product.product — componente a procesar.
        :param comp_qty: float — cantidad requerida, en la UoM de stock de comp.
        :param level: int — nivel del componente en el árbol.
        :param parent_path: list — path de product_ids raíz→padre.
        :param visited: set — productos visitados en la rama (evita ciclos).
        :param caches: dict — cachés compartidos (ver _new_caches).
        """
        node_path = parent_path + [comp.id]

        # 1. Reposición automática (mín/máx): el sistema lo repone solo.
        if caches['orderpoint'].get(comp.id, False):
            parent['children'].append(self._stock_node(
                comp, comp_qty, level, node_path,
                'stock_ok', _('Reposición automática (mín/máx)'),
            ))
            return

        # 2. Kit phantom: no se stockea ni se fabrica como tal; se explotan sus
        #    líneas en el padre, como hace Odoo (fix #3: antes el sub-árbol entero
        #    desaparecía porque _find_bom rechazaba las phantom y el nodo era None).
        comp_bom_any = self._find_bom_any(comp, cache=caches['bom_any'])
        if comp_bom_any and comp_bom_any.type == 'phantom':
            self._explode_phantom(parent, comp, comp_bom_any, comp_qty,
                                  level, node_path, visited, caches)
            return

        # 3. Stock realmente LIBRE (on-hand menos reservado), no el on-hand bruto:
        #    con qty_available el motor contaba material ya comprometido y
        #    planificaba de menos. free_qty NO descuenta lo saliente aún sin reservar
        #    (limitación conocida). Ya viene en la UoM de comp (ver _bom_line_qty),
        #    así que la comparación es homogénea (fix #2).
        #    Se descuenta además el stock ya ASIGNADO a otras ramas/artículos en este
        #    mismo cálculo (ledger stock_used): si dos productos comparten un
        #    componente, no cuentan el mismo free_qty dos veces (fix M1).
        used = caches['stock_used']
        gross_avail = max(0.0, comp.free_qty or 0.0)  # negativo (sobre-reservado) → 0
        stock_avail = max(0.0, gross_avail - used.get(comp.id, 0.0))

        if stock_avail >= comp_qty:
            used[comp.id] = used.get(comp.id, 0.0) + comp_qty
            parent['children'].append(self._stock_node(
                comp, comp_qty, level, node_path,
                'stock_ok', _('En stock (%g disponibles)') % stock_avail,
            ))
            return

        remaining_qty = comp_qty
        if stock_avail > 0:
            # Stock parcial: mostrar lo disponible y producir/comprar el resto
            used[comp.id] = used.get(comp.id, 0.0) + stock_avail
            parent['children'].append(self._stock_node(
                comp, stock_avail, level, node_path,
                'stock_partial', _('Stock parcial: %g de %g') % (stock_avail, comp_qty),
            ))
            remaining_qty = comp_qty - stock_avail

        # 4. Método de abastecimiento del remanente.
        method = self._get_supply_method(comp, cache=caches['supply'])

        if method == 'manufacture':
            child = self._build_demand_tree(comp, remaining_qty, level, visited,
                                            caches, path=parent_path)
            if child:
                parent['children'].append(child)
        elif method in ('subcontract', 'buy'):
            parent['children'].append(self._purchase_node(
                comp, remaining_qty, method, level, node_path,
            ))
        # method == 'stock' y sin stock: componente sin método conocido → omitir

    def _explode_phantom(self, parent, kit, kit_bom, kit_qty, level, kit_path, visited, caches):
        """Explota las líneas de un kit phantom en el nodo padre.

        Cada sub-componente del kit se procesa como si fuera un componente directo
        del padre (mismo nivel), replicando el comportamiento de Odoo al explotar
        kits: el kit no genera una OF propia, solo aporta sus componentes.

        :param parent: dict — nodo padre donde se cuelgan los sub-componentes.
        :param kit: product.product — producto kit (phantom).
        :param kit_bom: mrp.bom — LdM phantom del kit.
        :param kit_qty: float — cantidad de kit requerida, en su UoM de stock.
        :param level: int — nivel de los sub-componentes en el árbol.
        :param kit_path: list — path de product_ids raíz→kit.
        :param visited: set — productos visitados en la rama (evita ciclos).
        :param caches: dict — cachés compartidos (ver _new_caches).
        """
        if kit.id in visited:
            return
        visited = visited | {kit.id}

        factor = self._bom_factor(kit, kit_qty, kit_bom)
        self._prefetch_level_caches(kit_bom, caches)
        for line in kit_bom.bom_line_ids:
            sub     = line.product_id
            sub_qty = self._bom_line_qty(line, factor)
            self._expand_component(parent, sub, sub_qty, level,
                                   kit_path, visited, caches)
