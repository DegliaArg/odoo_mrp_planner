"""
Módulo: mrp_reschedule_config.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.reschedule.config

Agrega el interruptor de la validación de despacho (por empresa), la lista
de tipos de operación que participan del circuito (para excluir salidas que
no son entregas a clientes, p. ej. transferencias entre depósitos) y el
marcado retroactivo: al activar la función, las salidas ya validadas que
nunca entraron al circuito se consideran despachadas, para que la cola de
"Sin despachar" arranque vacía en lugar de arrastrar todo el histórico.

Los ajustes del Panel de Inventario (registro de disponibilidad, corte de
antigüedad, redondeo) viven en el módulo base: este módulo solo suma el
circuito de despacho.
"""
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpRescheduleConfig(models.Model):
    _inherit = 'mrp.reschedule.config'

    enable_dispatch_validation = fields.Boolean(
        string='Habilitar validación de despacho',
        default=False,
        help='Activa el circuito de despacho en las órdenes de entrega de esta empresa: '
             'estado Sin despachar/Despachado, botón "Marcar despachado" (solo con el '
             'remito validado y para el grupo Inventario: validación de despacho) y '
             'filtros en la lista de salidas. Al activar, las salidas ya validadas que '
             'nunca entraron al circuito se marcan como despachadas.')
    dispatch_picking_type_ids = fields.Many2many(
        'stock.picking.type', 'mrp_config_dispatch_picking_type_rel',
        'config_id', 'picking_type_id',
        string='Tipos de operación con despacho',
        domain="[('code', '=', 'outgoing')]",
        help='Salidas que participan del circuito de despacho. Al activar la validación '
             'se precarga con todos los tipos de salida de la empresa: sacá los que no '
             'son entregas a clientes (p. ej. transferencias entre depósitos que usan '
             'un tipo de salida). Vacío = todas las salidas.')

    def _dispatch_mark_legacy(self):
        """Marca como despachadas las salidas validadas que nunca entraron al circuito.

        Solo toca remitos con estado de despacho VACÍO (anteriores al módulo o
        de tipos que estaban excluidos) y de los tipos de operación con
        despacho: lo que ya está "Sin despachar" conserva su estado real, así
        una desactivación temporal no borra la cola pendiente.
        """
        for rec in self:
            dom = [
                ('company_id', '=', rec.company_id.id),
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
                ('x_dispatch_state', '=', False),
            ]
            if rec.dispatch_picking_type_ids:
                dom.append(('picking_type_id', 'in', rec.dispatch_picking_type_ids.ids))
            legacy = self.env['stock.picking'].sudo().search(dom)
            if legacy:
                legacy.write({'x_dispatch_state': 'dispatched'})
                _logger.info('Despacho: %s salidas históricas de %s marcadas como despachadas.',
                             len(legacy), rec.company_id.name)

    def _dispatch_fill_default_types(self):
        """Precarga los tipos de operación con despacho al activar la función:
        todos los tipos de salida de la empresa. Solo si la lista está vacía,
        para no pisar una selección manual previa."""
        Type = self.env['stock.picking.type'].sudo()
        for rec in self:
            if not rec.dispatch_picking_type_ids:
                types = Type.search([
                    ('code', '=', 'outgoing'),
                    ('company_id', '=', rec.company_id.id),
                ])
                rec.dispatch_picking_type_ids = [(6, 0, types.ids)]

    def _dispatch_sync_types(self):
        """Alinea el estado de despacho de los remitos con la lista de tipos.

        Los tipos que ENTRAN reciben su estado: salidas validadas viejas →
        despachadas (misma regla que el marcado retroactivo, para que la cola
        arranque vacía) y salidas abiertas → "Sin despachar". Los tipos que
        SALEN quedan totalmente fuera del circuito: se limpian estado, fecha y
        usuario de despacho (la auditoría de los despachos reales queda en el
        chatter de cada remito).
        """
        self._dispatch_mark_legacy()
        Picking = self.env['stock.picking'].sudo()
        for rec in self:
            base = [('company_id', '=', rec.company_id.id),
                    ('picking_type_code', '=', 'outgoing')]
            types = rec.dispatch_picking_type_ids
            dom_in = base + [
                ('x_dispatch_state', '=', False),
                ('state', 'not in', ('done', 'cancel')),
            ]
            if types:
                dom_in.append(('picking_type_id', 'in', types.ids))
            entering = Picking.search(dom_in)
            if entering:
                entering.write({'x_dispatch_state': 'to_dispatch'})
            leaving = Picking.search(base + [
                ('picking_type_id', 'not in', types.ids),
                ('x_dispatch_state', '!=', False),
            ]) if types else Picking
            if leaving:
                leaving.write({
                    'x_dispatch_state':   False,
                    'x_dispatch_date':    False,
                    'x_dispatch_user_id': False,
                })
            if entering or leaving:
                _logger.info('Despacho: sincronización de tipos en %s — %s remito(s) '
                             'incorporado(s), %s excluido(s).',
                             rec.company_id.name, len(entering), len(leaving))

    def write(self, vals):
        res = super().write(vals)
        if vals.get('enable_dispatch_validation'):
            self._dispatch_fill_default_types()
        if vals.get('enable_dispatch_validation') or 'dispatch_picking_type_ids' in vals:
            self.filtered('enable_dispatch_validation')._dispatch_sync_types()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        enabled = records.filtered('enable_dispatch_validation')
        enabled._dispatch_fill_default_types()
        enabled._dispatch_sync_types()
        return records
