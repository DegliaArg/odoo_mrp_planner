import calendar as _cal
import logging
from datetime import datetime

import pytz

from odoo import models, fields, api, _
from odoo.addons.odoo_mrp_reschedule.models.mrp_schedule_mixin import no_subcontract_domain

_logger = logging.getLogger(__name__)


class MrpPlannerDashboard(models.TransientModel):
    _name = 'mrp.planner.dashboard'
    _description = 'Panel del planificador de producción'

    name = fields.Char(default='Panel del Planificador')

    # ── Alertas — contadores ─────────────────────────────────────────────────

    alert_total           = fields.Integer(compute='_compute_alert_stats')
    alert_critical        = fields.Integer(compute='_compute_alert_stats')
    alert_warning         = fields.Integer(compute='_compute_alert_stats')
    alert_mo_delayed      = fields.Integer(compute='_compute_alert_stats')
    alert_po_delayed      = fields.Integer(compute='_compute_alert_stats')
    alert_po_cancelled    = fields.Integer(compute='_compute_alert_stats')
    alert_receipt_delayed = fields.Integer(compute='_compute_alert_stats')
    alert_qty_mismatch    = fields.Integer(compute='_compute_alert_stats')
    alert_mo_cancelled    = fields.Integer(compute='_compute_alert_stats')

    # ── Alertas — lista inline ───────────────────────────────────────────────

    urgent_alert_ids = fields.Many2many(
        'mrp.reschedule.alert',
        compute='_compute_inline_alerts',
        string='Alertas críticas',
    )

    # ── OFs — contadores ─────────────────────────────────────────────────────

    mo_total             = fields.Integer(compute='_compute_mo_stats')
    mo_in_progress       = fields.Integer(compute='_compute_mo_stats')
    mo_done              = fields.Integer(compute='_compute_mo_stats')
    mo_delayed           = fields.Integer(compute='_compute_mo_stats')
    mo_reschedule_needed = fields.Integer(compute='_compute_mo_stats')

    # ── OFs — listas inline ──────────────────────────────────────────────────

    delayed_mo_ids    = fields.Many2many('mrp.production', compute='_compute_inline_mos',
                                         string='OFs atrasadas')
    reschedule_mo_ids = fields.Many2many('mrp.production', compute='_compute_inline_mos',
                                         string='OFs para reprogramar')

    # ── OCs — contadores ─────────────────────────────────────────────────────

    po_rfq              = fields.Integer(compute='_compute_po_stats')
    po_to_approve       = fields.Integer(compute='_compute_po_stats')
    po_total            = fields.Integer(compute='_compute_po_stats')
    po_pending          = fields.Integer(compute='_compute_po_stats')
    po_overdue          = fields.Integer(compute='_compute_po_stats')
    po_overdue_critical = fields.Integer(compute='_compute_po_stats')

    # ── OCs — listas inline ──────────────────────────────────────────────────

    rfq_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='Solicitudes de cotización',
    )
    to_approve_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='Por aprobar',
    )
    overdue_po_ids = fields.Many2many(
        'purchase.order',
        compute='_compute_inline_pos',
        string='OCs vencidas',
    )

    # ── Programaciones — contadores ──────────────────────────────────────────

    request_active            = fields.Integer(compute='_compute_request_stats')
    request_calculated        = fields.Integer(compute='_compute_request_stats')
    request_reschedule_needed = fields.Integer(compute='_compute_request_stats')
    req_mos_total             = fields.Integer(compute='_compute_request_stats')
    req_mos_delayed           = fields.Integer(compute='_compute_request_stats')
    req_mos_done              = fields.Integer(compute='_compute_request_stats')

    # ── Programaciones — lista inline ────────────────────────────────────────

    active_request_ids = fields.Many2many(
        'mrp.production.request',
        compute='_compute_inline_requests',
        string='Programaciones activas',
    )

    # ── Carga WC ─────────────────────────────────────────────────────────────

    wc_load_ids = fields.One2many('mrp.planner.wc.load', 'dashboard_id', string='Carga WC')

    # ── Cómputos ─────────────────────────────────────────────────────────────

    @api.depends()
    def _compute_alert_stats(self):
        Alert = self.env['mrp.reschedule.alert']
        base = [('resolved', '=', False)]
        for rec in self:
            rec.alert_total           = Alert.search_count(base)
            rec.alert_critical        = Alert.search_count(base + [('severity', '=', 'critical')])
            rec.alert_warning         = Alert.search_count(base + [('severity', '=', 'warning')])
            rec.alert_mo_delayed      = Alert.search_count(base + [('alert_type', '=', 'mo_delayed')])
            rec.alert_po_delayed      = Alert.search_count(base + [('alert_type', '=', 'po_delayed')])
            rec.alert_po_cancelled    = Alert.search_count(base + [('alert_type', '=', 'po_cancelled')])
            rec.alert_receipt_delayed = Alert.search_count(base + [('alert_type', '=', 'receipt_delayed')])
            rec.alert_qty_mismatch    = Alert.search_count(base + [('alert_type', '=', 'qty_mismatch')])
            rec.alert_mo_cancelled    = Alert.search_count(base + [('alert_type', '=', 'mo_cancelled')])

    @api.depends()
    def _compute_inline_alerts(self):
        for rec in self:
            rec.urgent_alert_ids = self.env['mrp.reschedule.alert'].search(
                [('resolved', '=', False), ('severity', '=', 'critical')],
                order='days_late desc, id desc',
                limit=8,
            )

    @api.depends()
    def _compute_mo_stats(self):
        MO = self.env['mrp.production']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        for rec in self:
            active = MO.search([('state', 'not in', ('done', 'cancel'))] + no_sc)
            rec.mo_total             = len(active)
            rec.mo_in_progress       = len(active.filtered(lambda m: m.state in ('progress', 'to_close')))
            rec.mo_done              = MO.search_count([('state', '=', 'done')] + no_sc)
            rec.mo_delayed           = len(active.filtered(
                lambda m: m.date_finished and m.date_finished < now
            ))
            rec.mo_reschedule_needed = len(active.filtered(lambda m: m.x_reschedule_needed))

    @api.depends()
    def _compute_inline_mos(self):
        MO = self.env['mrp.production']
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        for rec in self:
            rec.delayed_mo_ids = MO.search([
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc, order='date_finished asc', limit=4)
            rec.reschedule_mo_ids = MO.search([
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc, order='date_start asc', limit=4)

    @api.depends()
    def _compute_po_stats(self):
        PO = self.env['purchase.order']
        now = fields.Datetime.now()
        for rec in self:
            rec.po_rfq        = PO.search_count([('state', 'in', ('draft', 'sent'))])
            rec.po_to_approve = PO.search_count([('state', '=', 'to approve')])
            # Approved, not fully received
            active = PO.search([('state', '=', 'purchase'), ('receipt_status', '!=', 'full')])
            overdue = active.filtered(lambda p: p.date_planned and p.date_planned < now)
            rec.po_total            = len(active)
            rec.po_pending          = len(active.filtered(
                lambda p: not p.date_planned or p.date_planned >= now
            ))
            rec.po_overdue          = len(overdue)
            rec.po_overdue_critical = len(overdue.filtered(
                lambda p: (now - p.date_planned).days >= 5
            ))

    @api.depends()
    def _compute_inline_pos(self):
        PO = self.env['purchase.order']
        now = fields.Datetime.now()
        for rec in self:
            rec.rfq_ids = PO.search([
                ('state', 'in', ('draft', 'sent')),
            ], order='date_planned asc', limit=4)
            rec.to_approve_ids = PO.search([
                ('state', '=', 'to approve'),
            ], order='date_planned asc', limit=3)
            rec.overdue_po_ids = PO.search([
                ('state', '=', 'purchase'),
                ('date_planned', '<', now),
                ('receipt_status', '!=', 'full'),
            ], order='date_planned asc', limit=5)

    @api.depends()
    def _compute_request_stats(self):
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()
        for rec in self:
            confirmed = Req.search([('state', '=', 'confirmed')])
            calculated = Req.search([('state', '=', 'calculated')])
            all_mos = confirmed.mapped('item_ids.production_id').filtered(lambda m: m.id)
            rec.request_active     = len(confirmed)
            rec.request_calculated = len(calculated)
            rec.request_reschedule_needed = len(confirmed.filtered(
                lambda r: any(
                    it.production_id and it.production_id.x_reschedule_needed
                    for it in r.item_ids
                )
            ))
            rec.req_mos_total   = len(all_mos)
            rec.req_mos_done    = len(all_mos.filtered(lambda m: m.state == 'done'))
            rec.req_mos_delayed = len(all_mos.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.date_finished and m.date_finished < now
            ))

    @api.depends()
    def _compute_inline_requests(self):
        for rec in self:
            rec.active_request_ids = self.env['mrp.production.request'].search([
                ('state', 'in', ('calculated', 'confirmed')),
            ], order='id desc', limit=6)

    # ── Apertura ─────────────────────────────────────────────────────────────

    @api.model
    def action_open(self):
        rec = self.create({})
        rec._populate_wc_load()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel del planificador'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh(self):
        self.env['mrp.reschedule.alert']._cron_check_delays()
        return self.env['mrp.planner.dashboard'].action_open()

    def _populate_wc_load(self):
        no_sc = no_subcontract_domain(self.env)
        active_mos = self.env['mrp.production'].search(
            [('state', 'not in', ('done', 'cancel'))] + no_sc
        )
        wc_data = {}
        pending_wos = active_mos.mapped('workorder_ids').filtered(
            lambda w: w.state not in ('done', 'cancel') and w.workcenter_id
        )
        for wo in pending_wos:
            wc_id = wo.workcenter_id.id
            if wc_id not in wc_data:
                wc_data[wc_id] = {
                    'wc': wo.workcenter_id,
                    'mo_ids': set(),
                    'hours': 0.0,
                }
            wc_data[wc_id]['mo_ids'].add(wo.production_id.id)
            wc_data[wc_id]['hours'] += (wo.duration_expected or 0.0) / 60.0

        vals_list = [
            {
                'dashboard_id': self.id,
                'workcenter_id': data['wc'].id,
                'mo_count': len(data['mo_ids']),
                'pending_hours': round(data['hours'], 1),
            }
            for data in sorted(wc_data.values(), key=lambda x: x['hours'], reverse=True)[:15]
        ]
        if vals_list:
            self.env['mrp.planner.wc.load'].create(vals_list)

    # ── Accesos rápidos ──────────────────────────────────────────────────────

    def action_new_request(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva programación'),
            'res_model': 'mrp.production.request',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new_plan(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nuevo plan de reprogramación'),
            'res_model': 'mrp.reschedule.plan',
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Navegación — alertas ─────────────────────────────────────────────────

    def _open_alerts(self, extra_domain=None):
        domain = [('resolved', '=', False)] + (extra_domain or [])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Alertas'),
            'res_model': 'mrp.reschedule.alert',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_alerts(self):
        return self._open_alerts()

    def action_view_critical(self):
        return self._open_alerts([('severity', '=', 'critical')])

    def action_view_warning(self):
        return self._open_alerts([('severity', '=', 'warning')])

    def action_view_mo_delayed_alerts(self):
        return self._open_alerts([('alert_type', '=', 'mo_delayed')])

    def action_view_po_delayed_alerts(self):
        return self._open_alerts([('alert_type', '=', 'po_delayed')])

    def action_view_po_cancelled_alerts(self):
        return self._open_alerts([('alert_type', '=', 'po_cancelled')])

    def action_view_receipt_alerts(self):
        return self._open_alerts([('alert_type', '=', 'receipt_delayed')])

    def action_view_qty_mismatch_alerts(self):
        return self._open_alerts([('alert_type', '=', 'qty_mismatch')])

    def action_view_mo_cancelled_alerts(self):
        return self._open_alerts([('alert_type', '=', 'mo_cancelled')])

    # ── Navegación — OFs ─────────────────────────────────────────────────────

    def _open_mos(self, domain, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_all_mos(self):
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', 'not in', ('done', 'cancel'))] + no_sc,
            _('OFs activas'),
        )

    def action_view_in_progress_mos(self):
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', 'in', ('progress', 'to_close'))] + no_sc,
            _('OFs en progreso'),
        )

    def action_view_delayed_mos(self):
        now = fields.Datetime.now()
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [
                ('state', 'in', ('confirmed', 'progress', 'to_close')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ] + no_sc,
            _('OFs atrasadas'),
        )

    def action_view_reschedule_needed(self):
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [
                ('state', 'not in', ('done', 'cancel')),
                ('x_reschedule_needed', '=', True),
            ] + no_sc,
            _('OFs para reprogramar'),
        )

    def action_view_done_mos(self):
        no_sc = no_subcontract_domain(self.env)
        return self._open_mos(
            [('state', '=', 'done')] + no_sc,
            _('OFs completadas'),
        )

    def action_view_wc_load(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Carga de centros de trabajo'),
            'res_model': 'mrp.workorder',
            'view_mode': 'list,form',
            'domain': [('state', 'not in', ('done', 'cancel'))],
            'context': {'group_by': ['workcenter_id']},
            'target': 'current',
        }

    # ── Navegación — OCs ─────────────────────────────────────────────────────

    def action_view_rfqs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Solicitudes de cotización'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', 'in', ('draft', 'sent'))],
            'target': 'current',
        }

    def action_view_to_approve(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Por aprobar'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'to approve')],
            'target': 'current',
        }

    def action_view_pending_pos(self):
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs a tiempo'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'purchase'),
                ('date_planned', '>=', now),
                ('receipt_status', '!=', 'full'),
            ],
            'target': 'current',
        }

    def action_view_overdue_pos(self):
        now = fields.Datetime.now()
        return {
            'type': 'ir.actions.act_window',
            'name': _('OCs vencidas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'purchase'),
                ('date_planned', '<', now),
                ('receipt_status', '!=', 'full'),
            ],
            'target': 'current',
        }

    def action_view_all_pos(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de compra activas'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'purchase'), ('receipt_status', '!=', 'full')],
            'target': 'current',
        }

    # ── Navegación — Programaciones ──────────────────────────────────────────

    def action_view_active_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con OFs creadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_calculated_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones calculadas'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'calculated')],
            'target': 'current',
        }

    def action_view_requests_reschedule(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con reprogramación pendiente'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'confirmed'),
                ('item_ids.production_id.x_reschedule_needed', '=', True),
            ],
            'target': 'current',
        }

    # ── Gráfico de carga WC ──────────────────────────────────────────────────

    @api.model
    def get_wc_tags(self):
        """Tags de centros de trabajo que tienen al menos un WC activo."""
        Tag = self.env['mrp.workcenter.tag']
        Wc  = self.env['mrp.workcenter']
        result = []
        for tag in Tag.search([]):
            if Wc.search_count([('tag_ids', 'in', tag.id), ('active', '=', True)]):
                result.append({'id': tag.id, 'name': tag.name})
        return result

    @api.model
    def get_wc_machines(self, tag_id=None):
        """Centros de trabajo activos, opcionalmente filtrados por tag."""
        domain = [('active', '=', True)]
        if tag_id:
            domain.append(('tag_ids', 'in', int(tag_id)))
        wcs = self.env['mrp.workcenter'].search(domain, order='name')
        return [{'id': wc.id, 'name': wc.name} for wc in wcs]

    @api.model
    def get_wc_chart_data(self, date_from, date_to, tag_id=None, workcenter_id=None):
        """Devuelve datos de carga por WC para el rango indicado.

        Bar 1 — Disponible: horas del calendario en el rango (referencia).
        Bar 2 — Real apilada: ejecutado + pendiente + tiempo_muerto,
                donde tiempo_muerto = max(0, disponible - ejecutado - pendiente).

        El filtro usa overlap real: date_start <= date_to AND date_finished >= date_from.
        Las horas de workorders que cruzan los límites del rango se calculan
        proporcionalmente al solapamiento.
        """
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        days_in_range = (last_day - first_day).days + 1

        domain = [('active', '=', True)]
        if tag_id:
            domain.append(('tag_ids', 'in', int(tag_id)))
        if workcenter_id:
            domain.append(('id', '=', int(workcenter_id)))
        workcenters = self.env['mrp.workcenter'].search(domain)

        labels, wc_ids, avail_list = [], [], []
        ejecutado_list, pendiente_list, tiempo_muerto_list = [], [], []

        def _avail_hours(calendar, dt_start, dt_end, efficiency):
            try:
                h = calendar.get_work_hours_count(
                    dt_start.replace(tzinfo=pytz.UTC),
                    dt_end.replace(tzinfo=pytz.UTC),
                    compute_leaves=False,
                )
                return h * (efficiency or 100.0) / 100.0
            except Exception as e:
                _logger.debug("WC chart: error calendario %s: %s", calendar.name, e)
                weekly = sum(
                    a.hour_to - a.hour_from
                    for a in calendar.attendance_ids
                    if not a.date_from and not a.date_to
                )
                span = (dt_end - dt_start).days + 1
                return weekly * (span / 7.0) * (efficiency or 100.0) / 100.0

        def _overlap_hours(wo, range_start, range_end):
            """Horas del workorder que caen dentro del rango, proporcional al solapamiento."""
            start = wo.date_start
            end   = wo.date_finished
            if not start:
                return 0.0
            ov_start = max(start, range_start)
            ov_end   = min(end, range_end) if end else range_end
            if ov_start >= ov_end:
                return 0.0
            if not end:
                return (wo.duration_expected or 0.0) / 60.0
            total_secs = (end - start).total_seconds()
            if total_secs <= 0:
                return (wo.duration_expected or 0.0) / 60.0
            proportion = (ov_end - ov_start).total_seconds() / total_secs
            return (wo.duration_expected or 0.0) / 60.0 * proportion

        for wc in workcenters:
            efficiency = wc.time_efficiency or 100.0

            # Horas disponibles del calendario en el rango
            avail = 0.0
            if wc.resource_calendar_id:
                avail = _avail_hours(wc.resource_calendar_id, first_day, last_day, efficiency)

            # Workorders que solapan con el rango (overlap real)
            wos = self.env['mrp.workorder'].search([
                ('workcenter_id', '=', wc.id),
                ('state', 'not in', ('cancel',)),
                ('date_start', '!=', False),
                ('date_start', '<=', fields.Datetime.to_string(last_day)),
                '|',
                ('date_finished', '>=', fields.Datetime.to_string(first_day)),
                ('date_finished', '=', False),
            ])

            ejecutado = sum(
                _overlap_hours(w, first_day, last_day)
                for w in wos if w.state == 'done'
            )
            pendiente = sum(
                _overlap_hours(w, first_day, last_day)
                for w in wos if w.state not in ('done', 'cancel')
            )
            tiempo_muerto = max(0.0, avail - ejecutado - pendiente)

            if avail == 0.0 and ejecutado == 0.0 and pendiente == 0.0:
                continue

            labels.append(wc.name)
            wc_ids.append(wc.id)
            avail_list.append(round(avail, 1))
            ejecutado_list.append(round(ejecutado, 1))
            pendiente_list.append(round(pendiente, 1))
            tiempo_muerto_list.append(round(tiempo_muerto, 1))

        tot_avail = sum(avail_list)
        tot_ejec  = sum(ejecutado_list)
        tot_pend  = sum(pendiente_list)
        tot_plan  = tot_ejec + tot_pend
        tot_libre = sum(tiempo_muerto_list)
        carga_pct = round(tot_plan / tot_avail * 100, 1) if tot_avail > 0 else 0.0

        return {
            'labels':          labels,
            'wc_ids':          wc_ids,
            'available_hours': avail_list,
            'ejecutado':       ejecutado_list,
            'pendiente':       pendiente_list,
            'tiempo_muerto':   tiempo_muerto_list,
            'totals': {
                'disponible':  round(tot_avail, 1),
                'planificado': round(tot_plan,  1),
                'carga_pct':   carga_pct,
                'ejecutado':   round(tot_ejec,  1),
                'pendiente':   round(tot_pend,  1),
                'tiempo_libre': round(tot_libre, 1),
            },
        }

    # ── Widget OCs con pestañas ──────────────────────────────────────────────

    @api.model
    def get_po_dashboard_data(self, filter_type='all', date_from=None, date_to=None, sort_field=None, sort_dir='asc', page=1, page_size=50):
        """Datos de OCs filtrados por tipo y rango de fecha de entrega."""
        PO      = self.env['purchase.order']
        Picking = self.env['stock.picking']
        now     = fields.Datetime.now()

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _rev = (_sd == 'desc')
        _PO_FIELD = {
            'name': 'name', 'partner': 'partner_id',
            'date_planned': 'date_planned', 'amount_total': 'amount_total',
        }
        _PICK_FIELD = {
            'name': 'name', 'partner': 'partner_id',
            'scheduled_date': 'scheduled_date', 'overdue': 'scheduled_date',
            'availability': 'state',
        }
        po_f       = _PO_FIELD.get(sort_field, 'date_planned')
        pick_f     = _PICK_FIELD.get(sort_field, 'scheduled_date')
        po_order   = f'{po_f} {_sd}'
        pick_order = f'{pick_f} {_sd}'
        offset     = (max(1, page) - 1) * page_size

        sc_domain = []
        if filter_type == 'purchase':
            sc_domain = [('subcontract_production_ids', '=', False)]
        elif filter_type == 'subcontract':
            sc_domain = [('subcontract_production_ids', '!=', False)]

        date_domain = []
        if date_from:
            date_domain.append(('date_planned', '>=', date_from + ' 00:00:00'))
        if date_to:
            date_domain.append(('date_planned', '<=', date_to + ' 23:59:59'))

        sched_domain = []
        if date_from:
            sched_domain.append(('scheduled_date', '>=', date_from + ' 00:00:00'))
        if date_to:
            sched_domain.append(('scheduled_date', '<=', date_to + ' 23:59:59'))

        rfq_dom      = [('state', 'in', ('draft', 'sent'))] + sc_domain + date_domain
        approve_dom  = [('state', '=', 'to approve')] + sc_domain + date_domain
        approved_dom = [('state', '=', 'purchase'), ('receipt_status', '!=', 'full')] + sc_domain + date_domain

        approved = PO.search(approved_dom)
        overdue  = approved.filtered(lambda p: p.date_planned and p.date_planned < now)
        pending  = approved.filtered(lambda p: not p.date_planned or p.date_planned >= now)

        # Leer umbral crítico OC desde config
        cfg = self.env['mrp.reschedule.config'].search([], limit=1)
        po_crit_days = cfg.alert_po_critical_days if cfg else 5

        def _po_dict(po):
            return {
                'id':           po.id,
                'name':         po.name,
                'partner':      po.partner_id.display_name if po.partner_id else '',
                'date_planned': po.date_planned.strftime('%d/%m/%Y') if po.date_planned else '—',
                'amount_total': po.amount_total,
                'is_subcontract': bool(po.subcontract_production_ids),
            }

        _AVAIL_LABEL = {
            'assigned':           'Disponible',
            'partially_available': 'Parcialmente',
            'confirmed':          'No disponible',
            'waiting':            'No disponible',
        }

        def _pick_dict(p):
            return {
                'id':             p.id,
                'name':           p.name,
                'partner':        p.partner_id.display_name if p.partner_id else '',
                'scheduled_date': p.scheduled_date.strftime('%d/%m/%Y') if p.scheduled_date else '—',
                'state':          p.state,
                'overdue':        bool(p.scheduled_date and p.scheduled_date < now),
                'availability':   p.state,
                'availability_label': _AVAIL_LABEL.get(p.state, '—'),
            }

        rfqs_list       = PO.search(rfq_dom,     order=po_order)
        to_approve_list = PO.search(approve_dom, order=po_order)

        # ── Separar servicios ────────────────────────────────────────────────
        show_svc = bool(cfg and cfg.show_po_services_tab)

        def _is_svc(po):
            lines = po.order_line.filtered(lambda l: l.product_id)
            return bool(lines) and all(l.product_id.type == 'service' for l in lines)

        if show_svc:
            rfqs_svc        = rfqs_list.filtered(_is_svc)
            rfqs_list       = rfqs_list - rfqs_svc
            approve_svc     = to_approve_list.filtered(_is_svc)
            to_approve_list = to_approve_list - approve_svc
            approved_svc    = approved.filtered(_is_svc)
            approved        = approved - approved_svc
            overdue         = overdue - approved_svc
            pending         = pending - approved_svc
            services_rs     = (rfqs_svc | approve_svc | approved_svc).sorted(po_f, reverse=_rev)
        else:
            services_rs     = self.env['purchase.order']

        overdue_list  = overdue.sorted(po_f,  reverse=_rev)
        all_pos_list  = approved.sorted(po_f, reverse=_rev)
        pending_list  = pending.sorted(po_f,  reverse=_rev)

        rfqs_pg       = rfqs_list[offset:offset + page_size]
        to_approve_pg = to_approve_list[offset:offset + page_size]
        overdue_pg    = overdue_list[offset:offset + page_size]
        all_pos_pg    = all_pos_list[offset:offset + page_size]
        pending_pg    = pending_list[offset:offset + page_size]

        # ── Recepciones (incoming pickings linked to POs) ────────────────────
        receipt_sc = []
        if filter_type == 'purchase':
            receipt_sc = [('purchase_id.subcontract_production_ids', '=', False)]
        elif filter_type == 'subcontract':
            receipt_sc = [('purchase_id.subcontract_production_ids', '!=', False)]

        receipts = Picking.search([
            ('state', 'not in', ['done', 'cancel']),
            ('picking_type_code', '=', 'incoming'),
            ('purchase_id', '!=', False),
        ] + receipt_sc + sched_domain, order=pick_order)

        receipts_pg      = receipts[offset:offset + page_size]
        overdue_receipts = receipts.filtered(lambda p: p.scheduled_date and p.scheduled_date < now)

        # ── Entregas (component deliveries to subcontractors) ───────────────
        # La OC no es un M2O en estos pickings, es texto. El único campo
        # confiable es el destino: ubicación de subcontratación.
        deliveries = Picking.search([
            ('state', 'not in', ['done', 'cancel']),
            ('location_dest_id.is_subcontracting_location', '=', True),
        ] + sched_domain, order=pick_order)

        deliveries_pg      = deliveries[offset:offset + page_size]
        services_pg        = services_rs[offset:offset + page_size]
        overdue_deliveries = deliveries.filtered(lambda p: p.scheduled_date and p.scheduled_date < now)

        return {
            'kpis': {
                'rfq':              len(rfqs_list),
                'to_approve':       len(to_approve_list),
                'total':            len(approved),
                'pending':          len(pending),
                'overdue':          len(overdue),
                'overdue_critical': len(overdue.filtered(
                    lambda p: (now - p.date_planned).days >= po_crit_days
                )),
                'receipts_total':    len(receipts),
                'receipts_overdue':  len(overdue_receipts),
                'deliveries_total':  len(deliveries),
                'deliveries_overdue': len(overdue_deliveries),
                'services_total':    len(services_rs),
            },
            'show_services_tab': show_svc,
            'rfqs':        [_po_dict(p) for p in rfqs_pg],
            'to_approve':  [_po_dict(p) for p in to_approve_pg],
            'overdue':     [_po_dict(p) for p in overdue_pg],
            'all_pos':     [_po_dict(p) for p in all_pos_pg],
            'pending_pos': [_po_dict(p) for p in pending_pg],
            'receipts':    [_pick_dict(p) for p in receipts_pg],
            'deliveries':  [_pick_dict(p) for p in deliveries_pg],
            'services':    [_po_dict(p) for p in services_pg],
        }

    # ── Widget OFs filtrable ─────────────────────────────────────────────────

    @api.model
    def get_filtered_mos(self, date_from, date_to, tag_id=None):
        """OFs activas (sin subcontratación) que solapan con el rango, filtradas por sector."""
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        no_sc = no_subcontract_domain(self.env)
        domain = [
            ('state', 'not in', ('done', 'cancel')),
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            '&',
            ('date_finished', '=', False),
            ('date_start', '>=', fields.Datetime.to_string(first_day)),
        ] + no_sc

        mos = self.env['mrp.production'].search(domain, order='date_finished asc')

        if tag_id:
            tag_id = int(tag_id)
            mos = mos.filtered(
                lambda m: any(
                    tag_id in w.workcenter_id.tag_ids.ids
                    for w in m.workorder_ids
                    if w.workcenter_id
                )
            )

        now = fields.Datetime.now()
        result = []
        for mo in mos:
            result.append({
                'id':            mo.id,
                'name':          mo.name,
                'product':       mo.product_id.display_name if mo.product_id else '',
                'qty':           mo.product_qty,
                'date_finished': mo.date_finished.strftime('%d/%m/%Y') if mo.date_finished else '',
                'state':         mo.state,
                'delayed':       bool(mo.date_finished and mo.date_finished < now),
                'reschedule':    bool(mo.x_reschedule_needed),
            })
        return result

    # ── Widget OFs con pestañas ──────────────────────────────────────────────

    @api.model
    def get_mo_widget_data(self, date_from, date_to, tag_id=None, sort_field=None, sort_dir='asc', page=1, page_size=50):
        """KPIs + lista de OFs activas en el rango, filtradas por sector."""
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _MO_FIELD = {
            'name': 'name', 'product': 'product_id', 'qty': 'product_qty',
            'date_finished': 'date_finished', 'state': 'state',
            'delayed': 'date_finished', 'reschedule': 'x_reschedule_needed',
        }
        mo_f     = _MO_FIELD.get(sort_field, 'date_finished')
        mo_order = f'{mo_f} {_sd}'

        no_sc = no_subcontract_domain(self.env)
        domain = [
            ('state', 'not in', ('done', 'cancel')),
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            '&',
            ('date_finished', '=', False),
            ('date_start', '>=', fields.Datetime.to_string(first_day)),
        ] + no_sc

        mos = self.env['mrp.production'].search(domain, order=mo_order)

        if tag_id:
            tag_id = int(tag_id)
            tag_filter = lambda m: any(
                tag_id in w.workcenter_id.tag_ids.ids
                for w in m.workorder_ids if w.workcenter_id
            )
            mos = mos.filtered(tag_filter)

        # OFs finalizadas en el mismo rango de fechas
        done_domain = [
            ('state', '=', 'done'),
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            ('date_finished', '<=', fields.Datetime.to_string(last_day)),
        ] + no_sc
        done_mos = self.env['mrp.production'].search(done_domain)
        if tag_id:
            done_mos = done_mos.filtered(tag_filter)

        offset   = (max(1, page) - 1) * page_size
        mos_page = mos[offset:offset + page_size]

        now = fields.Datetime.now()

        # Batch-compute pending outgoing deliveries per product (ítem 7)
        product_ids = list({mo.product_id.id for mo in mos_page if mo.product_id})
        if product_ids:
            out_moves = self.env['stock.move'].search([
                ('product_id', 'in', product_ids),
                ('state', 'not in', ('done', 'cancel')),
                ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ])
            pending_out = {}
            for m in out_moves:
                pid = m.product_id.id
                pending_out[pid] = pending_out.get(pid, 0.0) + m.product_uom_qty
        else:
            pending_out = {}

        def _mo_dict(mo):
            return {
                'id':               mo.id,
                'name':             mo.name,
                'product':          mo.product_id.display_name if mo.product_id else '',
                'qty':              mo.product_qty,
                'date_finished':    mo.date_finished.strftime('%d/%m/%Y') if mo.date_finished else '',
                'state':            mo.state,
                'delayed':          bool(mo.date_finished and mo.date_finished < now),
                'reschedule':       bool(mo.x_reschedule_needed),
                'pending_delivery': round(pending_out.get(mo.product_id.id, 0.0), 2),
            }

        return {
            'kpis': {
                'total':       len(mos),
                'in_progress': len(mos.filtered(lambda m: m.state in ('progress', 'to_close'))),
                'delayed':     len(mos.filtered(lambda m: m.date_finished and m.date_finished < now)),
                'reschedule':  len(mos.filtered(lambda m: m.x_reschedule_needed)),
                'done':        len(done_mos),
                'partial':     len(mos.filtered(lambda m: m.state == 'to_close')),
            },
            'mos': [_mo_dict(m) for m in mos_page],
        }

    @api.model
    def get_request_widget_data(self, sort_field=None, sort_dir='asc', page=1, page_size=50):
        """KPIs + lista de programaciones activas."""
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _REQ_FIELD = {'name': 'name', 'start_from': 'start_from', 'state': 'state'}
        req_f = _REQ_FIELD.get(sort_field, 'id')

        confirmed  = Req.search([('state', '=', 'confirmed')])
        calculated = Req.search([('state', '=', 'calculated')])
        all_active = (confirmed | calculated).sorted(req_f, reverse=(_sd == 'desc'))
        all_mos    = confirmed.mapped('item_ids.production_id').filtered(lambda m: m.id)

        offset          = (max(1, page) - 1) * page_size
        all_active_page = all_active[offset:offset + page_size]

        def _req_dict(r):
            mos = r.item_ids.mapped('production_id').filtered(lambda m: m.id)
            return {
                'id':          r.id,
                'name':        r.name,
                'start_from':  r.start_from.strftime('%d/%m/%Y') if r.start_from else '—',
                'state':       r.state,
                'mos_total':   len(mos),
                'mos_done':    len(mos.filtered(lambda m: m.state == 'done')),
                'mos_delayed': len(mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )),
            }

        return {
            'kpis': {
                'total':       len(all_active),
                'active':      len(confirmed),
                'calculated':  len(calculated),
                'reschedule':  len(confirmed.filtered(
                    lambda r: any(
                        it.production_id and it.production_id.x_reschedule_needed
                        for it in r.item_ids
                    )
                )),
                'mos_delayed': len(all_mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )),
            },
            'requests': [_req_dict(r) for r in all_active_page],
        }

    @api.model
    def get_comparison_data(self, date_from, date_to, tag_id=None):
        """Producido vs programado por producto en el rango."""
        first_day = datetime.strptime(date_from, '%Y-%m-%d')
        last_day  = datetime.strptime(date_to,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)

        no_sc = no_subcontract_domain(self.env)

        done_mos = self.env['mrp.production'].search([
            ('state', '=', 'done'),
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            ('date_finished', '<=', fields.Datetime.to_string(last_day)),
        ] + no_sc)

        active_mos = self.env['mrp.production'].search([
            ('state', 'not in', ('done', 'cancel')),
            ('date_start', '<=', fields.Datetime.to_string(last_day)),
            '|',
            ('date_finished', '>=', fields.Datetime.to_string(first_day)),
            '&',
            ('date_finished', '=', False),
            ('date_start', '>=', fields.Datetime.to_string(first_day)),
        ] + no_sc)

        all_mos = done_mos | active_mos

        if tag_id:
            tag_id = int(tag_id)
            all_mos = all_mos.filtered(
                lambda m: any(
                    tag_id in w.workcenter_id.tag_ids.ids
                    for w in m.workorder_ids if w.workcenter_id
                )
            )

        product_data = {}
        for mo in all_mos:
            pid = mo.product_id.id
            if not pid:
                continue
            if pid not in product_data:
                product_data[pid] = {
                    'product_id':   pid,
                    'product':      mo.product_id.display_name,
                    'uom':          mo.product_uom_id.name if mo.product_uom_id else '',
                    'planned_qty':  0.0,
                    'produced_qty': 0.0,
                }
            product_data[pid]['planned_qty']  += mo.product_qty
            product_data[pid]['produced_qty'] += mo.qty_produced

        items = sorted(product_data.values(), key=lambda x: x['planned_qty'], reverse=True)
        for item in items:
            item['pct'] = round(
                item['produced_qty'] / item['planned_qty'] * 100, 1
            ) if item['planned_qty'] > 0 else 0.0
            item['planned_qty']  = round(item['planned_qty'],  2)
            item['produced_qty'] = round(item['produced_qty'], 2)

        total_planned  = sum(x['planned_qty']  for x in items)
        total_produced = sum(x['produced_qty'] for x in items)
        pct = round(total_produced / total_planned * 100, 1) if total_planned > 0 else 0.0

        filtered_done = all_mos.filtered(lambda m: m.state == 'done')
        return {
            'kpis': {
                'planned':  round(total_planned,  2),
                'produced': round(total_produced, 2),
                'pct':      pct,
                'ofs_done': len(filtered_done),
            },
            'items': items[:20],
        }

    # ── Backwards compat (paneles de detalle) ─────────────────────────────────

    def action_open_mos_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('mos')

    def action_open_pos_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('pos')

    def action_open_requests_dashboard(self):
        return self.env['mrp.planner.detail.dashboard'].action_open_for_category('requests')


class MrpPlannerWcLoad(models.TransientModel):
    _name = 'mrp.planner.wc.load'
    _description = 'Carga de centro de trabajo en el panel'
    _order = 'pending_hours desc'

    dashboard_id  = fields.Many2one('mrp.planner.dashboard', ondelete='cascade')
    workcenter_id = fields.Many2one('mrp.workcenter', string='Centro de trabajo')
    mo_count      = fields.Integer(string='OFs activas')
    pending_hours = fields.Float(string='Horas pendientes', digits=(10, 1))
