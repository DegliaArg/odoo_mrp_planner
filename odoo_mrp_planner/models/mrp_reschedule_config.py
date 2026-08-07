"""
Módulo: mrp_reschedule_config.py
Modelo: mrp.reschedule.config

Singleton (por empresa) de configuración central del planificador MRP:
definición del modelo, alertas, análisis de proveedores y de clientes,
quiebres de stock, registro de ejecuciones, permisos de edición y la
sincronización con los ir.cron del módulo al guardar.

Los demás dominios de configuración extienden este modelo por archivo
(mismo patrón que mrp_partner_category.py):
- mrp_reschedule_config_forecast.py: forecast, comparativa y carga de CT.
- mrp_reschedule_config_categories.py: categorías A–E de venta/proveedor/
  cliente, umbrales Pareto y RFM, crons de recálculo.
- mrp_reschedule_config_inventory.py: Panel de Inventario (snapshots de
  disponibilidad, corte de antigüedad, redondeo).
- odoo_mrp_planner_scheduling agrega los campos de programación
  (enable_scheduling, wc_fallback, priority) por herencia.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError


class MrpRescheduleConfig(models.Model):
    _name = 'mrp.reschedule.config'
    _description = 'Configuración del planificador de producción'
    _rec_name = 'name'
    _sql_constraints = [
        ('singleton', 'UNIQUE(singleton_check, company_id)',
         'Solo puede existir una configuración del planificador por empresa.'),
    ]

    singleton_check = fields.Boolean(default=True, string='Singleton')
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    name = fields.Char(compute='_compute_name', string='Nombre')

    # ── Alertas ──────────────────────────────────────────────────────────────

    cron_interval_number = fields.Integer(string='Revisar alertas cada', default=30,
        help='Frecuencia con que el cron de detección revisa las OFs y OCs '
             'para generar o resolver alertas automáticamente. '
             'Valores bajos = más reactivo, mayor carga en el servidor.')
    cron_interval_type = fields.Selection([
        ('minutes', 'Minutos'),
        ('hours', 'Horas'),
    ], string='Unidad del intervalo de alertas', default='minutes',
       help='Unidad de tiempo para el intervalo del cron de detección de retrasos. '
            'Combinar con "Cada" para definir la frecuencia total.')

    alert_mo_critical_days      = fields.Integer(string='Días críticos OF',             default=3,
        help='OFs cuya fecha de fin planificada está a ≤ estos días generan alerta crítica (rojo).')
    alert_po_critical_days      = fields.Integer(string='Días críticos OC',             default=5,
        help='OCs cuya fecha de entrega planificada está a ≤ estos días generan alerta crítica (rojo).')
    alert_receipt_critical_days = fields.Integer(string='Días críticos recepción',      default=3,
        help='Recepciones pendientes con fecha esperada a ≤ estos días generan alerta crítica (rojo).')
    alert_mo_warning_days       = fields.Integer(string='Días por vencer OF',           default=7,
        help='OFs cuya fecha de fin planificada está a ≤ estos días (y > días críticos) generan aviso (amarillo).')
    alert_po_warning_days       = fields.Integer(string='Días por vencer OC',           default=10,
        help='OCs cuya fecha de entrega planificada está a ≤ estos días (y > días críticos) generan aviso (amarillo).')
    qty_tolerance_pct           = fields.Float(  string='Tolerancia cantidad (%)',      default=5.0,
        help='Diferencia porcentual aceptable entre cantidad pedida y recibida antes de generar alerta de desvío de cantidad.')

    alert_delay_stat = fields.Selection([
        ('max', 'Máximo'),
        ('avg', 'Promedio'),
    ], string='Días de atraso en los KPIs', default='max',
       help='Estadístico de los días de atraso que acompaña a los conteos en los '
            'KPIs de alertas: la card "OFs atrasadas" del panel de Producción y la '
            'card "Vencidas" del panel de Compras.\n'
            'Máximo: el caso más urgente (cuántos días lleva el atraso más viejo).\n'
            'Promedio: el atraso medio del conjunto.')

    # (Los campos de forecast/comparativa/carga de CT viven en
    #  mrp_reschedule_config_forecast.py; los de categorías A–E en
    #  mrp_reschedule_config_categories.py; los del Panel de Inventario en
    #  mrp_reschedule_config_inventory.py.)

    # ── Quiebres de stock ────────────────────────────────────────────────────
    stock_break_show_rotation = fields.Boolean(
        string='Mostrar rotación en quiebres de stock', default=False,
        help='Si está activo, se muestra la columna de rotación de inventario en el widget de quiebres de stock.'
    )
    stock_break_rotation_method = fields.Selection([
        ('units', 'Por unidades'),
        ('cogs',  'Por COGS (a costo)'),
        ('sales', 'Por ventas (a precio)'),
    ], string='Método de rotación (quiebres)', default='units',
       help='Fórmula para calcular la rotación en el widget de quiebres de stock.\n'
            'Unidades: stock promedio del período ÷ (salidas del período ÷ meses). No requiere valorización.\n'
            'COGS: días × inventario promedio (a costo) ÷ costo de lo vendido. Requiere valorización activa.\n'
            'Ventas: días × inventario promedio (a costo) ÷ ventas netas (a precio).'
    )
    stock_break_rotation_months = fields.Integer(
        string='Período de rotación (meses)', default=3,
        help='Cantidad de meses de historial a considerar para calcular la rotación en el widget de quiebres de stock.'
    )
    stock_break_rotation_alerts_enabled = fields.Boolean(
        string='Mostrar alertas de rotación', default=False,
        help='Activa colores e ícono de advertencia en la columna de rotación según los umbrales configurados.'
    )
    stock_break_rotation_warn_days = fields.Integer(
        string='Rotación — umbral amarillo (días)', default=90,
        help='Rotación mayor a este valor → amarillo.'
    )
    stock_break_rotation_critical_days = fields.Integer(
        string='Rotación — umbral rojo (días)', default=180,
        help='Rotación mayor a este valor → rojo con ícono de advertencia.'
    )

    show_po_services_tab = fields.Boolean(
        string='Mostrar pestaña de servicios en OCs',
        default=False,
        help='Muestra u oculta la pestaña "Servicios" en las órdenes de compra. '
             'Útil para empresas que no gestionan servicios desde OCs y desean '
             'simplificar la interfaz.',
    )

    exclude_service_pos = fields.Boolean(
        string='Excluir OC de servicios de los KPIs',
        default=True,
        help='Cuando está activo, las OCs cuyas líneas son todas de tipo servicio '
             '(sin recepción de mercadería) se excluyen de los contadores KPI del '
             'panel de compras. Siguen visibles en la pestaña "Servicios" si está habilitada.',
    )

    supplier_analysis_date_field = fields.Selection([
        ('date_approve', 'Fecha de aprobación'),
        ('date_order',   'Fecha de pedido'),
        ('date_planned', 'Fecha de entrega planificada'),
    ], string='Fecha para análisis de proveedores', default='date_approve',
       help='Campo de fecha utilizado como referencia temporal al calcular métricas '
            'de proveedor (entregas a tiempo, retrasos, etc.). '
            '"Aprobación" es la fecha en que la OC fue confirmada por el proveedor; '
            '"Pedido" es cuando se generó la OC en Odoo; '
            '"Entrega planificada" es la fecha comprometida de recepción.')

    # ── Umbrales análisis de proveedores ──────────────────────────────────────
    sup_on_time_green_pct   = fields.Integer(string='% A tiempo — verde (≥)',       default=90,
        help='Umbral superior de puntualidad: proveedores con % de entregas a tiempo ≥ este valor se muestran en verde.')
    sup_on_time_yellow_pct  = fields.Integer(string='% A tiempo — amarillo (≥)',    default=70,
        help='Umbral intermedio de puntualidad: entre este valor y el verde se muestra en amarillo; por debajo en rojo.')
    sup_delay_green_days    = fields.Integer(string='Retraso — verde (≤ días)',      default=1,
        help='Retraso promedio aceptable: proveedores con retraso medio ≤ este valor se muestran en verde.')
    sup_delay_yellow_days   = fields.Integer(string='Retraso — amarillo (≤ días)',  default=3,
        help='Retraso promedio tolerable: entre el umbral verde y este valor se muestra en amarillo; por encima en rojo.')
    sup_complete_green_pct  = fields.Integer(string='% Completas — verde (≥)',      default=95,
        help='Umbral de completitud: % de recepciones sin diferencia de cantidad ≥ este valor se muestra en verde.')
    sup_complete_yellow_pct = fields.Integer(string='% Completas — amarillo (≥)',   default=80,
        help='Umbral intermedio de completitud: entre este valor y el verde se muestra en amarillo; por debajo en rojo.')
    sup_price_var_green_pct  = fields.Float( string='Var. precio — verde (|%| ≤)',  default=3.0,
        help='Variación de precio aceptable: |desviación| ≤ este % respecto a la referencia configurada '
             '(costo estándar, lista de proveedor o precio anterior pagado) se muestra en verde.')
    sup_price_var_yellow_pct = fields.Float( string='Var. precio — amarillo (|%| ≤)', default=10.0,
        help='Variación de precio tolerable: entre el umbral verde y este % se muestra en amarillo; por encima en rojo.')
    supplier_price_var_method = fields.Selection([
        ('standard',   'Costo estándar del producto'),
        ('pricelist',  'Lista de precio del proveedor'),
        ('previous',   'Precio anterior pagado'),
    ], string='Referencia para variación de precio', default='previous',
       help='Precio de referencia para calcular la variación de precio, tanto en el análisis de '
            'proveedores (columna) como en la clasificación ABC por variación de precio.\n'
            'Costo estándar: compara precio OC vs. standard_price del producto.\n'
            'Lista de precio del proveedor: compara precio OC vs. precio en product.supplierinfo. '
            'Si el proveedor no tiene precio configurado para ese producto, queda sin variación.\n'
            'Precio anterior pagado: compara cada compra con el precio de la compra anterior del '
            'mismo producto al mismo proveedor (tendencia de precio; no depende del costo estándar, '
            'que puede ser muy volátil).')

    # ── Registro de ejecuciones y análisis de clientes ──────────────────────
    run_log_keep = fields.Integer(
        string='Ejecuciones a conservar (por proceso)', default=100,
        help='Cantidad de corridas que guarda el Registro de ejecuciones por cada '
             'proceso y empresa (categorías, chequeo de alertas, importación de '
             'forecast). Al superar el límite se borran las más antiguas.')

    sales_amount_method = fields.Selection([
        ('pxq',  'PxQ a precio de lista'),
        ('real', 'Importe real de pedidos'),
    ], string='Valorización monetaria de ventas', default='pxq',
       help='Cómo se valorizan los montos del análisis de clientes.\n'
            'PxQ a precio de lista: cantidad × precio de venta ACTUAL de la ficha del '
            'artículo. Precios constantes: no lo afectan descuentos ni inflación, pero '
            'NO considera precios históricos ni cuadra con la facturación.\n'
            'Importe real: precio efectivo de cada línea de pedido (con descuentos, '
            'sin impuestos). Cuadra con los pedidos/facturación.')
    customer_analysis_exclude_services = fields.Boolean(
        string='Excluir servicios de los análisis de ventas',
        default=False,
        help='Cuando está activo, las líneas de productos de tipo Servicio no se '
             'cuentan ni en el análisis de clientes (montos, piezas, precio promedio, '
             'top de artículos) ni en el panel de ventas (Demanda real, Cumplimiento '
             'de demanda y los agregados "sin FC" que alimentan las tasas). Las '
             'entregas físicas no cambian: los servicios no generan remitos.')
    customer_unify_by_vat = fields.Boolean(
        string='Unificar clientes por CUIT',
        default=False,
        help='En el análisis de clientes, fusiona en una sola fila los contactos que '
             'comparten el mismo CUIT/NIF (razones sociales distintas del mismo cliente). '
             'Se muestran con el nombre de la razón social de mayor facturación del período. '
             'Los contactos sin CUIT no se unifican.')
    customer_analysis_ontime_method = fields.Selection([
        ('commitment_date', 'Fecha compromiso del pedido'),
        ('scheduled_date',  'Fecha programada del envío'),
        ('sla_days',        'Días desde confirmación del pedido'),
    ], string='Método "entrega a tiempo"', default='commitment_date',
       help='Define cómo se calcula si una entrega fue a tiempo.\n'
            '• Fecha compromiso: compara la fecha real de entrega con la fecha '
            'pactada con el cliente en el pedido de venta (campo commitment_date).\n'
            '• Fecha programada del envío: usa la fecha programada del picking de salida.\n'
            '• Días desde confirmación: considera a tiempo si se entregó dentro de N días '
            'desde la confirmación del pedido (configurable en "SLA en días").')
    customer_analysis_sla_days = fields.Integer(
        string='SLA en días', default=5,
        help='Solo aplica cuando el método es "Días desde confirmación". '
             'Define cuántos días tiene la empresa para entregar desde que se confirma el pedido.')
    customer_leadtime_method = fields.Selection([
        ('weighted', 'Ponderado por cantidades entregadas'),
        ('first',    'Primera entrega'),
        ('complete', 'Pedido completo'),
    ], string='Método — Lead time de entrega', default='weighted',
       help='Cómo se calcula el tiempo promedio de entrega de los pedidos con entregas '
            'parciales. Todos los métodos miden días desde la confirmación del pedido '
            'hasta la fecha efectiva de cada remito de salida.\n'
            '• Ponderado: promedia los días de cada parcial pesándolos por la cantidad '
            'entregada — cuántos días esperó la pieza promedio.\n'
            '• Primera entrega: días hasta el primer remito — velocidad de reacción.\n'
            '• Pedido completo: días hasta el remito que completó el pedido; solo cuenta '
            'pedidos totalmente entregados.\n'
            'El método elegido manda en el KPI y la columna; los otros dos se muestran '
            'como referencia secundaria y en el tooltip.')
    customer_analysis_delivery_warn_pct = fields.Integer(
        string='Tasas — umbral verde (%)', default=80,
        help='Desde este porcentaje, las tasas de entrega se muestran en verde. Aplica a las tasas del análisis de clientes y a las tasas física y de cumplimiento del panel de ventas.'
             'la celda se muestra en amarillo en el análisis de clientes.')
    customer_analysis_delivery_crit_pct = fields.Integer(
        string='Tasas — umbral amarillo (%)', default=60,
        help='Desde este porcentaje (y por debajo del verde), las tasas se muestran en amarillo; menos, rojo. Aplica al análisis de clientes y al panel de ventas.'
             'la celda se muestra en rojo en el análisis de clientes.')
    customer_analysis_ontime_warn_pct = fields.Integer(
        string='% a tiempo — umbral amarillo', default=80,
        help='Por debajo de este porcentaje de entregas a tiempo, '
             'la celda se muestra en amarillo.')
    customer_analysis_ontime_crit_pct = fields.Integer(
        string='% a tiempo — umbral rojo', default=60,
        help='Por debajo de este porcentaje de entregas a tiempo, '
             'la celda se muestra en rojo.')
    customer_analysis_risk_days = fields.Integer(
        string='Días sin comprar (riesgo)', default=90,
        help='Un cliente que no compra hace más de este número de días '
             'se clasifica como "en riesgo" en la columna de frecuencia.')
    customer_analysis_abc_a_pct = fields.Integer(
        string='Segmento A — % acumulado', default=20,
        help='Clientes que suman el primer X% del monto total del período se clasifican como A. '
             'Se ordena de mayor a menor monto antes de acumular.')
    customer_analysis_abc_b_pct = fields.Integer(
        string='Segmento B — % acumulado adicional', default=50,
        help='Del monto restante tras el segmento A, los clientes que suman el siguiente X% '
             'se clasifican como B. El resto queda en C.')

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock (quiebres)',
        domain=[('usage', '=', 'internal')],
        compute='_compute_stock_location_id',
        inverse='_set_stock_location_id',
        store=False,
        help='Ubicación interna desde la cual se lee el stock actual en el widget de quiebres de stock.',
    )

    @api.model
    def get_config(self):
        """Retorna la configuración de la empresa actual; la crea si no existe.

        En multiempresa, cada compañía tiene su propio registro. Antes se creaba de
        forma perezosa solo al abrir Ajustes, así que una empresa donde nunca se abrió
        corría con los defaults hardcodeados en TODO el módulo (umbrales, métodos,
        exclusión de servicios, etc.), dando comportamientos distintos por empresa.
        Ahora se crea al vuelo (sudo) para garantizar consistencia entre compañías.
        """
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.sudo().create({'company_id': self.env.company.id})
        return config

    @api.depends()
    def _compute_stock_location_id(self):
        """
        Calcula stock_location_id para cada registro.

        Fórmula: lee el ID entero desde ir.config_parameter y resuelve el
        registro de stock.location correspondiente. Si el parámetro está vacío,
        es inválido o la ubicación fue eliminada, devuelve False.
        Depende de: ir.config_parameter['mrp_reschedule.stock_location_id'].
        """
        param = self.env['ir.config_parameter'].sudo().get_param(
            'mrp_reschedule.stock_location_id')
        # int() puede lanzar ValueError si el parámetro fue editado manualmente
        try:
            loc_id = int(param) if param else False
        except (ValueError, TypeError):
            loc_id = False
        location = self.env['stock.location'].browse(loc_id) if loc_id else \
            self.env['stock.location']
        for rec in self:
            rec.stock_location_id = location if loc_id and location.exists() else False

    def _set_stock_location_id(self):
        """Persiste stock_location_id en ir.config_parameter como cadena del ID."""
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                'mrp_reschedule.stock_location_id',
                str(rec.stock_location_id.id) if rec.stock_location_id else '',
            )

    @api.depends()
    def _compute_name(self):
        """
        Calcula name para cada registro.

        Fórmula: valor fijo — el singleton siempre tiene el mismo nombre visible.
        Depende de: ningún campo (nombre constante).
        """
        for rec in self:
            rec.name = 'Configuración del planificador'

    def action_open_user_warehouses(self):
        """
        Abre la lista unificada de usuarios con depósitos y secciones visibles del Planificador MRP.

        :returns: dict — acción de ventana (ir.actions.act_window) que muestra
                  res.users con la vista personalizada view_users_mrp_warehouse_list,
                  filtrando solo usuarios activos no compartidos (internos).
        """
        return {
            'type':      'ir.actions.act_window',
            'name':      'Preferencias por usuario',
            'res_model': 'res.users',
            'view_mode': 'list',
            'view_id':   self.env.ref('odoo_mrp_planner.view_users_mrp_warehouse_list').id,
            'domain':    [('share', '=', False), ('active', '=', True)],
            'target':    'current',
        }

    def _user_can_edit_config(self):
        """True si el usuario actual puede editar la configuración del planificador.

        Además del Administrador del módulo, los administradores de área
        (Producción, Programación, Ventas y Compras) pueden guardar la
        configuración: son los mismos grupos con permiso de escritura en
        ir.model.access.csv y a los que el menú Configuración les muestra
        su sección editable.
        """
        u = self.env.user
        return any(u.has_group(g) for g in self._config_editor_groups())

    @api.model
    def _config_editor_groups(self):
        """Grupos con permiso para editar la configuración.

        Hook extensible: odoo_mrp_planner_scheduling agrega su grupo de
        Programación a esta lista.
        """
        return [
            'odoo_mrp_planner.group_admin',
            'odoo_mrp_planner.group_prod',
            'odoo_mrp_planner.group_sales',
            'odoo_mrp_planner.group_purchase_admin',
            'odoo_mrp_planner.group_inventory_admin',
            'base.group_system',
        ]

    @api.model
    def _scheduling_ui_enabled(self, user=None):
        """True si el usuario debe ver la UI de programación (pestañas, KPIs, botones).

        Hook del módulo de scheduling: sin odoo_mrp_planner_scheduling instalado
        no existe la función de programación, por lo que siempre es False.
        """
        return False

    @api.model
    def _user_in_scheduling_group(self, user=None):
        """True si el usuario pertenece al grupo de Programación (hook de scheduling)."""
        return False

    def write(self, vals):
        """
        Guarda los cambios y propaga la configuración a los ir.cron del módulo.

        Cuando se modifican campos de intervalo de cron (cron_interval_*, sale_cat_*,
        supplier_cat_*, customer_cat_*) actualiza el registro de ir.cron correspondiente
        vía sudo() porque el usuario administrador del módulo no tiene acceso directo a ir.cron.

        :param vals: dict con los campos a actualizar.
        :returns: bool — resultado del super().write().
        """
        # Modo superusuario permitido para la carga de datos del módulo (instalación/upgrade).
        if not self.env.su and not self._user_can_edit_config():
            raise AccessError(_("Solo los administradores pueden modificar la configuración"))
        res = super().write(vals)
        if 'cron_interval_number' in vals or 'cron_interval_type' in vals:
            cron = self.env.ref('odoo_mrp_planner.ir_cron_check_delays', raise_if_not_found=False)
            if cron:
                cron_vals = {}
                if 'cron_interval_number' in vals:
                    cron_vals['interval_number'] = vals['cron_interval_number']
                if 'cron_interval_type' in vals:
                    cron_vals['interval_type'] = vals['cron_interval_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cron.sudo().write(cron_vals)
        if 'sale_cat_auto_cron' in vals or 'sale_cat_cron_number' in vals or 'sale_cat_cron_type' in vals:
            cat_cron = self.env.ref('odoo_mrp_planner.ir_cron_auto_assign_sale_categories', raise_if_not_found=False)
            if cat_cron:
                cat_cron_vals = {}
                if 'sale_cat_auto_cron' in vals:
                    cat_cron_vals['active'] = vals['sale_cat_auto_cron']
                if 'sale_cat_cron_number' in vals:
                    cat_cron_vals['interval_number'] = vals['sale_cat_cron_number']
                if 'sale_cat_cron_type' in vals:
                    cat_cron_vals['interval_type'] = vals['sale_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cat_cron.sudo().write(cat_cron_vals)
        # Supplier categories cron
        if any(k in vals for k in ('enable_supplier_categories', 'supplier_cat_auto_cron', 'supplier_cat_cron_number', 'supplier_cat_cron_type')):
            sup_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_supplier_categories', raise_if_not_found=False)
            if sup_cron:
                sup_vals = {}
                if 'supplier_cat_auto_cron' in vals:
                    sup_vals['active'] = vals['supplier_cat_auto_cron']
                if 'enable_supplier_categories' in vals and not vals['enable_supplier_categories']:
                    sup_vals['active'] = False  # disabling the feature also disables the cron
                if 'supplier_cat_cron_number' in vals:
                    sup_vals['interval_number'] = vals['supplier_cat_cron_number']
                if 'supplier_cat_cron_type' in vals:
                    sup_vals['interval_type'] = vals['supplier_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                if sup_vals:
                    sup_cron.sudo().write(sup_vals)
        # Customer categories cron
        if any(k in vals for k in ('enable_customer_categories', 'customer_cat_auto_cron', 'customer_cat_cron_number', 'customer_cat_cron_type')):
            cust_cron = self.env.ref('odoo_mrp_planner.ir_cron_compute_customer_categories', raise_if_not_found=False)
            if cust_cron:
                cust_vals = {}
                if 'customer_cat_auto_cron' in vals:
                    cust_vals['active'] = vals['customer_cat_auto_cron']
                if 'enable_customer_categories' in vals and not vals['enable_customer_categories']:
                    cust_vals['active'] = False  # disabling the feature also disables the cron
                if 'customer_cat_cron_number' in vals:
                    cust_vals['interval_number'] = vals['customer_cat_cron_number']
                if 'customer_cat_cron_type' in vals:
                    cust_vals['interval_type'] = vals['customer_cat_cron_type']
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                if cust_vals:
                    cust_cron.sudo().write(cust_vals)
        if 'dispatch_snapshot_hour' in vals or vals.get('dispatch_stock_log_enabled'):
            self._dispatch_sync_snapshot_cron()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """
        Crea el registro de configuración aplicando la restricción singleton.

        Lanza UserError si ya existe un registro, garantizando que solo haya una
        instancia del planificador. Tras la creación sincroniza el cron de
        detección de retrasos con los valores del nuevo registro.

        :param vals_list: list[dict] — lista de valores para crear.
        :returns: mrp.reschedule.config — recordset con los registros creados.
        :raises UserError: si ya existe una configuración en la base de datos.
        """
        # Se permite en modo superusuario para que la carga de datos del módulo (instalación:
        # el singleton se crea como SUPERUSER, que aún no pertenece a group_admin) no falle.
        if not self.env.su and not self.env.user.has_group('odoo_mrp_planner.group_admin'):
            raise AccessError(_("Solo los administradores pueden crear la configuración"))
        # Singleton POR EMPRESA: una configuración por compañía (no una global). La unicidad
        # real la garantiza el _sql_constraints UNIQUE(singleton_check, company_id).
        for vals in vals_list:
            cid = vals.get('company_id') or self.env.company.id
            if self.search_count([('company_id', '=', cid)]) > 0:
                raise UserError(_(
                    'Ya existe una configuración del planificador para esta empresa. '
                    'Editá el registro existente en lugar de crear uno nuevo.'
                ))
        records = super().create(vals_list)
        for rec in records:
            cron = self.env.ref('odoo_mrp_planner.ir_cron_check_delays', raise_if_not_found=False)
            if cron:
                # sudo() necesario: ir.cron pertenece al superusuario y el administrador
                # del módulo no tiene permisos de escritura directa sobre él.
                cron.sudo().write({
                    'interval_number': rec.cron_interval_number,
                    'interval_type':   rec.cron_interval_type,
                })
        if any(v.get('dispatch_stock_log_enabled') or v.get('dispatch_snapshot_hour')
               for v in vals_list):
            records._dispatch_sync_snapshot_cron()
        return records

    @api.model
    def action_open(self):
        """
        Abre el formulario de configuración del planificador (singleton).

        Busca el único registro existente y retorna una acción de ventana apuntando
        a su formulario con paginador oculto (no_pager) para reforzar la experiencia
        de singleton. Si no existe ningún registro, abre el formulario en modo creación.

        :returns: dict — acción ir.actions.act_window con res_id del singleton o
                  False si aún no fue creado.
        """
        if not self._user_can_edit_config():
            raise AccessError(_("Solo los administradores pueden acceder a la configuración"))
        config = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            # sudo(): la creación del singleton puede ejecutarse como cualquier usuario que abre la pantalla
            config = self.sudo().create({'company_id': self.env.company.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Configuración del planificador',
            'res_model': self._name,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner.mrp_reschedule_config_form_view').id,
            'res_id': config.id,
            'target': 'current',
            'flags': {'no_pager': True},
        }
