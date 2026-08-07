"""
Módulo: purchase_order.py
Modelo: extensión de purchase.order

Extiende el modelo nativo de órdenes de compra para integrar alertas de
reprogramación MRP cuando una OC es cancelada, marcada como hecha o su fecha
de entrega planificada cambia.

Responsabilidades:
- Disparar alertas críticas (po_cancelled) cuando una OC activa es cancelada.
- Resolver alertas de atraso (po_delayed) cuando una OC se completa o su fecha
  vuelve a ser futura.
- Marcar órdenes de producción relacionadas como necesitadas de reprogramación
  cuando la fecha de entrega de la OC se retrasa.

Relacionado con:
- mrp.reschedule.alert: crea y resuelve alertas de retraso/cancelación de OC.
- mrp.production: las MOs afectadas por la OC reciben x_reschedule_needed=True.
"""
import logging
from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        """
        Intercepta escrituras en purchase.order para sincronizar alertas MRP.

        Antes de delegar al super(), captura el estado previo de los registros
        que van a cambiar (fechas planificadas, estados) para poder comparar
        después de la escritura y determinar si hay alertas que crear o resolver.

        Flujo por caso:
        - Cancelación: crea alerta crítica 'po_cancelled' y marca MOs impactadas.
        - Completado ('done'): resuelve alertas 'po_delayed' y 'po_cancelled'.
        - Cambio de fecha: resuelve 'po_delayed' si la nueva fecha es futura;
          marca MOs si la fecha se alejó respecto a la anterior.

        :param vals: dict con los valores a escribir (estándar Odoo ORM)
        :returns: bool — resultado del super().write(vals)
        """
        track_cancel = vals.get('state') == 'cancel'
        track_done   = vals.get('state') == 'done'
        track_date   = 'date_planned' in vals

        if track_cancel:
            # Capturar antes del write porque después el estado ya será 'cancel'
            pos_to_cancel = self.filtered(lambda p: p.state not in ('cancel', 'done'))
        if track_date:
            # Snapshot de fechas previas: necesario antes del write para detectar el delta
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
                    # Una OC completada cierra tanto la alerta de atraso como la de cancelación
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
        """Marca x_reschedule_needed=True en todas las MOs confirmadas/en-progreso vinculadas a esta OC."""
        MO = self.env['mrp.production']
        mo_fields = MO._fields
        # Solo MOs activas: 'done' y 'cancel' no tienen sentido reprogramar
        domain = [('state', 'in', ('confirmed', 'progress'))]
        or_clauses = []
        # Los campos de relación directa con OC son opcionales según la versión/módulo instalado
        if 'purchase_order_id' in mo_fields:
            or_clauses.append(('purchase_order_id', '=', po.id))
        if 'purchase_line_id' in mo_fields:
            or_clauses.append(('purchase_line_id.order_id', '=', po.id))
        if or_clauses:
            # Con dos cláusulas se necesita el operador '|' prefijo de Odoo (notación polaca)
            if len(or_clauses) == 2:
                domain = domain + ['|'] + or_clauses
            else:
                domain = domain + or_clauses
            mos = MO.search(domain)
            if mos:
                mos.write({'x_reschedule_needed': True})
