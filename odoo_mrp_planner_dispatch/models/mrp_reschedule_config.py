"""
Módulo: mrp_reschedule_config.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.reschedule.config

Agrega el interruptor de la validación de despacho (por empresa) y el
marcado retroactivo: al activar la función, las salidas ya validadas que
nunca entraron al circuito se consideran despachadas, para que la cola de
"Sin despachar" arranque vacía en lugar de arrastrar todo el histórico.
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

    def _dispatch_mark_legacy(self):
        """Marca como despachadas las salidas validadas que nunca entraron al circuito.

        Solo toca remitos con estado de despacho VACÍO (anteriores al módulo):
        lo que ya está "Sin despachar" conserva su estado real, así una
        desactivación temporal no borra la cola pendiente.
        """
        for rec in self:
            legacy = self.env['stock.picking'].sudo().search([
                ('company_id', '=', rec.company_id.id),
                ('picking_type_code', '=', 'outgoing'),
                ('state', '=', 'done'),
                ('x_dispatch_state', '=', False),
            ])
            if legacy:
                legacy.write({'x_dispatch_state': 'dispatched'})
                _logger.info('Despacho: %s salidas históricas de %s marcadas como despachadas.',
                             len(legacy), rec.company_id.name)

    def write(self, vals):
        res = super().write(vals)
        if vals.get('enable_dispatch_validation'):
            self._dispatch_mark_legacy()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('enable_dispatch_validation')._dispatch_mark_legacy()
        return records
