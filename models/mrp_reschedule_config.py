from odoo import models, fields, api


class MrpRescheduleConfig(models.Model):
    _name = 'mrp.reschedule.config'
    _description = 'Configuración del planificador de producción'

    wc_fallback = fields.Selection([
        ('ldm', 'Usar operaciones de la Lista de Materiales'),
        ('none', 'Sin centro de trabajo'),
    ], string='Fallback de centro de trabajo', default='ldm', required=True)

    priority = fields.Selection([
        ('chronological', 'Orden cronológico (fecha actual)'),
        ('shortest_first', 'Más cortas primero (SPT)'),
        ('manual', 'Secuencia manual en el wizard'),
    ], string='Criterio de prioridad al reprogramar', default='chronological', required=True)

    def write(self, vals):
        res = super().write(vals)
        sp = self.env['ir.config_parameter'].sudo()
        if 'wc_fallback' in vals:
            sp.set_param('mrp_reschedule.wc_fallback', vals['wc_fallback'])
        if 'priority' in vals:
            sp.set_param('mrp_reschedule.priority', vals['priority'])
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        sp = self.env['ir.config_parameter'].sudo()
        for rec in records:
            sp.set_param('mrp_reschedule.wc_fallback', rec.wc_fallback)
            sp.set_param('mrp_reschedule.priority', rec.priority)
        return records
