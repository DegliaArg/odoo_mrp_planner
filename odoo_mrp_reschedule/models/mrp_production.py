from odoo import models, fields, api, _

import logging
_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # ── Fase 2: vínculo tipado a la OF madre ────────────────────────────────

    x_parent_mo_id = fields.Many2one(
        'mrp.production',
        string='OF madre',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
        help='Vínculo tipado a la orden de fabricación que generó esta. '
             'Más confiable que el campo Origen (texto).',
    )

    # ── Fase 4: flag de reprogramación sugerida ──────────────────────────────

    x_reschedule_needed = fields.Boolean(
        string='Reprogramación sugerida',
        copy=False,
        help='Indica que un cambio reciente en esta orden puede afectar '
             'la programación de las órdenes subsecuentes. '
             'Se limpia automáticamente al abrir el wizard.',
    )

    # ── Fase 4: override de write() para detección semi-automática ───────────

    def write(self, vals):
        """
        Detecta cambios de estado relevantes (done / cancel) y marca las MOs
        subsecuentes en los mismos WC para que muestren el botón de
        reprogramación sugerida.
        """
        trigger = 'state' in vals and vals['state'] in ('done', 'cancel')

        if trigger:
            old_states = {mo.id: mo.state for mo in self}

        result = super().write(vals)

        if trigger:
            for mo in self:
                old_state = old_states.get(mo.id, mo.state)
                if old_state not in ('done', 'cancel'):
                    try:
                        self._flag_subsequent_mos(mo)
                    except Exception as e:
                        _logger.warning(
                            'MRP Reschedule: error al marcar MOs subsecuentes '
                            'de %s: %s', mo.name, e
                        )
        return result

    def _flag_subsequent_mos(self, mo):
        """
        Busca MOs subsecuentes en los mismos WC y activa x_reschedule_needed.
        Solo busca las más próximas (limit=20) para no afectar el rendimiento.
        """
        if not mo.date_start:
            return
        wc_ids = mo.workorder_ids.mapped('workcenter_id').ids
        if not wc_ids:
            return
        subsequent = self.env['mrp.production'].search([
            ('id', '!=', mo.id),
            ('state', 'not in', ['done', 'cancel']),
            ('date_start', '>=', mo.date_start),
            ('workorder_ids.workcenter_id', 'in', wc_ids),
        ], limit=20)
        if subsequent:
            # Escribir directamente en la DB para evitar trigger recursivo
            subsequent.write({'x_reschedule_needed': True})

    # ── Acción del botón Reprogramar ─────────────────────────────────────────

    def action_open_reschedule_wizard(self):
        """
        Abre el wizard de reprogramación. Funciona desde:
          - La vista lista (Acción → botón servidor).
          - El botón inteligente en el form (cuando x_reschedule_needed=True).
        """
        production_ids = self.env.context.get('active_ids', self.ids)
        if not production_ids:
            return
        pivot = self.browse(production_ids[0])

        # Limpiar el flag al abrir el wizard
        pivot.write({'x_reschedule_needed': False})

        wizard = self.env['mrp.reschedule.wizard'].create({
            'production_id': pivot.id,
            'new_finish_date': pivot.date_finished or fields.Datetime.now(),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reprogramar en cascada'),
            'res_model': 'mrp.reschedule.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
