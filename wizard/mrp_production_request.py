import logging
import pytz
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INDENT_MAP = {0: '', 1: '└─ ', 2: '   └─ ', 3: '      └─ '}


class MrpProductionRequestItem(models.TransientModel):
    """Una fila de entrada: qué fabricar, cuánto y para cuándo."""
    _name = 'mrp.production.request.item'
    _description = 'Artículo de solicitud de programación'
    _order = 'sequence, id'
    _rec_name = 'name'

    request_id  = fields.Many2one('mrp.production.request', required=True, ondelete='cascade')
    sequence    = fields.Integer(default=10)
    name        = fields.Char(compute='_compute_name', store=True)
    product_id  = fields.Many2one('product.product', string='Producto', required=True,
                                  domain=[('type', 'in', ['consu', 'product'])])
    product_qty = fields.Float(string='Cantidad', default=1.0, required=True)
    date_deadline = fields.Datetime(string='Fecha de entrega deseada', required=True)

    # Resultado del cálculo — se escribe al calcular
    projected_end   = fields.Datetime(string='Fin proyectado', readonly=True)
    feasible        = fields.Boolean(compute='_compute_feasible', store=False)
    feasibility_msg = fields.Char(compute='_compute_feasible', store=False, string='Δ Plazo')

    @api.depends('product_id')
    def _compute_name(self):
        for item in self:
            item.name = item.product_id.display_name or '—'

    @api.depends('projected_end', 'date_deadline')
    def _compute_feasible(self):
        for item in self:
            if not item.projected_end or not item.date_deadline:
                item.feasible = False
                item.feasibility_msg = '—'
                continue
            if item.projected_end <= item.date_deadline:
                secs = (item.date_deadline - item.projected_end).total_seconds()
                d, h = int(secs // 86400), int((secs % 86400) // 3600)
                item.feasible = True
                item.feasibility_msg = f'+{d}d {h}h' if d else f'+{h}h'
            else:
                secs = (item.projected_end - item.date_deadline).total_seconds()
                d, h = int(secs // 86400), int((secs % 86400) // 3600)
                item.feasible = False
                item.feasibility_msg = f'-{d}d {h}h' if d else f'-{h}h'


class MrpProductionRequest(models.TransientModel):
    _name = 'mrp.production.request'
    _description = 'Solicitud de programación de fabricación'

    start_from = fields.Datetime(
        string='Disponible desde', default=fields.Datetime.now,
        help='Fecha mínima de inicio para todos los artículos. Por defecto: ahora.',
    )
    item_ids = fields.One2many(
        'mrp.production.request.item', 'request_id', string='Artículos',
    )
    line_ids = fields.One2many(
        'mrp.production.request.line', 'request_id', string='Plan calculado',
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('calculated', 'Calculado'),
    ], default='draft')

    all_feasible        = fields.Boolean(compute='_compute_summary', store=False)
    feasibility_summary = fields.Char(compute='_compute_summary', store=False)

    @api.depends('item_ids.feasible', 'item_ids.projected_end')
    def _compute_summary(self):
        for rec in self:
            done = rec.item_ids.filtered('projected_end')
            if not done:
                rec.all_feasible = False
                rec.feasibility_summary = _('Sin datos calculados')
                continue
            ok = sum(1 for i in done if i.feasible)
            total = len(done)
            rec.all_feasible = ok == total
            if ok == total:
                rec.feasibility_summary = _(
                    'Todos los artículos cumplen el plazo (%d/%d)'
                ) % (ok, total)
            else:
                rec.feasibility_summary = _(
                    '%d de %d artículos no cumplen el plazo'
                ) % (total - ok, total)

    # ── Acciones ─────────────────────────────────────────────────────────────

    def action_calculate(self):
        self.ensure_one()
        if not self.item_ids:
            raise UserError(_('Agregue al menos un artículo.'))
        missing_bom = []

        self.line_ids.unlink()
        self.item_ids.write({'projected_end': False})

        plan_model = self.env['mrp.reschedule.plan']
        start = self.start_from or fields.Datetime.now()
        if hasattr(start, 'tzinfo') and start.tzinfo:
            start = start.astimezone(pytz.utc).replace(tzinfo=None)

        # Construir árbol de LdM para cada artículo (en orden de secuencia)
        item_trees = []
        for item in self.item_ids.sorted(lambda i: (i.sequence, i.id)):
            root = self._build_bom_tree(item.product_id, item.product_qty, level=0)
            if not root:
                missing_bom.append(item.product_id.display_name)
            else:
                item_trees.append((item, root))

        if missing_bom:
            raise UserError(_(
                'Sin lista de materiales para: %s'
            ) % ', '.join(missing_bom))

        # Anclas de WC: carga existente de MOs confirmadas/en progreso
        all_roots = [r for _, r in item_trees]
        wc_anchors = self._get_wc_anchors_multi(start, all_roots)

        # Programar todos los artículos compartiendo los mismos anclas de WC
        lines_vals = []
        seq = [10]
        for item, root in item_trees:
            self._schedule_tree(root, start, wc_anchors, plan_model)
            self._collect_lines(root, lines_vals, seq, item_id=item.id)
            item.write({'projected_end': root.get('scheduled_end')})

        for vals in lines_vals:
            vals['request_id'] = self.id
        if lines_vals:
            self.env['mrp.production.request.line'].create(lines_vals)

        self.state = 'calculated'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'calculated':
            raise UserError(_('Calcule primero el plan.'))
        if not self.line_ids:
            raise UserError(_('No hay líneas calculadas.'))

        has_parent_field = 'x_parent_mo_id' in self.env['mrp.production']._fields
        all_created_ids = []

        for item in self.item_ids.sorted(lambda i: (i.sequence, i.id)):
            item_lines = self.line_ids.filtered(
                lambda l: l.item_id.id == item.id
            ).sorted(lambda l: (l.level, l.sequence))

            if not item_lines:
                continue

            level_mo = {}
            for line in item_lines:
                mo_vals = {
                    'product_id':  line.product_id.id,
                    'product_qty': line.product_qty,
                    'date_start':    line.new_date_start,
                    'date_finished': line.new_date_finish,
                }
                if line.bom_id:
                    mo_vals['bom_id'] = line.bom_id.id
                parent_mo = level_mo.get(line.level - 1) if line.level > 0 else None
                if parent_mo and has_parent_field:
                    mo_vals['x_parent_mo_id'] = parent_mo.id
                elif parent_mo:
                    mo_vals['origin'] = parent_mo.name

                mo = self.env['mrp.production'].create(mo_vals)
                level_mo[line.level] = mo
                all_created_ids.append(mo.id)

        if not all_created_ids:
            raise UserError(_('No se pudo crear ninguna orden de fabricación.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de fabricación creadas'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_created_ids)],
            'target': 'current',
        }

    # ── Helpers — BOM explosion ───────────────────────────────────────────────

    def _find_bom(self, product):
        try:
            result = self.env['mrp.bom']._bom_find(product, company_id=self.env.company.id)
            bom = result.get(product) if isinstance(result, dict) else result
            if bom:
                return bom
        except Exception:
            pass
        return self.env['mrp.bom'].search([
            ('type', 'not in', ['phantom', 'subcontract']),
            ('company_id', 'in', [False, self.env.company.id]),
            '|',
            ('product_id', '=', product.id),
            '&', ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ], limit=1, order='sequence, id')

    def _get_op_duration_hours(self, op, qty):
        dur_min = (
            getattr(op, 'time_cycle_manual', None)
            or getattr(op, 'time_cycle', None)
            or 60.0
        )
        return dur_min * qty / 60.0

    def _build_bom_tree(self, product, qty, level, visited=None):
        if visited is None:
            visited = set()
        if product.id in visited:
            return None
        visited = visited | {product.id}

        bom = self._find_bom(product)
        if not bom or bom.type == 'phantom':
            return None

        operations = []
        if bom.operation_ids:
            for op in bom.operation_ids.sorted('sequence'):
                wc = op.workcenter_id
                dur_h = self._get_op_duration_hours(op, qty)
                operations.append((wc, dur_h))
        else:
            operations = [(None, 8.0)]

        node = {
            'product':    product,
            'qty':        qty,
            'bom':        bom,
            'level':      level,
            'operations': operations,
            'children':   [],
            'scheduled_start': None,
            'scheduled_end':   None,
        }

        for bom_line in bom.bom_line_ids:
            child_node = self._build_bom_tree(
                bom_line.product_id,
                bom_line.product_qty * qty,
                level + 1,
                visited,
            )
            if child_node:
                node['children'].append(child_node)

        return node

    def _get_wc_anchors_multi(self, start, roots):
        wc_ids = set()

        def _collect(node):
            for wc, _ in node['operations']:
                if wc:
                    wc_ids.add(wc.id)
            for child in node['children']:
                _collect(child)

        for root in roots:
            _collect(root)

        if not wc_ids:
            return {}

        anchors = {}
        for mo in self.env['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress')),
            ('workorder_ids.workcenter_id', 'in', list(wc_ids)),
        ]):
            est_end = mo.date_finished or (
                mo.date_start + timedelta(hours=8) if mo.date_start else None
            )
            if est_end:
                for wo in mo.workorder_ids:
                    wc_id = wo.workcenter_id.id
                    if wc_id in wc_ids:
                        anchors[wc_id] = max(anchors.get(wc_id, est_end), est_end)
        return anchors

    def _schedule_tree(self, node, start, wc_anchors, plan_model):
        children_end = start
        for child in node['children']:
            self._schedule_tree(child, start, wc_anchors, plan_model)
            if child['scheduled_end']:
                children_end = max(children_end, child['scheduled_end'])

        after_dt   = max(start, children_end)
        node_start = None
        current    = after_dt

        for wc, dur_h in node['operations']:
            wc_id    = wc.id if wc else 0
            calendar = (
                wc.resource_calendar_id if wc and wc.resource_calendar_id
                else self.env.company.resource_calendar_id
            )
            earliest    = max(current, wc_anchors.get(wc_id, after_dt))
            wo_start, wo_end = plan_model._schedule_duration(calendar, earliest, dur_h)
            wc_anchors[wc_id] = wo_end
            if node_start is None:
                node_start = wo_start
            current = wo_end

        node['scheduled_start'] = node_start
        node['scheduled_end']   = current

    def _collect_lines(self, node, lines_vals, seq, item_id=None):
        indent   = INDENT_MAP.get(node['level'], '         └─ ')
        product  = node['product']
        ops      = node['operations']
        wcs      = [wc for wc, _ in ops if wc]
        wc_label = ' › '.join(wc.name for wc in wcs) if wcs else ''
        dur_h    = sum(d for _, d in ops)

        lines_vals.append({
            'sequence':          seq[0],
            'level':             node['level'],
            'item_id':           item_id,
            'product_id':        product.id,
            'bom_id':            node['bom'].id,
            'product_qty':       node['qty'],
            'duration_hours':    round(dur_h, 2),
            'new_date_start':    node['scheduled_start'],
            'new_date_finish':   node['scheduled_end'],
            'workcenter_label':  wc_label,
            'description_label': f'{indent}{product.display_name}',
            'type_label':        'OF' if node['level'] == 0 else 'OF hija',
        })
        seq[0] += 10

        for child in node['children']:
            self._collect_lines(child, lines_vals, seq, item_id=item_id)


class MrpProductionRequestLine(models.TransientModel):
    _name = 'mrp.production.request.line'
    _description = 'Línea de solicitud de programación'
    _order = 'sequence'

    request_id = fields.Many2one('mrp.production.request', required=True, ondelete='cascade')
    item_id    = fields.Many2one('mrp.production.request.item', string='Artículo',
                                 ondelete='cascade')
    sequence   = fields.Integer(default=10)
    level      = fields.Integer(default=0)

    product_id  = fields.Many2one('product.product', string='Producto', required=True)
    bom_id      = fields.Many2one('mrp.bom', string='LdM')
    product_qty = fields.Float(string='Cantidad', digits=(16, 2))
    duration_hours = fields.Float(string='Duración (hs)', digits=(10, 2))

    new_date_start  = fields.Datetime(string='Inicio propuesto')
    new_date_finish = fields.Datetime(string='Fin propuesto')

    workcenter_label  = fields.Char(string='Centros de trabajo')
    description_label = fields.Char(string='Producto')
    type_label        = fields.Char(string='Tipo')
