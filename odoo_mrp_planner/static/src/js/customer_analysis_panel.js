/** @odoo-module **/

/**
 * Panel lateral de detalle y filas expandibles (pedidos inline) del análisis
 * de clientes. Ambas features comparten el RPC get_customer_detail y se
 * excluyen mutuamente por cliente (abrir una cierra la otra).
 *
 * Mismo patrón que customer_analysis_charts.js: funciones que reciben el
 * widget; el componente conserva delegados de una línea para el template.
 */

/**
 * Abre/cierra el panel lateral de análisis de un cliente. Al abrir carga el
 * detalle vía RPC; con "Unificar por CUIT" la fila puede agrupar varios
 * partners y el panel agrega los pedidos de todos ellos.
 * @param {Component} widget
 * @param {number} partnerId - Partner de la fila (representativo si está unificado).
 */
export async function toggleDetail(widget, partnerId) {
    const state = widget.state;
    if (state.panelPartnerId === partnerId) {
        state.panelPartnerId = null;
        state.panelData      = null;
        widget._lastPanelKey = null;
        widget._destroyPanelCharts();
        return;
    }
    widget._destroyPanelCharts();
    widget._lastPanelKey = null;
    state.panelPartnerId = partnerId;
    state.panelData      = null;
    state.panelLoading   = true;
    // Si se abre el panel, cerrar la fila expandida del mismo cliente
    if (state.expandedRows[partnerId]) {
        state.expandedRows[partnerId] = false;
    }
    try {
        const row = state.allRows.find((r) => r.partner_id === partnerId);
        const partnerIds = (row && row.partner_ids) || [partnerId];
        const data = await widget.orm.call(
            "mrp.planner.dashboard",
            "get_customer_detail",
            [partnerId, state.dateFrom, state.dateTo, null, partnerIds, state.localAmountMethod]
        );
        state.panelData = data;
    } catch (e) {
        console.error("[CustomerAnalysis] toggleDetail", e);
    } finally {
        state.panelLoading = false;
    }
}

/**
 * Expande/colapsa la fila de pedidos inline de un cliente; en la primera
 * apertura carga los pedidos con el mismo RPC del panel.
 * @param {Component} widget
 * @param {number} partnerId
 */
export async function toggleRow(widget, partnerId) {
    const state = widget.state;
    const isOpen = !!state.expandedRows[partnerId];
    state.expandedRows[partnerId] = !isOpen;
    // Si se abre la fila de pedidos, cerrar el panel de análisis del mismo cliente
    if (!isOpen && state.panelPartnerId === partnerId) {
        state.panelPartnerId = null;
        state.panelData      = null;
        widget._destroyPanelCharts();
    }
    if (!isOpen && !state.rowOrders[partnerId]) {
        state.rowOrdersLoading[partnerId] = true;
        try {
            const row = state.allRows.find((r) => r.partner_id === partnerId);
            const partnerIds = (row && row.partner_ids) || [partnerId];
            const data = await widget.orm.call(
                "mrp.planner.dashboard",
                "get_customer_detail",
                [partnerId, state.dateFrom, state.dateTo, null, partnerIds, state.localAmountMethod]
            );
            state.rowOrders[partnerId] = data.orders || [];
        } catch (e) {
            console.error("[CustomerAnalysis] toggleRow", e);
            state.rowOrders[partnerId] = [];
        } finally {
            state.rowOrdersLoading[partnerId] = false;
        }
    }
}

/** Pedidos de la fila expandida, ordenados por la columna activa. */
export function getSortedOrders(widget, partnerId) {
    const state  = widget.state;
    const orders = state.rowOrders[partnerId] || [];
    const key    = state.rowOrderSort;
    const dir    = state.rowOrderDir === "desc" ? -1 : 1;
    return [...orders].sort((a, b) => {
        const va = a[key] ?? -Infinity;
        const vb = b[key] ?? -Infinity;
        if (typeof va === "string") return dir * va.localeCompare(vb, "es", { sensitivity: "base" });
        return dir * (va - vb);
    });
}

/** Cambia la columna de orden de la tabla de pedidos inline (o invierte). */
export function sortRowOrders(widget, key) {
    const state = widget.state;
    if (state.rowOrderSort === key) {
        state.rowOrderDir = state.rowOrderDir === "desc" ? "asc" : "desc";
    } else {
        state.rowOrderSort = key;
        state.rowOrderDir  = "desc";
    }
}

/** Top de artículos del panel, con qty_pending calculado, ordenado y recortado a panelTopN. */
export function panelTopProducts(widget) {
    const state = widget.state;
    const all = (state.panelData?.top_products || []).map((p) => ({
        ...p,
        qty_pending: Math.max(0, (p.qty_ordered || 0) - (p.qty_delivered || 0)),
    }));
    const key = state.panelProdSort;
    const dir = state.panelProdDir === "desc" ? -1 : 1;
    const sorted = [...all].sort((a, b) => {
        const va = a[key] ?? (typeof a[key] === "string" ? "" : -Infinity);
        const vb = b[key] ?? (typeof b[key] === "string" ? "" : -Infinity);
        if (typeof va === "string") return dir * va.localeCompare(vb, "es", { sensitivity: "base" });
        return dir * (va - vb);
    });
    return sorted.slice(0, state.panelTopN);
}

/** Métrica del panel (monto/cantidad): resetea el sort del top de artículos. */
export function setPanelMetric(widget, m) {
    const state = widget.state;
    if (state.panelMetric !== m) {
        state.panelMetric   = m;
        state.panelProdSort = m === "qty" ? "qty_ordered" : "amount";
        state.panelProdDir  = "desc";
        widget._panelDonutsKey = "";
        widget._panelChartKey  = "";
    }
}

/** Modo del gráfico principal del panel (barras/línea). */
export function setPanelChartMode(widget, mode) {
    const state = widget.state;
    if (state.panelChartMode !== mode) {
        state.panelChartMode  = mode;
        widget._panelChartKey = "";
    }
}

/** Cantidad de artículos del top del panel. */
export function setPanelTopN(widget, n) {
    widget.state.panelTopN = n;
}

/** Cambia la columna de orden del top de artículos del panel (o invierte). */
export function sortPanelProds(widget, key) {
    const state = widget.state;
    if (state.panelProdSort === key) {
        state.panelProdDir = state.panelProdDir === "desc" ? "asc" : "desc";
    } else {
        state.panelProdSort = key;
        state.panelProdDir  = "desc";
    }
}
