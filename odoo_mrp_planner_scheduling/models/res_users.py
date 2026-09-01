"""
Módulo: res_users.py (odoo_mrp_planner_scheduling)
Modelo: extensión de res.users

Valida la asignación del grupo de Programación cuando la función está
deshabilitada y expone el flag de programación habilitada para las vistas.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    mrp_scheduling_enabled = fields.Boolean(
        compute='_compute_mrp_scheduling_enabled',
        string='Programación MRP habilitada',
    )

    # El valor depende de la config de la empresa activa (get_config resuelve por
    # self.env.company), no de un campo del usuario: se depende del contexto de
    # empresa para cachear/recalcular por compañía.
    @api.depends_context('company')
    def _compute_mrp_scheduling_enabled(self):
        cfg = self.env['mrp.reschedule.config'].get_config()
        enabled = bool(cfg.enable_scheduling) if cfg else False
        for user in self:
            user.mrp_scheduling_enabled = enabled

    @api.constrains('groups_id')
    def _check_scheduling_group_assignment(self):
        # Durante instalación/actualización (modo superusuario) no se valida: Odoo
        # re-propaga los grupos implícitos al cargar los datos y esta restricción de
        # UI no debe abortar el upgrade.
        if self.env.su:
            return
        scheduling_group = self.env.ref('odoo_mrp_planner_scheduling.group_scheduling', raise_if_not_found=False)
        if not scheduling_group:
            return
        cfg = self.env['mrp.reschedule.config'].get_config()
        if not cfg or cfg.enable_scheduling:
            return
        # Los administradores del módulo (y del sistema) conservan la programación aunque
        # esté desactivada: group_admin IMPLICA group_scheduling, por lo que bloquearlos
        # contradiría ese diseño y rompería el upgrade. Solo se bloquea a usuarios no-admin.
        admin_group  = self.env.ref('odoo_mrp_planner.group_admin', raise_if_not_found=False)
        system_group = self.env.ref('base.group_system', raise_if_not_found=False)
        for user in self:
            if scheduling_group not in user.groups_id:
                continue
            if admin_group and admin_group in user.groups_id:
                continue
            if system_group and system_group in user.groups_id:
                continue
            raise ValidationError(
                'No se puede asignar el permiso "Programación" porque la '
                'programación está deshabilitada. Habilítela primero desde '
                'Configuración → Planificador MRP → Programación y reprogramación.'
            )
