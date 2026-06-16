import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        track_cancel = vals.get('state') == 'cancel'
        track_done   = vals.get('state') == 'done'
        track_date   = 'date_planned' in vals

        if track_cancel:
            pos_to_cancel = self.filtered(lambda p: p.state not in ('cancel', 'done'))
        if track_date:
            old_dates = {po.id: po.date_planned for po in self}

        result = super().write(vals)

        alert_env = self.env['mrp.reschedule.alert']
        now = fields.Datetime.now()

        if track_cancel:
            for po in pos_to_cancel:
                try:
                    # Resolver alerta de atraso al cancelar
                    alert_env._resolve_for(('po_delayed',), purchase_id=po.id)
                    # Crear alerta de cancelación
                    product_ids = po.order_line.mapped('product_id').ids
                    impacted = self.env['mrp.production']
                    for pid in product_ids:
                        product = self.env['product.product'].browse(pid)
                        impacted |= alert_env._find_impact_mos(pid, product.qty_available)
                    alert_env._upsert_alert(
                        'po_cancelled', 'critical', 0,
                        _('OC %s cancelada') % po.name,
                        purchase_id=po.id,
                        impact_mo_ids=impacted.ids,
                    )
                    if impacted:
                        impacted.write({'x_reschedule_needed': True})
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al procesar cancelación de OC %s: %s',
                        po.name, e,
                    )

        if track_done:
            for po in self:
                try:
                    alert_env._resolve_for(('po_delayed', 'po_cancelled'), purchase_id=po.id)
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al resolver alertas de OC %s: %s', po.name, e,
                    )

        if track_date:
            for po in self:
                try:
                    # Si la nueva fecha es futura, resolver alerta de atraso
                    if po.date_planned and po.date_planned > now:
                        alert_env._resolve_for(('po_delayed',), purchase_id=po.id)
                    # Si la fecha se atrasó, marcar MOs afectadas
                    old_dt = old_dates.get(po.id)
                    if old_dt and po.date_planned and po.date_planned > old_dt:
                        self._flag_mos_for_po(po)
                except Exception as e:
                    _logger.warning(
                        'MRP Reschedule: error al procesar cambio de fecha de OC %s: %s',
                        po.name, e,
                    )

        return result

    def _flag_mos_for_po(self, po):
        """Marca x_reschedule_needed en MOs relacionadas a esta OC."""
        MO = self.env['mrp.production']
        mo_fields = MO._fields
        domain = [('state', 'in', ('confirmed', 'progress'))]
        or_clauses = []
        if 'purchase_order_id' in mo_fields:
            or_clauses.append(('purchase_order_id', '=', po.id))
        if 'purchase_line_id' in mo_fields:
            or_clauses.append(('purchase_line_id.order_id', '=', po.id))
        if or_clauses:
            if len(or_clauses) == 2:
                domain = domain + ['|'] + or_clauses
            else:
                domain = domain + or_clauses
            mos = MO.search(domain)
            if mos:
                mos.write({'x_reschedule_needed': True})
