"""
Módulo: mrp_production_request_line.py
Modelo: mrp.production.request.line / mrp.production.request.wc

Líneas de detalle y cargas de centros de trabajo para solicitudes de programación MRP.

Responsabilidades:
- Representar cada ítem (fabricación, compra o stock) dentro de una solicitud de reprogramación.
- Calcular los centros de trabajo compatibles para cada producto, respetando la configuración
  de fallback del sistema.
- Registrar la carga horaria planificada por centro de trabajo en el horizonte de programación.

Relacionado con:
- mrp.production.request: cabecera de la solicitud a la que pertenecen estas líneas.
- mrp.production.request.item: artículo padre que originó la línea.
- mrp.workcenter: centros de trabajo disponibles para asignación y carga.
- product.product: producto que se va a fabricar, comprar o consumir desde stock.
- mrp.bom: lista de materiales asociada al producto de la línea.
"""
from odoo import models, fields, api


class MrpProductionRequestLine(models.Model):
    _name = 'mrp.production.request.line'
    _description = 'Línea de solicitud de programación'
    _order = 'sequence'

    request_id  = fields.Many2one(
        'mrp.production.request', required=True, ondelete='cascade',
        help='Solicitud de programación a la que pertenece esta línea.',
    )
    item_id     = fields.Many2one(
        'mrp.production.request.item', string='Artículo', ondelete='cascade',
        help='Artículo (producto raíz) que originó esta línea de detalle.',
    )
    sequence    = fields.Integer(
        default=10,  # 10 como base permite insertar líneas intermedias sin reordenar todo
        help='Orden de visualización dentro de la solicitud.',
    )
    level       = fields.Integer(
        default=0,  # 0 = nivel raíz; valores positivos indican profundidad en la explosión de LdM
        help='Profundidad en la jerarquía de explosión de lista de materiales.',
    )
    record_type = fields.Selection(
        [('mrp', 'Fabricación'), ('purchase', 'Compra'), ('stock', 'Stock')],
        string='Tipo registro', default='mrp',
        help='Naturaleza de la operación: orden de fabricación, orden de compra o consumo de stock.',
    )

    product_id  = fields.Many2one(
        'product.product', string='Producto', required=True,
        help='Producto variante involucrado en esta línea de la solicitud.',
    )
    bom_id      = fields.Many2one(
        'mrp.bom', string='LdM',
        help='Lista de materiales utilizada para explotar este producto, si corresponde.',
    )
    product_qty = fields.Float(
        string='Cantidad', digits=(16, 2),
        help='Cantidad a fabricar, comprar o consumir para satisfacer la demanda planificada.',
    )
    duration_hours = fields.Float(
        string='Duración (hs)', digits=(10, 2),
        help='Tiempo estimado de producción en horas para esta línea.',
    )

    new_date_start  = fields.Datetime(
        string='Fecha inicio',
        help='Fecha y hora de inicio reprogramada para la operación.',
    )
    new_date_finish = fields.Datetime(
        string='Fecha fin',
        help='Fecha y hora de finalización reprogramada para la operación.',
    )
    workcenter_id   = fields.Many2one(
        'mrp.workcenter', string='Centro de trabajo',
        help='Centro de trabajo asignado para ejecutar esta operación.',
    )
    compatible_workcenter_ids = fields.Many2many(
        'mrp.workcenter', compute='_compute_compatible_wc_ids',
        help='Centros de trabajo habilitados para este producto según su configuración de compatibilidad.',
    )

    @api.depends('product_id')
    def _compute_compatible_wc_ids(self):
        """
        Calcula compatible_workcenter_ids para cada línea.

        Fórmula: lee los centros compatibles del campo x_centros_compatibles de la plantilla
        del producto (filtrados por activos). Si no hay centros definidos, aplica la política de
        fallback configurada en el parámetro del sistema 'mrp_reschedule.wc_fallback':
          - 'ldm' (por defecto): devuelve todos los centros activos del sistema.
          - 'none': no asigna ningún centro (lista vacía).
        Depende de: product_id → product_tmpl_id → x_centros_compatibles, active.
        """
        get_param = self.env['ir.config_parameter'].sudo().get_param
        fallback = get_param('mrp_reschedule.wc_fallback', 'ldm')
        # Se inicializa en None para diferir la consulta SELECT hasta que sea realmente necesaria
        # (lazy load), evitando una query si todas las líneas tienen centros propios definidos.
        all_wcs = None
        for line in self:
            if not line.product_id:
                line.compatible_workcenter_ids = self.env['mrp.workcenter']
                continue
            centros = line.product_id.product_tmpl_id.x_centros_compatibles.filtered('active')
            if centros:
                line.compatible_workcenter_ids = centros.mapped('workcenter_id')
            elif fallback == 'none':
                line.compatible_workcenter_ids = self.env['mrp.workcenter']
            else:
                # fallback == 'ldm': se permite usar cualquier centro del sistema
                if all_wcs is None:
                    all_wcs = self.env['mrp.workcenter'].search([])
                line.compatible_workcenter_ids = all_wcs

    workcenter_label  = fields.Char(
        string='WC / Proveedor',
        help='Etiqueta de presentación del centro de trabajo o proveedor según el tipo de línea.',
    )
    workcenter_chain  = fields.Char(
        string='Cadena WC', readonly=True,
        help='Secuencia concatenada de centros de trabajo involucrados en la ruta de fabricación.',
    )
    description_label = fields.Char(
        string='Producto',
        help='Etiqueta descriptiva del producto para mostrar en vistas de solo lectura.',
    )
    type_label        = fields.Char(
        string='Tipo',
        help='Etiqueta legible del tipo de operación (Fabricación, Compra, Stock) para la vista.',
    )

    warning_type = fields.Selection([
        ('', 'Ninguna'),
        ('stock_ok',      'Stock suficiente'),
        ('stock_partial', 'Stock parcial'),
    ], string='Tipo advertencia', default='',
        help='Indica si el stock disponible cubre total o parcialmente la cantidad requerida.',
    )
    warning_message  = fields.Char(
        string='Advertencia',
        help='Mensaje descriptivo del estado de stock o cualquier condición que requiera atención.',
    )
    is_auto_reorder  = fields.Boolean(
        default=False,
        help='Verdadero si la reposición de este ítem fue disparada automáticamente por una regla de reabastecimiento.',
    )


class MrpProductionRequestWc(models.Model):
    """
    Registro de carga horaria por centro de trabajo dentro de una solicitud de programación.

    Cada instancia representa el bloque de tiempo que un centro de trabajo tiene asignado
    en el horizonte planificado para una solicitud concreta. Se usa para detectar conflictos
    de capacidad y visualizar la ocupación en el Gantt / dashboard de carga.
    """

    _name = 'mrp.production.request.wc'
    _description = 'Carga de centro de trabajo en programación'
    _order = 'date_start, id'

    request_id    = fields.Many2one(
        'mrp.production.request', required=True, ondelete='cascade',
        help='Solicitud de programación que genera esta carga en el centro de trabajo.',
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Centro de trabajo', required=True,
        help='Centro de trabajo que absorbe las horas planificadas de esta entrada.',
    )
    total_hours   = fields.Float(
        string='Horas totales', digits=(10, 2),
        help='Cantidad total de horas asignadas a este centro en el bloque de tiempo definido.',
    )
    date_start    = fields.Datetime(
        string='Inicio',
        help='Fecha y hora de inicio del bloque de trabajo planificado.',
    )
    date_end      = fields.Datetime(
        string='Fin',
        help='Fecha y hora de finalización del bloque de trabajo planificado.',
    )
