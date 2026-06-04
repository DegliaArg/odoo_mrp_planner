from odoo import models, fields, _
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_open_reschedule_wizard(self):
        """
        Abre el wizard de reprogramación en cascada.
        Soporta 0 o 1 registro seleccionado:
          - 0 seleccionados: el wizard abre vacío, el usuario elige la orden pivot.
          - 1 seleccionado: el wizard se pre-completa con esa orden.
          - 2+: se lanza un error.
        """
        if len(self) > 1:
            raise UserError(_(
                'Seleccione una única orden de fabricación como punto de inicio '
                'de la reprogramación, o no seleccione ninguna para elegirla '
                'dentro del asistente.'
            ))

        ctx = {}

        if self:
            # Calcular fecha de fin real desde las WOs terminadas
            done_wos = self.workorder_ids.filtered(
                lambda w: w.state == 'done' and w.date_finished
            )
            finish_dates = [w.date_finished for w in done_wos]
            if finish_dates:
                new_finish = max(finish_dates)
            elif self.date_finished:
                new_finish = self.date_finished
            else:
                new_finish = fields.Datetime.now()

            ctx['default_production_id'] = self.id
            ctx['default_new_finish_date'] = new_finish
        else:
            ctx['default_new_finish_date'] = fields.Datetime.now()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Reprogramar en cascada'),
            'res_model': 'mrp.reschedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }
