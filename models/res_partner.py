"""
Módulo: res_partner.py
Modelo: extensión de 'res.partner'

Extiende el modelo de contactos (clientes y proveedores) con campos de
clasificación ABC propios del planificador MRP y flags de visibilidad que
reflejan la configuración activa del módulo.

Responsabilidades:
- Agregar categorías A–E de proveedor y cliente al contacto.
- Exponer flags booleanos de visibilidad para que las vistas oculten o
  muestren esos campos según la configuración del planificador.

Relacionado con:
- mrp.reschedule.config: fuente de los flags enable_supplier_categories y
  enable_customer_categories que controlan la visibilidad de los campos.
- const.SALE_CAT_SELECTION: lista de valores A/B/C/D/E compartida con otros
  modelos del planificador.
"""
from odoo import models, fields, api
from odoo.addons.odoo_mrp_planner.models.const import SALE_CAT_SELECTION


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_supplier_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de proveedor',
        help='Clasificación A–E de calidad del proveedor.',
        index=True,
    )
    x_customer_category = fields.Selection(
        SALE_CAT_SELECTION,
        string='Categoría de cliente',
        help='Clasificación A–E de calidad del cliente.',
        index=True,
    )

    mrp_enable_supplier_cat = fields.Boolean(
        compute='_compute_mrp_cat_flags',
        help='Indica si la categoría de proveedor está habilitada en la '
             'configuración del planificador. Usado para ocultar/mostrar el '
             'campo x_supplier_category en las vistas.',
    )
    mrp_enable_customer_cat = fields.Boolean(
        compute='_compute_mrp_cat_flags',
        help='Indica si la categoría de cliente está habilitada en la '
             'configuración del planificador. Usado para ocultar/mostrar el '
             'campo x_customer_category en las vistas.',
    )

    # Usar @api.depends con la ruta cross-model para que Odoo invalide el cache
    # cuando cambia la configuración del planificador.
    @api.depends_context('company')
    def _compute_mrp_cat_flags(self):
        """
        Calcula mrp_enable_supplier_cat y mrp_enable_customer_cat para cada registro.

        Fórmula: lee los flags enable_supplier_categories / enable_customer_categories
        del único registro de mrp.reschedule.config existente; si no hay
        configuración creada aún, ambos flags quedan en False.
        Depende de: contexto de compañía (company); los cambios en
        mrp.reschedule.config invalidan el caché vía depends_context.
        """
        config = self.env['mrp.reschedule.config'].sudo().get_config()
        enable_sup  = config.enable_supplier_categories if config else False
        enable_cust = config.enable_customer_categories if config else False
        for rec in self:
            rec.mrp_enable_supplier_cat = enable_sup
            rec.mrp_enable_customer_cat = enable_cust
