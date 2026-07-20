"""
Mixin: MrpDemandExpansionMixin — expansión del árbol de demanda (BOM, rutas, WC).

Responsabilidades:
- Determinar el método de abastecimiento de cada producto (fabricar, comprar,
  subcontratar, stock).
- Buscar la LdM aplicable y calcular duraciones de operaciones escaladas.
- Construir recursivamente el árbol de demanda multinivel (dict por nodo).
- Aplicar overrides manuales de centros de trabajo sobre el árbol ya construido.
- Resolver el WC preferido para un producto desde x_centros_compatibles.
- Retornar el start más temprano del árbol para el artículo.
"""
import logging
from datetime import timedelta

from odoo import models, _
from odoo.exceptions import UserError

from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import INDENT_MAP

_logger = logging.getLogger(__name__)


class MrpDemandExpansionMixin(models.AbstractModel):
    _name = 'mrp.demand.expansion.mixin'
    _description = 'Mixin de expansión del árbol de demanda'

    # ── Rutas y método de abastecimiento ─────────────────────────────────────

    def _get_supply_method(self, product):
        """
        Determina cómo se abastece un producto según las rutas configuradas.

        Evalúa en orden de prioridad:
        1. Subcontratación: existe LdM de tipo 'subcontract'.
        2. Fabricación: alguna regla de ruta tiene action == 'manufacture'.
        3. Compra: alguna regla de ruta tiene action == 'buy'.
        4. Fallback por BOM genérica o purchase_ok.

        :param product: product.product — producto a evaluar.
        :returns: str — 'subcontract' | 'manufacture' | 'buy' | 'stock'.
        """
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
            return 'subcontract'

        # Rutas configuradas en el producto/categoría
        # Usar rule.action (campo semántico de Odoo 18) en lugar de picking_type_id.code,
        # que no es confiable con rutas personalizadas (ej. "Mecanizado: suministrar…").
        found = set()
        routes = product.route_ids | product.categ_id.total_route_ids
        for route in routes:
            for rule in route.rule_ids.filtered('active'):
                if rule.action == 'manufacture':
                    found.add('manufacture')
                elif rule.action == 'buy':
                    found.add('buy')
        if 'manufacture' in found:
            return 'manufacture'
        if 'buy' in found:
            return 'buy'

        # Fallback
        if self._find_bom(product):
            return 'manufacture'
        if product.purchase_ok:
            return 'buy'
        return 'stock'

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

    def _find_bom(self, product):
        """Busca la LdM de fabricación activa para el producto dado.

        Intenta primero con el método oficial _bom_find de Odoo (robusto pero
        puede lanzar excepciones en versiones con API inestable); si falla,
        realiza una búsqueda directa excluyendo tipos 'phantom' y 'subcontract'.

        :param product: product.product — producto para el que se busca la LdM.
        :returns: mrp.bom — primera LdM encontrada, o recordset vacío si no existe.
        """
        try:
            result = self.env['mrp.bom']._bom_find(product, company_id=self.env.company.id)
            bom = result.get(product) if isinstance(result, dict) else result
            if bom:
                return bom
        except Exception:
            pass
        return self.env['mrp.bom'].search([
            ('type', 'not in', ['phantom', 'subcontract']),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ], limit=1, order='sequence, id')

    def _get_op_duration_hours(self, op, bom_factor):
        """Calcula la duración en horas de una operación de LdM escalada por bom_factor.

        Prioriza time_cycle_manual (ajuste manual) sobre time_cycle (calculado);
        si ambos son cero usa 60 minutos como mínimo operativo.

        :param op: mrp.routing.workcenter — operación de la LdM.
        :param bom_factor: float — factor de escala (qty_solicitada / bom.product_qty).
        :returns: float — duración en horas.
        """
        dur_min = (
            getattr(op, 'time_cycle_manual', None)
            or getattr(op, 'time_cycle', None)
            or 60.0
        )
        return dur_min * bom_factor / 60.0

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

    def _apply_wc_overrides(self, node, item_id, overrides):
        """Aplica los centros de trabajo editados manualmente al árbol de demanda.

        Reemplaza las operaciones del nodo con el WC guardado en overrides para la
        combinación (item_id, product.id, level). La duración total se preserva.

        :param node: dict — nodo del árbol a procesar (se modifica en-place).
        :param item_id: int — ID del mrp.production.request.item al que pertenece el árbol.
        :param overrides: dict — {(item_id, product_id, level): workcenter} con los overrides.
        """
        if node.get('type') == 'manufacture' and node.get('operations'):
            key = (item_id, node['product'].id, node['level'])
            if key in overrides:
                wc = overrides[key]
                dur_h = sum(d for _, d in node['operations'])
                node['operations'] = [(wc, dur_h)]
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

    def _build_demand_tree(self, product, qty, level, visited=None):
        """
        Construye recursivamente el árbol de demanda multinivel para un producto.

        Cada nodo del árbol es un dict con las claves: type, product, qty, bom,
        level, operations, children, scheduled_start, scheduled_end.
        Los tipos de nodo posibles son:
          - 'manufacture': se debe fabricar (nodo interno, puede tener hijos).
          - 'buy' / 'subcontract': se debe comprar/subcontratar (nodo hoja).
          - 'stock': cubierto por stock existente o reorden automático (nodo hoja).

        Para cada componente de la LdM se evalúa stock disponible primero; si
        hay stock parcial se genera un nodo stock por la parte cubierta y se
        continúa con el método de abastecimiento para el remanente.

        :param product: product.product — producto raíz o componente a evaluar.
        :param qty: float — cantidad necesaria a producir/abastecer.
        :param level: int — profundidad en el árbol (0 = artículo raíz de la solicitud).
        :param visited: set | None — productos ya visitados en la rama actual (evita ciclos).
        :returns: dict | None — nodo raíz del árbol, o None si no existe LdM fabricable.
        """
        if visited is None:
            visited = set()
        if product.id in visited:
            return None
        visited = visited | {product.id}

        bom = self._find_bom(product)
        if not bom or bom.type == 'phantom':
            return None  # No se puede fabricar el artículo raíz

        # Factor de corrección: cuántas corridas de LdM se necesitan para qty unidades.
        # bom.product_qty es cuántas unidades produce una corrida de la LdM.
        bom_factor = qty / (bom.product_qty or 1.0)

        preferred_wc = self._get_preferred_workcenter(product)
        # sudo(): ir.config_parameter solo es legible con permisos de admin; usuarios de wizard no lo tienen
        wc_fallback = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.wc_fallback', 'ldm'
        )
        operations = []
        dur_bom = (
            sum(self._get_op_duration_hours(op, bom_factor) for op in bom.operation_ids)
            if bom.operation_ids else 8.0
        )
        if preferred_wc:
            operations = [(preferred_wc, dur_bom)]
        elif bom.operation_ids and wc_fallback == 'ldm':
            for op in bom.operation_ids.sorted('sequence'):
                operations.append((op.workcenter_id, self._get_op_duration_hours(op, bom_factor)))
        else:
            operations = [(None, dur_bom)]

        node = {
            'type':     'manufacture',
            'product':  product,
            'qty':      qty,
            'bom':      bom,
            'level':    level,
            'operations': operations,
            'children': [],
            'scheduled_start': None,
            'scheduled_end':   None,
        }

        for bom_line in bom.bom_line_ids:
            comp     = bom_line.product_id
            comp_qty = bom_line.product_qty * bom_factor

            # Productos con regla de reorden automática: el sistema los repone solo.
            # Generar un único nodo stock_ok para la cantidad total y saltar.
            if self.env['stock.warehouse.orderpoint'].search([
                ('product_id', '=', comp.id),
                ('active',     '=', True),
                ('trigger',    '=', 'auto'),
            ], limit=1):
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             comp_qty,
                    'level':           level + 1,
                    'warning_type':    'stock_ok',
                    'warning_message': 'Reposición automática (mín/máx)',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                continue

            # Verificar stock disponible antes de decidir el método de abastecimiento
            stock_avail = comp.qty_available or 0.0

            if stock_avail >= comp_qty:
                # Completamente cubierto por stock existente
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             comp_qty,
                    'level':           level + 1,
                    'warning_type':    'stock_ok',
                    'warning_message': f'En stock ({stock_avail:g} disponibles)',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                continue

            remaining_qty = comp_qty
            if stock_avail > 0:
                # Stock parcial: mostrar lo disponible y producir/comprar el resto
                node['children'].append({
                    'type':            'stock',
                    'product':         comp,
                    'qty':             stock_avail,
                    'level':           level + 1,
                    'warning_type':    'stock_partial',
                    'warning_message': f'Stock parcial: {stock_avail:g} de {comp_qty:g}',
                    'operations':      [],
                    'children':        [],
                    'scheduled_start': None,
                    'scheduled_end':   None,
                })
                remaining_qty = comp_qty - stock_avail

            method = self._get_supply_method(comp)

            if method == 'manufacture':
                child = self._build_demand_tree(comp, remaining_qty, level + 1, visited)
                if child:
                    node['children'].append(child)

            elif method in ('subcontract', 'buy'):
                lead_days    = self._get_purchase_lead_days(comp)
                seller_rec   = comp.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
                supplier_cal = self._get_supplier_calendar(
                    seller_rec.partner_id if seller_rec else self.env['res.partner']
                )
                node['children'].append({
                    'type':              method,
                    'product':           comp,
                    'qty':               remaining_qty,
                    'bom':               None,
                    'level':             level + 1,
                    'lead_days':         lead_days,
                    'supplier_name':     seller_rec.partner_id.display_name if seller_rec else '',
                    'supplier_calendar': supplier_cal,
                    'warning_type':      '',
                    'warning_message':   '',
                    'operations':        [],
                    'children':          [],
                    'scheduled_start':   None,
                    'scheduled_end':     None,
                })
            # method == 'stock' y sin stock: componente sin método conocido → omitir

        return node
