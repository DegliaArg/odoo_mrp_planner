"""
Módulo: mrp_reschedule_alert.py
Modelo: mrp.reschedule.alert

Gestiona las alertas de desvío de planificación de producción.

Responsabilidades:
- Detectar OFs y OCs atrasadas o próximas a vencer mediante un cron periódico.
- Detectar recepciones de stock demoradas y diferencias de cantidad en OFs cerradas.
- Calcular el impacto en OFs que consumen los productos afectados.
- Permitir al usuario resolver alertas manualmente o crear un plan de reprogramación.
- Resolver automáticamente alertas cuando el registro subyacente vuelve a estado normal.

Relacionado con:
- mrp.production: OF origen de las alertas mo_delayed / mo_upcoming / qty_mismatch.
- purchase.order: OC origen de las alertas po_delayed / po_upcoming / po_cancelled.
- stock.picking: Recepción origen de las alertas receipt_delayed.
- mrp.reschedule.plan: Plan de reprogramación generado a partir de una alerta.
- mrp.reschedule.config: Configuración de umbrales (días críticos, tolerancia de cantidad).
"""
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError
from odoo.addons.odoo_mrp_planner.models.mrp_schedule_mixin import no_subcontract_domain
from .const import DEFAULT_PO_CRITICAL_DAYS

_logger = logging.getLogger(__name__)

# Tolerancia de cantidad por defecto (5 %) usada cuando no existe registro de configuración.
# El valor operativo lo sobreescribe mrp.reschedule.config.qty_tolerance_pct en tiempo de ejecución.
QTY_TOLERANCE = 0.05  # fallback; sobreescrito por mrp.reschedule.config


