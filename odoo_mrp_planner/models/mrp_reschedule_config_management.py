# Copyright (C) 2024 - MRP Planner
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""
Módulo: mrp_reschedule_config_management.py
Modelo: extensión de mrp.reschedule.config

Campos de configuración de la sección Gerencia (Resumen diario): qué
tipos de operación (stock.picking.type) alimentan cada indicador de movimiento
del panel. Son IDs específicos de cada base, por eso se configuran acá en vez
de hardcodearlos.

Relacionado con:
- mrp.reschedule.config: modelo base que este archivo extiende vía _inherit
  (mismo patrón que mrp_reschedule_config_forecast/categories/inventory).
- mrp_planner_dashboard_management.get_management_overview: consume estos campos.
"""
from odoo import models, fields


class MrpRescheduleConfigManagement(models.Model):
    _inherit = 'mrp.reschedule.config'

    management_dispatch_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_dispatch_rel', 'config_id', 'picking_type_id',
        string='Despachos — Tipos de operación',
        help='Tipos de operación que se cuentan como DESPACHOS del mes en el '
             'Resumen diario (transferencias validadas / estado Hecho). '
             'La cantidad se mide en piezas movidas.',
    )
    management_packing_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_packing_rel', 'config_id', 'picking_type_id',
        string='Embalajes — Tipos de operación',
        help='Tipos de operación que se cuentan como EMBALAJES pendientes en el '
             'Resumen diario (transferencias en estado Listo/Asignado). '
             'Es una foto del pendiente actual: muestra las piezas listas para embalar ahora.',
    )
    management_picking_picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'mrp_resched_cfg_mgmt_picking_rel', 'config_id', 'picking_type_id',
        string='Picking — Tipos de operación',
        help='Tipos de operación que se cuentan como PICKING pendiente en el '
             'Resumen diario (transferencias en estado Listo/Asignado). '
             'Es una foto del pendiente actual: muestra las piezas listas para pickear ahora.',
    )
    management_production_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'mrp_resched_cfg_mgmt_prod_wh_rel', 'config_id', 'warehouse_id',
        string='Producido — Depósitos',
        help='Si se indican, el indicador de PRODUCIDO del Resumen diario solo '
             'cuenta OFs cuyo depósito (el del tipo de operación de la OF) esté '
             'entre estos. Vacío = todos los depósitos.',
    )
