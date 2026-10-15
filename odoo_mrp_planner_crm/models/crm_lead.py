"""
Módulo: crm_lead.py (odoo_mrp_planner_crm)
Modelo: extensión de 'crm.lead'

Expone en el formulario de la oportunidad, junto a los datos del cliente, dos
datos comerciales del contacto (campos related, SOLO lectura):

- Condición de pago  -> partner_id.property_payment_term_id (account)
- Lista de precios   -> partner_id.property_product_pricelist (product)
  ("descuento comercial" en la operatoria del cliente).

Los demás "Datos del cliente" de la propuesta (contacto, mail, teléfono) ya los
muestra el form nativo del lead, por lo que no se replican.
"""
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    x_partner_payment_term_id = fields.Many2one(
        related='partner_id.property_payment_term_id',
        string='Condición de pago',
        readonly=True,
    )
    x_partner_pricelist_id = fields.Many2one(
        related='partner_id.property_product_pricelist',
        string='Lista de precios',
        readonly=True,
    )