class MrpRescheduleAlert(models.Model):
    _name = 'mrp.reschedule.alert'
    _description = 'Alerta de planificación de producción'
    _order = 'resolved asc, severity desc, id desc'

    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    name = fields.Char(compute='_compute_name', store=True,
                       help='Etiqueta legible generada automáticamente: tipo de alerta + referencia del documento.')

    alert_type = fields.Selection([
        ('mo_delayed',      'OF atrasada'),
        ('mo_upcoming',     'OF por vencer'),
        ('po_delayed',      'OC vencida'),
        ('po_upcoming',     'OC por vencer'),
        ('po_cancelled',    'OC cancelada'),
        ('receipt_delayed', 'Recepción atrasada'),
        ('qty_mismatch',    'Cantidad diferente'),
        ('mo_cancelled',    'OF cancelada'),
    ], string='Tipo', required=True,
       help='Categoría del desvío detectado. Determina qué documento de origen se analiza y qué reglas de resolución se aplican.')

    severity = fields.Selection([
        ('warning',  'Aviso'),
        ('critical', 'Crítico'),
    ], string='Severidad', required=True, default='warning',
       help='Nivel de urgencia. "Crítico" se activa cuando el atraso supera el umbral configurado en mrp.reschedule.config.')

    production_id = fields.Many2one('mrp.production', string='Orden de fabricación',
                                    ondelete='cascade', index=True,
                                    help='OF causante de la alerta (tipos: mo_delayed, mo_upcoming, qty_mismatch, mo_cancelled).')
    purchase_id   = fields.Many2one('purchase.order',  string='Orden de compra',
                                    ondelete='cascade', index=True,
                                    help='OC causante de la alerta (tipos: po_delayed, po_upcoming, po_cancelled).')
    picking_id    = fields.Many2one('stock.picking',   string='Recepción',
                                    ondelete='cascade', index=True,
                                    help='Recepción de stock causante de la alerta (tipo: receipt_delayed).')
    product_id    = fields.Many2one('product.product', string='Producto', index=True,
                                    help='Producto involucrado en el desvío. Relevante para qty_mismatch y cálculo de impacto.')

    expected_qty  = fields.Float(string='Cantidad planificada', digits=(16, 2),
                                 help='Cantidad que estaba planificada producir/recibir según la OF o la OC.')
    actual_qty    = fields.Float(string='Cantidad real',        digits=(16, 2),
                                 help='Cantidad efectivamente producida o recibida. Se compara con expected_qty para calcular el desvío.')

    impact_mo_ids = fields.Many2many(
        'mrp.production',
        'mrp_reschedule_alert_production_rel',
        'alert_id', 'production_id',
        string='OFs afectadas',
        help='OFs confirmadas/en progreso cuya demanda acumulada supera el stock disponible del producto afectado.'
    )
    impact_mo_count = fields.Integer(compute='_compute_impact_mo_count', string='OFs afectadas',
                                     help='Cantidad de OFs impactadas por este desvío. Calculado a partir de impact_mo_ids.')

    days_late = fields.Integer(string='Días de atraso', compute='_compute_days_late', store=False,
                                help='Diferencia en días entre la fecha de referencia del documento y el momento actual.')
    message   = fields.Char(string='Detalle',
                            help='Texto descriptivo generado automáticamente con fechas y valores del desvío.')

    resolved     = fields.Boolean(string='Resuelta', default=False,
                                  help='Indica si la alerta fue resuelta manualmente o por resolución automática.')
    resolve_date = fields.Datetime(string='Resuelta el', readonly=True,
                                   help='Fecha y hora en que se marcó la alerta como resuelta.')
    plan_id      = fields.Many2one('mrp.reschedule.plan', string='Plan generado', readonly=True,
                                   help='Plan de reprogramación creado a partir de esta alerta.')

    active = fields.Boolean(default=True,
                            help='Permite archivar alertas sin borrarlas. Las alertas inactivas no aparecen en las vistas estándar.')

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('alert_type', 'production_id', 'purchase_id', 'picking_id')
    def _compute_name(self):
        """
        Calcula el nombre legible de la alerta.

        Fórmula: '<etiqueta del tipo> — <referencia del documento>'.
        La referencia se toma del primer campo relacional disponible:
        production_id > purchase_id > picking_id.
        Depende de: alert_type, production_id.name, purchase_id.name, picking_id.name.
        """
        type_labels = dict(self._fields['alert_type'].selection)
        for alert in self:
            ref = (
                (alert.production_id.name if alert.production_id else None)
                or (alert.purchase_id.name if alert.purchase_id else None)
                or (alert.picking_id.name  if alert.picking_id  else None)
                or ''
            )
            label = type_labels.get(alert.alert_type, alert.alert_type)
            alert.name = f'{label} — {ref}' if ref else label

    @api.depends('production_id.date_finished', 'purchase_id.date_planned', 'picking_id.scheduled_date')
    def _compute_days_late(self):
        """Calcula días de atraso en tiempo real desde la fecha del registro fuente."""
        now = datetime.utcnow()
        for alert in self:
            ref_date = None
            atype = alert.alert_type
            if atype in ('mo_delayed', 'mo_upcoming', 'qty_mismatch', 'mo_cancelled'):
                if alert.production_id and alert.production_id.date_finished:
                    ref_date = alert.production_id.date_finished
            elif atype in ('po_delayed', 'po_upcoming', 'po_cancelled'):
                if alert.purchase_id and alert.purchase_id.date_planned:
                    ref_date = alert.purchase_id.date_planned
            elif atype == 'receipt_delayed':
                if alert.picking_id and alert.picking_id.scheduled_date:
                    ref_date = alert.picking_id.scheduled_date
            if ref_date:
                alert.days_late = max(0, (now - ref_date).days)
            else:
                alert.days_late = 0

    @api.depends('impact_mo_ids')
    def _compute_impact_mo_count(self):
        """
        Calcula la cantidad de OFs afectadas por la alerta.

        Fórmula: conteo de IDs en impact_mo_ids.
        Depende de: impact_mo_ids.
        """
        # Usar .ids evita cargar los campos de los registros relacionados
        for alert in self:
            alert.impact_mo_count = len(alert.impact_mo_ids.ids)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_resolve(self):
        """
        Marca la alerta (o el lote seleccionado) como resuelta.

        Verifica que el usuario tenga el grupo 'Producción - Planificar' o 'Administrador'
        del módulo antes de escribir. La fecha de resolución se registra automáticamente.

        :raises UserError: Si el usuario no pertenece a ninguno de los grupos requeridos.
        """
        if not (self.env.user.has_group('odoo_mrp_planner.group_prod') or
                self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_(
                'Solo los usuarios con permiso "Producción - Planificar" o "Administrador" '
                'pueden marcar alertas como resueltas.'
            ))
        self.write({'resolved': True, 'resolve_date': fields.Datetime.now()})

    def action_view_impact_mos(self):
        """
        Abre la vista de lista/formulario de OFs afectadas por esta alerta.

        :returns: Diccionario de acción de ventana filtrado a las OFs en impact_mo_ids.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs afectadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.impact_mo_ids.ids)],
            'target': 'current',
        }

    def action_create_reschedule_plan(self):
        """
        Crea o abre el plan de reprogramación vinculado a esta alerta.

        Si ya existe un plan activo (no aplicado ni cancelado), lo abre directamente.
        De lo contrario crea un nuevo mrp.reschedule.plan, intentando asociarlo a la
        OF correspondiente. Cuando la alerta proviene de una OC (purchase_id), busca
        la OF relacionada mediante los campos purchase_order_id, purchase_line_id.order_id
        u origin (en ese orden de prioridad).

        :returns: Acción de ventana al formulario del plan de reprogramación.
        """
        self.ensure_one()
        if self.plan_id and self.plan_id.state not in ('applied', 'cancelled'):
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.reschedule.plan',
                'res_id': self.plan_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        mo = self.production_id
        if not mo and self.purchase_id:
            MO = self.env['mrp.production']
            mo_fields = MO._fields
            try:
                domain = [('state', 'in', ('confirmed', 'progress'))]
                or_clauses = []
                if 'purchase_order_id' in mo_fields:
                    or_clauses.append(('purchase_order_id', '=', self.purchase_id.id))
                if 'purchase_line_id' in mo_fields:
                    or_clauses.append(('purchase_line_id.order_id', '=', self.purchase_id.id))
                if or_clauses:
                    if len(or_clauses) == 2:
                        domain = domain + ['|'] + or_clauses
                    else:
                        domain = domain + or_clauses
                    mo = MO.search(domain, limit=1)
                if not mo:
                    mo = MO.search([
                        ('state', 'in', ('confirmed', 'progress')),
                        ('origin', 'ilike', self.purchase_id.name),
                    ], limit=1)
            except Exception as e:
                _logger.warning('MRP Reschedule: no se pudo buscar OF para alerta %s: %s', self.id, e)

        plan_vals = {'replan_from': fields.Datetime.now()}
        if mo:
            plan_vals['production_id'] = mo.id
            if mo.date_finished:
                plan_vals['new_finish_date'] = mo.date_finished

        plan = self.env['mrp.reschedule.plan'].create(plan_vals)
        self.plan_id = plan.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.reschedule.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def action_run_cron_manual(self):
        """Botón manual: ejecuta el chequeo de alertas ahora (solo para administradores del planificador)."""
        # Usar group_admin del módulo propio para consistencia con el resto de controles de acceso.
        # mrp.group_mrp_manager fue el grupo original pero excluía a usuarios con group_admin
        # del planificador que no tenían rol nativo de fabricación.
        if not (self.env.user.has_group('odoo_mrp_planner.group_admin') or
                self.env.user.has_group('base.group_system')):
            raise UserError(_(
                'Solo los administradores del planificador pueden ejecutar el chequeo de alertas manualmente.'
            ))
        self._cron_check_delays()
        return self.env.ref('odoo_mrp_planner.action_mrp_reschedule_alert').read()[0]

    # ── Helpers — upsert ─────────────────────────────────────────────────────

    @api.model
    def _upsert_alert(self, alert_type, severity, days_late, message, **fields_vals):
        """Crea o actualiza una alerta abierta del tipo y registro dados.

        Busca una alerta sin resolver del mismo ``alert_type`` y los mismos campos
        relacionales pasados en ``fields_vals`` (ej. production_id, purchase_id).
        Si la encuentra, actualiza ``severity``, ``days_late`` y ``message``.
        Si no existe, crea una nueva.

        Args:
            alert_type (str): Valor del campo Selection ``alert_type``.
            severity (str): 'warning' o 'critical'.
            days_late (int): Días de atraso calculados por el llamador.
            message (str): Texto descriptivo del desvío.
            **fields_vals: Campos relacionales/numéricos para buscar y/o escribir
                           (ej. production_id=42, product_id=7, impact_mo_ids=[1,2]).
        """
        domain = [('alert_type', '=', alert_type), ('resolved', '=', False)]
        relational_keys = ('production_id', 'purchase_id', 'picking_id', 'product_id')
        for k in relational_keys:
            if k in fields_vals:
                domain.append((k, '=', fields_vals[k]))

        existing = self.search(domain, limit=1)
        write_vals = {
            'severity': severity,
            'days_late': days_late,
            'message': message,
        }
        # Campos extra (ej. expected_qty, actual_qty)
        extra_skip = set(relational_keys) | {'impact_mo_ids'}
        for k, v in fields_vals.items():
            if k not in extra_skip:
                write_vals[k] = v
        # Many2many impact_mo_ids requiere sintaxis ORM (6, 0, ids)
        if 'impact_mo_ids' in fields_vals:
            write_vals['impact_mo_ids'] = [(6, 0, fields_vals['impact_mo_ids'])]

        if existing:
            existing.write(write_vals)
        else:
            create_vals = dict(write_vals)
            create_vals['alert_type'] = alert_type
            for k in relational_keys:
                if k in fields_vals:
                    create_vals[k] = fields_vals[k]
            self.create(create_vals)

    # ── Helpers — impacto ────────────────────────────────────────────────────

    @api.model
    def _find_impact_mos(self, product_id, available_qty, cache=None):
        """Retorna MOs confirmadas/en progreso que consumen product_id y
        cuya demanda acumulada supera el stock disponible (orden cronológico)."""
        if cache is not None and product_id in cache:
            return cache[product_id]

        mos = self.env['mrp.production'].search([
            ('company_id', '=', self.env.company.id),
            ('state', 'in', ('confirmed', 'progress')),
            ('move_raw_ids.product_id', '=', product_id),
        ] + no_subcontract_domain(self.env)).sorted(lambda m: m.date_start or datetime(9999, 12, 31))

        # Prefetch all raw moves in one query
        mos.mapped('move_raw_ids')

        impacted   = self.env['mrp.production']
        cumulative = 0.0
        for mo in mos:
            required = sum(
                (m.product_uom_qty - (getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)))
                for m in mo.move_raw_ids
                if m.product_id.id == product_id
                and m.state not in ('done', 'cancel')
            )
            if required <= 0:
                continue
            cumulative += required
            if cumulative > available_qty:
                impacted |= mo

        if cache is not None:
            cache[product_id] = impacted
        return impacted

    # ── Migración ─────────────────────────────────────────────────────────────

    def _auto_init(self):
        super()._auto_init()
        # Índices compuestos para acelerar las queries de alertas que siempre
        # filtran por (resolved, company_id) y frecuentemente por alert_type.
        tools.create_index(
            self._cr,
            'mrp_reschedule_alert_resolved_company_idx',
            self._table,
            ['resolved', 'company_id'],
        )
        tools.create_index(
            self._cr,
            'mrp_reschedule_alert_type_company_idx',
            self._table,
            ['alert_type', 'company_id', 'resolved'],
        )
        # Fill company_id for alerts created before multi-company support
        self.env.cr.execute("SAVEPOINT fill_alert_company_id")
        try:
            self.env.cr.execute("""
                UPDATE mrp_reschedule_alert
                SET company_id = (SELECT id FROM res_company ORDER BY id LIMIT 1)
                WHERE company_id IS NULL
            """)
            self.env.cr.execute("RELEASE SAVEPOINT fill_alert_company_id")
        except Exception:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT fill_alert_company_id")

    # ── Cron ─────────────────────────────────────────────────────────────────

    @api.model
    def _cron_check_delays(self):
        """Ejecutado periódicamente. Detecta desvíos y crea/actualiza alertas (una vez por empresa activa)."""
        # sudo() necesario: el cron corre en contexto de empresa activa y el multi-company record rule restringe res.company.
        companies = self.env['res.company'].sudo().search([])
        for company in companies:
            _logger.info('MRP Planner cron: chequeo desvíos — empresa %s', company.name)
            try:
                self.with_company(company)._cron_check_delays_for_company()
            except Exception as e:
                _logger.warning('MRP Planner cron: error en empresa %s: %s', company.name, e)

    def _cron_check_delays_for_company(self):
        """Detecta desvíos para la empresa activa en self.env.company."""
        _logger.info('MRP Planner cron: inicio chequeo de desvíos de producción')
        now = datetime.utcnow()
        impact_cache = {}
        # Leer la configuración una sola vez para toda la ejecución del cron.
        # Los métodos privados la reciben como parámetro para evitar llamadas repetidas a get_config().
        cfg = self.env['mrp.reschedule.config'].get_config()
        steps = [
            (self._check_delayed_mos,     (now, cfg)),
            (self._check_upcoming_mos,    (now, cfg)),
            (self._check_delayed_pos,     (now, cfg, impact_cache)),
            (self._check_upcoming_pos,    (now, cfg)),
            (self._check_delayed_receipts,(now, cfg, impact_cache)),
            (self._check_qty_mismatches,  (now, cfg, impact_cache)),
            (self._auto_resolve_stale,    ()),
        ]
        for fn, args in steps:
            try:
                fn(*args)
            except Exception as e:
                _logger.warning('MRP Reschedule cron: error en %s: %s', fn.__name__, e)
        _logger.info('MRP Planner cron: fin chequeo de desvíos de producción')

    @api.model
    def _check_delayed_mos(self, now, cfg=None):
        """Detecta OFs confirmadas/en progreso cuya fecha de fin ya pasó y crea/actualiza alertas mo_delayed."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        # 3 días es el umbral crítico por defecto si no hay configuración activa
        crit_days = cfg.alert_mo_critical_days if cfg else 3
        mos = self.env['mrp.production'].search([
            ('company_id', '=', self.env.company.id),
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
            ('date_finished', '<', now),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        # Preload all open mo_delayed alerts indexed by production_id
        by_mo = {
            a.production_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'mo_delayed'), ('resolved', '=', False)])
        }

        to_create = []
        for mo in mos:
            days = max(0, (now - mo.date_finished).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Fin planificado: %s') % mo.date_finished.strftime('%d/%m/%Y %H:%M')
            write_vals = {'severity': severity, 'message': msg}
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'mo_delayed',
                    'production_id': mo.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_upcoming_mos(self, now, cfg=None):
        """Detecta OFs con fecha de fin dentro de la ventana de aviso y crea/actualiza alertas mo_upcoming."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        # 7 días es el horizonte de aviso por defecto si no hay configuración activa
        warn_days = cfg.alert_mo_warning_days if cfg else 7
        future_limit = now + timedelta(days=warn_days)

        mos = self.env['mrp.production'].search([
            ('company_id', '=', self.env.company.id),
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
            ('date_finished', '>=', now),
            ('date_finished', '<=', future_limit),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        by_mo = {
            a.production_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'mo_upcoming'), ('resolved', '=', False)])
        }

        to_create = []
        for mo in mos:
            days_until = max(0, (mo.date_finished - now).days)
            msg = _('Vence el: %s (en %d días)') % (mo.date_finished.strftime('%d/%m/%Y'), days_until)
            write_vals = {'severity': 'warning', 'message': msg}
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'mo_upcoming',
                    'production_id': mo.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_delayed_pos(self, now, cfg=None, impact_cache=None):
        """Detecta OCs con fecha de entrega vencida y sin recepción completa; crea/actualiza alertas po_delayed."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        # 5 días es el umbral crítico por defecto para OCs si no hay configuración activa
        crit_days = cfg.alert_po_critical_days if cfg else DEFAULT_PO_CRITICAL_DAYS
        pos = self.env['purchase.order'].search([
            ('company_id', '=', self.env.company.id),
            ('state', 'in', ('purchase', 'done')),
            ('date_planned', '<', now),
            ('receipt_status', 'not in', ['full']),
        ])

        # Preload all open po_delayed alerts indexed by purchase_id
        by_po = {
            a.purchase_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'po_delayed'), ('resolved', '=', False)])
        }

        # Batch-read qty_available for ALL products across ALL POs in one shot
        all_product_ids = set()
        for po in pos:
            all_product_ids.update(po.order_line.mapped('product_id').ids)
        if all_product_ids:
            products = self.env['product.product'].browse(list(all_product_ids))
            qty_by_product = {p.id: p.qty_available for p in products}
        else:
            qty_by_product = {}

        to_create = []
        for po in pos:
            days = max(0, (now - po.date_planned).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Entrega planificada: %s') % po.date_planned.strftime('%d/%m/%Y')

            product_ids = po.order_line.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                impacted |= self._find_impact_mos(pid, qty_by_product.get(pid, 0), cache=impact_cache)

            write_vals = {
                'severity':  severity,
                'message':   msg,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if po.id in by_po:
                by_po[po.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type': 'po_delayed',
                    'purchase_id': po.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_upcoming_pos(self, now, cfg=None):
        """Detecta OCs con entrega próxima y sin recepción completa; crea/actualiza alertas po_upcoming."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        # 10 días es el horizonte de aviso por defecto para OCs si no hay configuración activa
        warn_days = cfg.alert_po_warning_days if cfg else 10
        future_limit = now + timedelta(days=warn_days)

        pos = self.env['purchase.order'].search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'purchase'),
            ('receipt_status', '!=', 'full'),
            ('date_planned', '>=', now),
            ('date_planned', '<=', future_limit),
        ])

        by_po = {
            a.purchase_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'po_upcoming'), ('resolved', '=', False)])
        }

        to_create = []
        for po in pos:
            days_until = max(0, (po.date_planned - now).days)
            msg = _('Entrega prevista: %s (en %d días)') % (po.date_planned.strftime('%d/%m/%Y'), days_until)
            write_vals = {'severity': 'warning', 'message': msg}
            if po.id in by_po:
                by_po[po.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':  'po_upcoming',
                    'purchase_id': po.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_delayed_receipts(self, now, cfg=None, impact_cache=None):
        """Detecta recepciones de compra pendientes cuya fecha programada ya pasó; crea/actualiza alertas receipt_delayed."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        # 3 días es el umbral crítico por defecto para recepciones si no hay configuración activa
        crit_days = cfg.alert_receipt_critical_days if cfg else 3
        pickings = self.env['stock.picking'].search([
            ('company_id', '=', self.env.company.id),
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_code', '=', 'incoming'),
            ('purchase_id', '!=', False),
            ('return_id', '=', False),
            ('scheduled_date', '<', now),
        ])

        # Preload all open receipt_delayed alerts indexed by picking_id
        by_picking = {
            a.picking_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'receipt_delayed'), ('resolved', '=', False)])
        }

        # Batch-read qty_available for ALL products across ALL pickings in one shot
        all_product_ids = set()
        for picking in pickings:
            all_product_ids.update(picking.move_ids.mapped('product_id').ids)
        if all_product_ids:
            products = self.env['product.product'].browse(list(all_product_ids))
            qty_by_product = {p.id: p.qty_available for p in products}
        else:
            qty_by_product = {}

        to_create = []
        for picking in pickings:
            days = max(0, (now - picking.scheduled_date).days)
            severity = 'critical' if days >= crit_days else 'warning'
            msg = _('Fecha prevista: %s') % picking.scheduled_date.strftime('%d/%m/%Y')

            product_ids = picking.move_ids.mapped('product_id').ids
            impacted = self.env['mrp.production']
            for pid in product_ids:
                impacted |= self._find_impact_mos(pid, qty_by_product.get(pid, 0), cache=impact_cache)

            write_vals = {
                'severity':  severity,
                'message':   msg,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if picking.id in by_picking:
                by_picking[picking.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type': 'receipt_delayed',
                    'picking_id': picking.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _check_qty_mismatches(self, now, cfg=None, impact_cache=None):
        """Detecta MOs recién cerradas con cantidad diferente a la planificada."""
        if cfg is None:
            cfg = self.env['mrp.reschedule.config'].get_config()
        qty_tol = (cfg.qty_tolerance_pct / 100.0) if cfg else QTY_TOLERANCE
        # La ventana de búsqueda coincide con el intervalo del cron + 10 % de margen para evitar
        # que OFs cerradas justo entre dos ejecuciones queden fuera del análisis.
        if cfg:
            interval_number = cfg.cron_interval_number or 1
            interval_type = cfg.cron_interval_type or 'hours'
            type_to_hours = {'minutes': 1/60, 'hours': 1, 'days': 24}
            # Factor 1.1 = margen del 10 % sobre el intervalo configurado
            hours = interval_number * type_to_hours.get(interval_type, 1) * 1.1
        else:
            hours = 2.0
        # Mínimo de 30 minutos para no dejar ventana en blanco si el cron se configura muy frecuente
        since = now - timedelta(hours=max(hours, 0.5))
        done_mos = self.env['mrp.production'].search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'done'),
            ('date_finished', '>=', since),
            ('date_finished', '!=', False),
        ] + no_subcontract_domain(self.env))

        # Preload all open qty_mismatch alerts indexed by production_id
        by_mo = {
            a.production_id.id: a
            for a in self.search([('company_id', '=', self.env.company.id), ('alert_type', '=', 'qty_mismatch'), ('resolved', '=', False)])
        }

        # Prefetch all finished moves in one query
        done_mos.mapped('move_finished_ids')

        to_create = []
        for mo in done_mos:
            planned_qty = mo.product_qty
            if not planned_qty:
                continue
            # Cantidad real producida: suma de movimientos de salida terminados
            done_moves = mo.move_finished_ids.filtered(
                lambda m: m.state == 'done' and m.product_id == mo.product_id
            )
            actual_qty = sum(
                getattr(m, 'quantity', None) or getattr(m, 'quantity_done', 0.0)
                for m in done_moves
            ) if done_moves else planned_qty
            if actual_qty == 0:
                actual_qty = planned_qty  # sin datos, no alertar
            delta = abs(actual_qty - planned_qty) / planned_qty
            if delta <= qty_tol:
                continue
            # Calcular OFs afectadas por el delta de producción
            avail = mo.product_id.qty_available
            impacted = self._find_impact_mos(mo.product_id.id, avail, cache=impact_cache)
            severity = 'critical' if actual_qty < planned_qty else 'warning'
            msg = _('Planificado: %g | Real: %g (%.0f%%)') % (
                planned_qty, actual_qty, (actual_qty / planned_qty) * 100
            )
            write_vals = {
                'severity':     severity,
                'message':      msg,
                'expected_qty': planned_qty,
                'actual_qty':   actual_qty,
                'impact_mo_ids': [(6, 0, impacted.ids)],
            }
            if mo.id in by_mo:
                by_mo[mo.id].write(write_vals)
            else:
                to_create.append({
                    'alert_type':    'qty_mismatch',
                    'production_id': mo.id,
                    'product_id':    mo.product_id.id,
                    **write_vals,
                })
        if to_create:
            self.create(to_create)

    @api.model
    def _resolve_for(self, alert_types, **record_fields):
        """
        Resuelve inmediatamente alertas abiertas del tipo dado para un registro concreto.

        Diseñado para ser llamado desde los write() de OF/OC/Recepción cuando el estado
        del documento cambia a uno que ya no justifica la alerta (resolución reactiva).
        Complementa la resolución periódica del cron (_auto_resolve_stale).

        :param alert_types: Iterable de valores de alert_type a buscar.
        :param record_fields: Pares campo=valor (ej. production_id=42) para restringir
                              la búsqueda al documento específico que cambió de estado.
        """
        domain = [('alert_type', 'in', list(alert_types)), ('resolved', '=', False)]
        for fname, fval in record_fields.items():
            if fval:
                domain.append((fname, '=', fval))
        alerts = self.search(domain)
        if alerts:
            alerts.write({'resolved': True, 'resolve_date': fields.Datetime.now()})

    @api.model
    def _auto_resolve_stale(self):
        """Resuelve alertas cuyos registros ya volvieron a estado normal.
        Actúa como red de seguridad: la resolución principal es reactiva (write()).
        Nota: mo_cancelled NO se resuelve aquí — debe resolverla el usuario a mano.
        """
        now = fields.Datetime.now()

        # Limpiar alertas de OFs subcontratadas — no deben generar alertas de producción
        # Usamos is_subcontracting_location porque las OFs SBC suelen tener bom_id=False
        stale_sc = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', 'in', ('mo_delayed', 'mo_upcoming', 'mo_cancelled', 'qty_mismatch')),
            ('resolved', '=', False),
            ('production_id.location_src_id.is_subcontracting_location', '=', True),
        ])
        if stale_sc:
            stale_sc.write({'resolved': True, 'resolve_date': now})

        # mo_delayed y qty_mismatch: se resuelven cuando la OF termina o se cancela
        stale_mo = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', 'in', ('mo_delayed', 'qty_mismatch')),
            ('resolved', '=', False),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_mo:
            stale_mo.write({'resolved': True, 'resolve_date': now})

        # mo_delayed: también se resuelve si la OF ya no está atrasada
        stale_mo_on_time = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', '=', 'mo_delayed'),
            ('resolved', '=', False),
            ('production_id.date_finished', '>', now),
        ])
        if stale_mo_on_time:
            stale_mo_on_time.write({'resolved': True, 'resolve_date': now})

        # mo_upcoming: se resuelve cuando la OF ya venció (pasa a mo_delayed) o termina/cancela
        stale_upcoming_mo = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', '=', 'mo_upcoming'),
            ('resolved', '=', False),
            '|',
            ('production_id.date_finished', '<', now),
            ('production_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_upcoming_mo:
            stale_upcoming_mo.write({'resolved': True, 'resolve_date': now})

        # po_upcoming: se resuelve cuando la OC ya venció (pasa a po_delayed) o se cancela/completa
        stale_upcoming_po = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', '=', 'po_upcoming'),
            ('resolved', '=', False),
            '|',
            ('purchase_id.date_planned', '<', now),
            ('purchase_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_upcoming_po:
            stale_upcoming_po.write({'resolved': True, 'resolve_date': now})

        stale_po = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', 'in', ('po_delayed', 'po_cancelled')),
            ('resolved', '=', False),
            '|',
            ('purchase_id.state', '=', 'cancel'),
            ('purchase_id.receipt_status', '=', 'full'),
        ])
        if stale_po:
            stale_po.write({'resolved': True, 'resolve_date': now})

        stale_pick = self.search([
            ('company_id', '=', self.env.company.id),
            ('alert_type', '=', 'receipt_delayed'),
            ('resolved', '=', False),
            ('picking_id.state', 'in', ('done', 'cancel')),
        ])
        if stale_pick:
            stale_pick.write({'resolved': True, 'resolve_date': now})
