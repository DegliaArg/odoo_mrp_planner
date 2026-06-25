from odoo import models, fields


class MrpRescheduleUserPermission(models.Model):
    _name = 'mrp.reschedule.user.permission'
    _description = 'Permiso de usuario en el planificador'
    _rec_name = 'user_id'

    config_id = fields.Many2one(
        'mrp.reschedule.config',
        required=True,
        ondelete='cascade',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        required=True,
        ondelete='cascade',
        domain=[('share', '=', False)],
    )

    # ── Secciones visibles ───────────────────────────────────────────────────

    show_alerts       = fields.Boolean(string='Alertas',                  default=True)
    show_mo           = fields.Boolean(string='Órdenes de fabricación',   default=True)
    show_wc           = fields.Boolean(string='Centros de trabajo',       default=True)
    show_po           = fields.Boolean(string='Órdenes de compra',        default=True)
    show_stock_breaks = fields.Boolean(string='Quiebres de stock',        default=True)

    # ── Acciones habilitadas ─────────────────────────────────────────────────

    can_schedule      = fields.Boolean(string='Puede programar',          default=True)
    can_reschedule    = fields.Boolean(string='Puede reprogramar',        default=True)

    show_forecast      = fields.Boolean(string='Forecast',                 default=True)
    can_edit_forecast  = fields.Boolean(string='Puede editar forecast',    default=True)

    # ── Filtro por depósito ──────────────────────────────────────────────────

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Depósitos visibles',
        help='Dejar vacío para ver todos los depósitos.',
    )
