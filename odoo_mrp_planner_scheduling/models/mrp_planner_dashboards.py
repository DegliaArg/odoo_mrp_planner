"""
Módulo: mrp_planner_dashboards.py (odoo_mrp_planner_scheduling)

Extiende los paneles del planificador con la parte de Programaciones:
- mrp.planner.detail.dashboard: agrega la categoría 'requests' con sus KPIs
  (programaciones activas, con reprogramación, OFs asociadas) y sus acciones
  de navegación.
- mrp.planner.dashboard: agrega get_request_widget_data, que alimenta la
  pestaña "Programaciones" del widget de OFs (visible solo cuando la
  programación está habilitada).
"""
from odoo import models, fields, api, _


class MrpPlannerDetailDashboard(models.TransientModel):
    _inherit = 'mrp.planner.detail.dashboard'

    category = fields.Selection(
        selection_add=[('requests', 'Programaciones')],
        ondelete={'requests': 'cascade'},
    )

    # ── Programaciones (category='requests') ─────────────────────────────────
    req_total       = fields.Integer(compute='_compute_req_stats')
    req_reschedule  = fields.Integer(compute='_compute_req_stats')
    req_mos_total   = fields.Integer(compute='_compute_req_stats')
    req_mos_delayed = fields.Integer(compute='_compute_req_stats')
    req_mos_done    = fields.Integer(compute='_compute_req_stats')

    @api.depends('category')
    def _compute_req_stats(self):
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()
        for rec in self:
            cat = rec.category
            if cat == 'requests':
                reqs = Req.search([('state', '=', 'confirmed')])
                all_mos = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id)
                delayed_req = all_mos.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                    and m.date_finished and m.date_finished < now
                )
                rec.req_total       = len(reqs)
                rec.req_reschedule  = len(reqs.filtered(
                    lambda r: any(
                        it.production_id and it.production_id.x_reschedule_needed
                        for it in r.item_ids
                    )
                ))
                rec.req_mos_total   = len(all_mos)
                rec.req_mos_delayed = len(delayed_req)
                rec.req_mos_done    = len(all_mos.filtered(lambda m: m.state == 'done'))
            else:
                rec.req_total = rec.req_reschedule = 0
                rec.req_mos_total = rec.req_mos_delayed = rec.req_mos_done = 0

    # ── Navegación — Programaciones ───────────────────────────────────────────

    def action_view_all_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones en curso'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'confirmed')],
            'target': 'current',
        }

    def action_view_reschedule_requests(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programaciones con reprogramación'),
            'res_model': 'mrp.production.request',
            'view_mode': 'list,form',
            'domain': [
                ('state', '=', 'confirmed'),
                ('item_ids.production_id.x_reschedule_needed', '=', True),
            ],
            'target': 'current',
        }

    def action_view_req_mos(self):
        reqs = self.env['mrp.production.request'].search([('state', '=', 'confirmed')])
        mo_ids = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs en programaciones activas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mo_ids)],
            'target': 'current',
        }

    def action_view_req_delayed_mos(self):
        now = fields.Datetime.now()
        reqs = self.env['mrp.production.request'].search([('state', '=', 'confirmed')])
        mo_ids = reqs.mapped('item_ids.production_id').filtered(lambda m: m.id).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('OFs atrasadas en programaciones'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [
                ('id', 'in', mo_ids),
                ('state', 'not in', ('done', 'cancel')),
                ('date_finished', '<', now),
                ('date_finished', '!=', False),
            ],
            'target': 'current',
        }


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    request_active            = fields.Integer(compute='_compute_request_stats', help='Programaciones en estado confirmado (OFs ya generadas).')
    request_calculated        = fields.Integer(compute='_compute_request_stats', help='Programaciones en estado calculado (pendientes de confirmación).')
    request_reschedule_needed = fields.Integer(compute='_compute_request_stats', help='Programaciones confirmadas que tienen al menos una OF con reprogramación pendiente.')
    req_mos_total             = fields.Integer(compute='_compute_request_stats', help='Total de OFs vinculadas a programaciones confirmadas.')
    req_mos_delayed           = fields.Integer(compute='_compute_request_stats', help='OFs vinculadas a programaciones confirmadas que están atrasadas.')
    req_mos_done              = fields.Integer(compute='_compute_request_stats', help='OFs vinculadas a programaciones confirmadas que ya están completadas.')

    # ── Programaciones — lista inline ────────────────────────────────────────

    active_request_ids = fields.Many2many(
        'mrp.production.request',
        compute='_compute_inline_requests',
        string='Programaciones activas',
        help='Hasta 6 programaciones en estado calculado o confirmado, ordenadas por ID descendente para el widget inline del dashboard.',
    )

    @api.depends()
    def _compute_request_stats(self):
        """
        Calcula los contadores de programaciones de producción para el panel.

        Fórmula: request_active y request_calculated se obtienen con search_count
        (una query COUNT por estado). Las métricas sobre OFs vinculadas se calculan
        con read_group sobre mrp.production.request.item para evitar cargar registros
        en memoria — una sola query GROUP BY por contador en lugar de mapped() +
        filtered() en Python.

        request_reschedule_needed: programaciones confirmadas que tienen al menos
        un item cuya OF tenga x_reschedule_needed=True. Se resuelve con un search
        sobre los items filtrado por la OF, luego len(set(...)) para deduplicar.

        Depende de: mrp.production.request (state),
                    mrp.production.request.item (request_id, production_id),
                    mrp.production (state, date_finished, x_reschedule_needed).
        """
        Req = self.env['mrp.production.request']
        Item = self.env['mrp.production.request.item']
        now = fields.Datetime.now()
        for rec in self:
            confirmed_ids = Req.search([('state', '=', 'confirmed')]).ids
            rec.request_active     = len(confirmed_ids)
            rec.request_calculated = Req.search_count([('state', '=', 'calculated')])

            if not confirmed_ids:
                rec.request_reschedule_needed = 0
                rec.req_mos_total   = 0
                rec.req_mos_done    = 0
                rec.req_mos_delayed = 0
                continue

            # ── req_mos_total: cantidad de OFs distintas vinculadas a confirmed ──
            # read_group emite: SELECT request_id, COUNT(DISTINCT production_id) ...
            # GROUP BY request_id  → O(1) en SQL en lugar de mapped() en Python.
            groups_total = Item.read_group(
                [('request_id', 'in', confirmed_ids), ('production_id', '!=', False)],
                fields=['production_id:count_distinct'],
                groupby=[],
            )
            rec.req_mos_total = groups_total[0]['production_id'] if groups_total else 0

            # ── req_mos_done: OFs en estado 'done' vinculadas a confirmed ────────
            groups_done = Item.read_group(
                [
                    ('request_id', 'in', confirmed_ids),
                    ('production_id', '!=', False),
                    ('production_id.state', '=', 'done'),
                ],
                fields=['production_id:count_distinct'],
                groupby=[],
            )
            rec.req_mos_done = groups_done[0]['production_id'] if groups_done else 0

            # ── req_mos_delayed: OFs activas con date_finished vencido ───────────
            groups_delayed = Item.read_group(
                [
                    ('request_id', 'in', confirmed_ids),
                    ('production_id', '!=', False),
                    ('production_id.state', 'not in', ('done', 'cancel')),
                    ('production_id.date_finished', '!=', False),
                    ('production_id.date_finished', '<', now),
                ],
                fields=['production_id:count_distinct'],
                groupby=[],
            )
            rec.req_mos_delayed = groups_delayed[0]['production_id'] if groups_delayed else 0

            # ── request_reschedule_needed: programaciones con ≥1 OF pendiente ───
            # search sobre items filtrando directamente por la OF marcada; luego
            # deduplicar request_id con un set para contar programaciones únicas.
            items_reschedule = Item.search([
                ('request_id', 'in', confirmed_ids),
                ('production_id', '!=', False),
                ('production_id.x_reschedule_needed', '=', True),
            ])
            rec.request_reschedule_needed = len(set(items_reschedule.mapped('request_id').ids))

    @api.depends()
    def _compute_inline_requests(self):
        """
        Calcula la lista reducida de programaciones activas para el widget inline.

        Fórmula: últimas 6 programaciones en estado calculado o confirmado,
        ordenadas por ID descendente (más recientes primero).
        Depende de: mrp.production.request (state).
        """
        for rec in self:
            rec.active_request_ids = self.env['mrp.production.request'].search([
                ('state', 'in', ('calculated', 'confirmed')),
            ], order='id desc', limit=6)

    @api.model
    def get_request_widget_data(self, sort_field=None, sort_dir='asc', page=1, page_size=50, search=None):
        """
        Retorna KPIs y la página de programaciones de producción activas (confirmed + calculated).

        Cada programación incluye un resumen de sus OFs: total, finalizadas y retrasadas.
        El KPI 'reschedule' cuenta programaciones confirmadas que tienen al menos una OF
        con x_reschedule_needed activado.

        :param sort_field: str|None — campo lógico de ordenamiento ('name', 'start_from', 'state').
        :param sort_dir: 'asc' o 'desc'.
        :param page: int — página a devolver (base 1).
        :param page_size: int — cantidad máxima de registros por página.
        :param search: str|None — filtro de texto sobre nombre o fecha de inicio de la programación.
        :returns: dict con:
                  - kpis (dict): total, active (confirmed), calculated, reschedule, mos_delayed.
                  - requests (list[dict]): registros de la página con id, name, start_from, state,
                    mos_total, mos_done, mos_delayed.
        """
        Req = self.env['mrp.production.request']
        now = fields.Datetime.now()

        _sd = 'desc' if sort_dir == 'desc' else 'asc'
        _REQ_FIELD = {'name': 'name', 'start_from': 'start_from', 'state': 'state'}
        req_f = _REQ_FIELD.get(sort_field, 'id')

        _req_co = [('company_id', '=', self.env.company.id)]
        confirmed  = Req.search([('state', '=', 'confirmed')] + _req_co)
        calculated = Req.search([('state', '=', 'calculated')] + _req_co)
        all_active = (confirmed | calculated).sorted(req_f, reverse=(_sd == 'desc'))
        all_mos    = confirmed.mapped('item_ids.production_id').filtered(lambda m: m.id)

        if search:
            _s = search.strip().lower()
            all_active = all_active.filtered(
                lambda r: _s in (r.name or '').lower()
                or _s in (r.start_from.strftime('%d/%m/%Y') if r.start_from else '')
            )

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

        exec_running = len(all_mos.filtered(lambda m: m.state in ('progress', 'done')))
        exec_total   = len(all_mos)
        exec_rate    = round(exec_running / exec_total * 100, 1) if exec_total > 0 else 0.0
        no_materials = len(all_mos.filtered(
            lambda m: m.state == 'confirmed' and m.reservation_state != 'assigned'
        ))

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
                'exec_running': exec_running,
                'exec_total':   exec_total,
                'exec_rate':    exec_rate,
                'no_materials': no_materials,
            },
            'requests': [_req_dict(r) for r in all_active_page],
        }
