"""
Módulo: mrp_planner_dashboard_movements.py (odoo_mrp_planner_dispatch)
Modelo: extensión de mrp.planner.dashboard

Backend del panel "Movimientos pendientes": recepciones y transferencias
pendientes — el complemento exacto del Panel de Inventario, que cubre la
cadena de entrega a clientes.

Universo: pickings pendientes de tipos entrada/interna/salida cuyo destino
NO es una ubicación de cliente (las entregas a clientes viven en el Panel de
Inventario), excluyendo además los eslabones de recolección/embalaje de la
cadena de entrega. Cubre compras por recibir, transferencias internas y los
tramos entre depósitos de las rutas de reabastecimiento (aunque usen un tipo
de salida).

Todo se calcula en vivo: sin snapshots, sin tasa y sin circuito de despacho.
Mismos grupos que el Panel de Inventario (acá no hay acciones de escritura).
"""
from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api, _

PENDING_PICKING_STATES = ('confirmed', 'waiting', 'assigned')

MOVEMENT_TYPE_CODES = ('incoming', 'internal', 'outgoing')


class MrpPlannerDashboard(models.TransientModel):
    _inherit = 'mrp.planner.dashboard'

    # ── Apertura del panel ────────────────────────────────────────────────────

    @api.model
    def action_open_movements(self):
        """Abre el panel de Movimientos pendientes (form sin barra de control)."""
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Movimientos pendientes'),
            'res_model': 'mrp.planner.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'view_id': self.env.ref('odoo_mrp_planner_dispatch.mrp_movements_dashboard_form').id,
            'target': 'main',
            'flags': {'withControlPanel': False},
        }

    def action_refresh_movements(self):
        """Botón Actualizar del panel: reabre la vista con un registro nuevo."""
        return self.action_open_movements()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @api.model
    def _movements_excluded_type_ids(self, company):
        """Eslabones de recolección/embalaje de la cadena de entrega: son
        demanda de clientes y pertenecen al Panel de Inventario, no acá."""
        _ids, info = self.env['mrp.dispatch.stock.log'] \
            ._dispatch_chain_types(company)
        return [t for t, i in info.items() if i[2] != 'ship']

    @api.model
    def get_movements_picking_types(self, warehouse_ids=None):
        """Tipos de operación del panel de Movimientos para el filtro:
        entradas, internas y salidas (las salidas por sus tramos no-cliente),
        sin los eslabones pick/pack de la cadena de entrega.

        :returns: list[dict] — {'id', 'name'} ordenados por nombre.
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        dom = [
            ('company_id', '=', company.id),
            ('code', 'in', MOVEMENT_TYPE_CODES),
            ('id', 'not in', self._movements_excluded_type_ids(company)),
        ]
        if warehouse_ids:
            dom.append(('warehouse_id', 'in', warehouse_ids))
        types = self.env['stock.picking.type'].sudo().search(dom).read(['display_name'])
        return sorted(({'id': t['id'], 'name': t['display_name']} for t in types),
                      key=lambda d: d['name'])

    # ── Tabla (los KPIs y el gráfico se derivan de las filas en el cliente) ──

    @api.model
    def get_movements_pending_table(self, date_from=None, date_to=None,
                                    warehouse_ids=None, picking_type_ids=None,
                                    search=''):
        """
        Movimientos pendientes (una fila por remito): recepciones,
        transferencias internas y tramos de salida sin destino cliente.
        Respeta el corte de antigüedad de Ajustes, igual que el Panel de
        Inventario.

        :param date_from/date_to: filtro opcional sobre la fecha programada
                                  (días locales del usuario).
        :param warehouse_ids: filtro opcional de depósitos.
        :param picking_type_ids: filtro opcional de tipos de operación.
        :param search: texto contra remito / origen.
        :returns: dict {'rows': list[dict]}
        """
        self._inventory_ensure_group()
        warehouse_ids = self._inventory_effective_whs(warehouse_ids)
        company = self.env.company
        cfg = self.env['mrp.reschedule.config'].sudo().get_config()
        dom = [
            ('company_id', '=', company.id),
            ('state', 'in', list(PENDING_PICKING_STATES)),
            ('picking_type_id.code', 'in', MOVEMENT_TYPE_CODES),
            # Las entregas a clientes viven en el Panel de Inventario
            ('location_dest_id.usage', '!=', 'customer'),
        ] + cfg._dispatch_pending_cutoff_domain('scheduled_date')
        excluded = self._movements_excluded_type_ids(company)
        if excluded:
            dom.append(('picking_type_id', 'not in', excluded))
        if warehouse_ids:
            dom.append(('picking_type_id.warehouse_id', 'in', warehouse_ids))
        if picking_type_ids:
            dom.append(('picking_type_id', 'in', picking_type_ids))
        # Fechas del filtro interpretadas como días locales del usuario
        tz = self._inventory_tz()
        to_utc = lambda d: tz.localize(datetime.combine(d, datetime.min.time())) \
            .astimezone(pytz.utc).replace(tzinfo=None)
        if date_from:
            dom.append(('scheduled_date', '>=',
                        to_utc(fields.Date.from_string(date_from))))
        if date_to:
            dom.append(('scheduled_date', '<',
                        to_utc(fields.Date.from_string(date_to) + timedelta(days=1))))
        if search:
            dom += ['|',
                    ('name', 'ilike', search),
                    ('origin', 'ilike', search)]
        picks = self.env['stock.picking'].sudo().search(dom, order='scheduled_date asc')
        if not picks:
            return {'rows': []}

        # Origen con link: compra (recepciones) o venta (tramos con grupo de
        # abastecimiento); texto plano si no hay documento asociado.
        has_purchase = 'purchase_id' in picks._fields
        has_sale = 'sale_id' in picks._fields
        extra = (['purchase_id'] if has_purchase else []) + (['sale_id'] if has_sale else [])
        pick_rows = picks.read(['name', 'partner_id', 'origin', 'scheduled_date',
                                'state', 'picking_type_id', 'location_id',
                                'location_dest_id'] + extra)

        # Tipo de operación → nombre / código / depósito
        type_ids = {r['picking_type_id'][0] for r in pick_rows if r['picking_type_id']}
        type_info = {t['id']: t for t in self.env['stock.picking.type'].sudo()
                     .browse(list(type_ids)).read(['display_name', 'code', 'warehouse_id'])}

        # Cantidades y artículos por remito (mismo esquema que el Panel de Inventario)
        qty = {}    # {pick_id: [pending, {product_id: display_name}]}
        moves = self.env['stock.move'].sudo().search([
            ('picking_id', 'in', picks.ids),
            ('state', 'not in', ('draft', 'done', 'cancel')),
        ])
        for r in moves.read(['picking_id', 'product_id', 'product_uom_qty']):
            pick = r['picking_id'][0] if r['picking_id'] else False
            if not pick:
                continue
            qty.setdefault(pick, [0.0, {}])
            qty[pick][0] += r['product_uom_qty'] or 0.0
            if r['product_id']:
                qty[pick][1][r['product_id'][0]] = r['product_id'][1]

        today = fields.Date.context_today(self)
        rows = []
        for r in pick_rows:
            pid = r['id']
            tinfo = type_info.get(r['picking_type_id'][0] if r['picking_type_id'] else 0)
            pending, prods = qty.get(pid, [0.0, {}])
            detail = sorted(({'id': p_id, 'name': p_name} for p_id, p_name in prods.items()),
                            key=lambda d: d['name'])
            names = [d['name'] for d in detail]
            sched = r['scheduled_date']
            if sched:
                sched_local = pytz.utc.localize(sched).astimezone(tz)
                sched_str = sched_local.strftime('%d/%m/%Y')
                overdue = (today - sched_local.date()).days
            else:
                sched_str, overdue = '', 0
            if has_purchase and r.get('purchase_id'):
                origin_model, origin_id = 'purchase.order', r['purchase_id'][0]
            elif has_sale and r.get('sale_id'):
                origin_model, origin_id = 'sale.order', r['sale_id'][0]
            else:
                origin_model, origin_id = False, False
            rows.append({
                'picking_id':    pid,
                'name':          r['name'],
                'type_name':     tinfo['display_name'] if tinfo else '',
                'type_code':     tinfo['code'] if tinfo else '',
                'warehouse':     (tinfo['warehouse_id'][1]
                                  if tinfo and tinfo['warehouse_id'] else ''),
                'origin':        r['origin'] or '',
                'origin_model':  origin_model,
                'origin_id':     origin_id,
                'partner':       r['partner_id'][1] if r['partner_id'] else '',
                'loc_from':      r['location_id'][1] if r['location_id'] else '',
                'loc_to':        r['location_dest_id'][1] if r['location_dest_id'] else '',
                'scheduled':     sched_str,
                'overdue_days':  max(0, overdue),
                'state':         r['state'],
                'qty_pending':   self._inventory_qround(cfg, pending),
                'products':      len(detail),
                'product_names': ', '.join(names[:3]) + ('…' if len(names) > 3 else ''),
                'products_detail': detail,
            })
        return {'rows': rows}
