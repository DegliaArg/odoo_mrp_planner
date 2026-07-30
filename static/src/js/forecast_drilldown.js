/** @odoo-module **/

/**
 * Drill-down actions para el widget de forecast.
 * Cada función recibe el widget como primer parámetro y abre la vista Odoo correspondiente.
 */

function periodDateRange(widget) {
    const toUtcStr = (localIso) => {
        const d = new Date(localIso);
        const pad = n => String(n).padStart(2, '0');
        return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
               `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    };
    return {
        dateFrom: toUtcStr(`${widget.state.periodFrom}T00:00:00`),
        dateTo:   toUtcStr(`${widget.state.periodTo}T23:59:59`),
    };
}

// Productos con línea de forecast (para los drills "sin forecast", que
// necesitan el 'not in'). Viene del payload: las filas de la tabla ahora
// incluyen también artículos sin forecast, así que no sirven para esto.
function forecastProductIds(widget) {
    return (widget.state.data && widget.state.data.fc_product_ids) || [];
}

// Filtro de servicios para los drills de demanda (líneas de pedido), según el
// toggle de Ajustes que viaja en el payload del forecast.
function svcDom(widget) {
    return (widget.state.data && widget.state.data.exclude_services)
        ? [['product_id.type', '!=', 'service']] : [];
}

// Productos actualmente VISIBLES en la tabla (tras búsqueda, filtro y agrupamiento).
// Los drills de los KPIs usan este conjunto para reflejar lo que el usuario ve.
function visibleProductIds(widget) {
    return (widget.filteredRowsAll || []).map(r => r.product_id);
}

export function openDrillForecast(widget) {
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Demanda forecast',
        res_model: 'mrp.forecast.line',
        view_mode: 'list,form',
        views:     [[false, 'list'], [false, 'form']],
        domain:    [
            ['period', '>=', widget.state.periodFrom.substring(0, 7) + '-01'],
            ['period', '<=', widget.state.periodTo.substring(0, 7)   + '-01'],
            ['product_id', 'in', visibleProductIds(widget)],
        ],
        target: 'current',
    });
}

export function openDrillMos(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids     = visibleProductIds(widget);
    const moStates = (widget.state.data && widget.state.data.mo_states) || ['confirmed', 'progress', 'to_close'];
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Producción planificada',
        res_model: 'mrp.production',
        view_mode: 'list,form',
        views:     [[false, 'list'], [false, 'form']],
        domain:    [
            ['product_id', 'in', pids],
            ['state', 'in', moStates],
            ['date_finished', '>=', dateFrom],
            ['date_finished', '<=', dateTo],
            ['location_src_id.is_subcontracting_location', '!=', true],
        ],
        target: 'current',
    });
}

export function openDrillSoDemand(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = visibleProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Demanda real (órdenes de venta)',
        res_model: 'sale.order.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['order_id.state', 'in', ['sale', 'done']],
            ['order_id.date_order', '>=', dateFrom],
            ['order_id.date_order', '<=', dateTo],
            ['product_id', 'in', pids],
            ...svcDom(widget),
        ],
        target: 'current',
    });
}

export function openDrillDelivered(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = visibleProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Entregas Físicas (movimientos de salida)',
        res_model: 'stock.move.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['state', '=', 'done'],
            ['picking_id.picking_type_id.code', '=', 'outgoing'],
            ['date', '>=', dateFrom],
            ['date', '<=', dateTo],
            ['product_id', 'in', pids],
        ],
        target: 'current',
    });
}

/**
 * Movimientos de salida del período que componen una fila del resumen
 * "Entregas físicas por mes de pedido".
 * @param {Object} widget - Widget de forecast.
 * @param {string} ymKey - 'YYYY-MM' (mes de confirmación del pedido de origen)
 *   o '' para las salidas sin pedido de venta vinculado.
 * @param {string} label - Etiqueta de la fila, usada como título de la ventana.
 */
export function openDrillDeliveredByOrderMonth(widget, ymKey, label) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = visibleProductIds(widget);
    const domain = [
        ['state', '=', 'done'],
        ['picking_id.picking_type_id.code', '=', 'outgoing'],
        ['date', '>=', dateFrom],
        ['date', '<=', dateTo],
        ['product_id', 'in', pids],
    ];
    if (ymKey) {
        // Mismo corte de mes que el backend: strftime('%Y-%m') sobre el datetime
        // UTC de date_order, por eso los límites van en UTC sin conversión local.
        const [y, m] = ymKey.split('-').map(Number);
        const pad = n => String(n).padStart(2, '0');
        const next = m === 12 ? `${y + 1}-01` : `${y}-${pad(m + 1)}`;
        domain.push(
            ['picking_id.sale_id.date_order', '>=', `${ymKey}-01 00:00:00`],
            ['picking_id.sale_id.date_order', '<', `${next}-01 00:00:00`],
        );
    } else {
        domain.push(['picking_id.sale_id', '=', false]);
    }
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      `Entregas físicas — ${label}`,
        res_model: 'stock.move.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain,
        target: 'current',
    });
}

export function openDrillDemandDelivered(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = visibleProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Cumplimiento de demanda (entregas de pedidos del período)',
        res_model: 'stock.move.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['state', '=', 'done'],
            ['picking_id.picking_type_id.code', '=', 'outgoing'],
            ['picking_id.sale_id.date_order', '>=', dateFrom],
            ['picking_id.sale_id.date_order', '<=', dateTo],
            ['product_id', 'in', pids],
        ],
        target: 'current',
    });
}

export function openDrillSoDemandNoFc(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = forecastProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Demanda real – productos sin forecast',
        res_model: 'sale.order.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['order_id.state', 'in', ['sale', 'done']],
            ['order_id.date_order', '>=', dateFrom],
            ['order_id.date_order', '<=', dateTo],
            ['product_id.sale_ok', '=', true],
            ['product_id', 'not in', pids],
            ...svcDom(widget),
        ],
        target: 'current',
    });
}

export function openDrillMosNoFc(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids     = forecastProductIds(widget);
    const moStates = (widget.state.data && widget.state.data.mo_states) || ['confirmed', 'progress', 'to_close'];
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Producción planificada – productos sin forecast',
        res_model: 'mrp.production',
        view_mode: 'list,form',
        views:     [[false, 'list'], [false, 'form']],
        domain:    [
            ['state', 'in', moStates],
            ['date_finished', '>=', dateFrom],
            ['date_finished', '<=', dateTo],
            ['product_id.sale_ok', '=', true],
            ['location_src_id.is_subcontracting_location', '!=', true],
            ['product_id', 'not in', pids],
        ],
        target: 'current',
    });
}

export function openDrillDemandDeliveredNoFc(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = forecastProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Cumplimiento de demanda – productos sin forecast',
        res_model: 'stock.move.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['state', '=', 'done'],
            ['picking_id.picking_type_id.code', '=', 'outgoing'],
            ['picking_id.sale_id.date_order', '>=', dateFrom],
            ['picking_id.sale_id.date_order', '<=', dateTo],
            ['product_id.sale_ok', '=', true],
            ['product_id', 'not in', pids],
        ],
        target: 'current',
    });
}

export function openDrillDeliveredNoFc(widget) {
    const { dateFrom, dateTo } = periodDateRange(widget);
    const pids = forecastProductIds(widget);
    widget.action.doAction({
        type:      'ir.actions.act_window',
        name:      'Entregas físicas – productos sin forecast',
        res_model: 'stock.move.line',
        view_mode: 'list',
        views:     [[false, 'list']],
        domain:    [
            ['state', '=', 'done'],
            ['picking_id.picking_type_id.code', '=', 'outgoing'],
            ['date', '>=', dateFrom],
            ['date', '<=', dateTo],
            ['product_id.sale_ok', '=', true],
            ['product_id', 'not in', pids],
        ],
        target: 'current',
    });
}
