/** @odoo-module **/

/**
 * Filtros, ordenamiento y handlers del widget de forecast.
 * Cada función recibe el widget como primer parámetro (widget pattern).
 * Las funciones internas se llaman entre sí directamente (sin pasar por widget.getter)
 * para evitar indirección innecesaria.
 */

export function baseFilteredRows(widget) {
    if (!widget.state.data || !widget.state.data.rows) return [];
    let rows = widget.state.data.rows;
    const q = widget.state.productSearch.toLowerCase();
    if (q) rows = rows.filter(r => r.product.toLowerCase().includes(q));
    const f = widget.state.activeFilter;
    if (f === 'with_mos') rows = rows.filter(r => r.total_mos > 0);
    if (f === 'no_mos')   rows = rows.filter(r => r.total_mos === 0);
    if (f === 'gap')      rows = rows.filter(r => r.total_forecast > 0 && r.total_mos < r.total_forecast);
    return rows;
}

export function filteredRowsAll(widget) {
    let rows = baseFilteredRows(widget);
    const gb = widget.state.groupBy;
    if (gb && widget.state.selectedGroup !== null) {
        rows = rows.filter(r => (r[gb] || '') === widget.state.selectedGroup);
    }
    return rows;
}

export function filteredKpis(widget) {
    if (!widget.state.data) return {};
    const rows = filteredRowsAll(widget);
    const total_forecast         = rows.reduce((s, r) => s + (r.total_forecast         || 0), 0);
    const total_mos              = rows.reduce((s, r) => s + (r.total_mos              || 0), 0);
    const total_delivered        = rows.reduce((s, r) => s + (r.total_delivered        || 0), 0);
    const total_so_demand        = rows.reduce((s, r) => s + (r.total_so_demand        || 0), 0);
    const total_demand_delivered = rows.reduce((s, r) => s + (r.total_demand_delivered || 0), 0);

    // Las filas ahora cubren el negocio completo (con y sin forecast): los KPIs
    // son la suma de la tabla visible y los chips "sin FC" desglosan cuánto del
    // total viene de artículos sin línea de forecast — respondiendo a los filtros.
    const fcSet = new Set(widget.state.data.fc_product_ids || []);
    let so_demand_no_fc = 0, mos_no_fc = 0, delivered_no_fc = 0, demand_delivered_no_fc = 0;
    for (const r of rows) {
        if (fcSet.has(r.product_id)) continue;
        so_demand_no_fc        += r.total_so_demand        || 0;
        mos_no_fc              += r.total_mos              || 0;
        delivered_no_fc        += r.total_delivered        || 0;
        demand_delivered_no_fc += r.total_demand_delivered || 0;
    }

    // Tasas y brechas con 1 decimal (mismo criterio que el análisis de clientes)
    const r1 = x => Math.round(x * 10) / 10;
    const overall_service_rate        = total_so_demand > 0
        ? r1(total_delivered        / total_so_demand * 100) : null;
    const overall_demand_service_rate = total_so_demand > 0
        ? r1(total_demand_delivered / total_so_demand * 100) : null;
    const demand_gap_pct = total_forecast > 0
        ? r1((total_so_demand - total_forecast) / total_forecast * 100) : null;
    const mos_gap_pct = total_forecast > 0
        ? r1((total_mos - total_forecast) / total_forecast * 100) : null;

    // Precisión global AGREGADA sobre las filas filtradas, con el MISMO método que el
    // server (ratio de sumas, no promedio de porcentajes por artículo). Así el card, la
    // columna y la fila Total son consistentes y respetan el filtro. El titular es la
    // fórmula elegida en Ajustes (acc_formula).
    const d0 = widget.state.data;
    const acc_formula = (d0 && d0.acc_formula) || 'simple';
    const precision_source = d0 && d0.precision_source;
    let mapeSum = 0, mapeCount = 0, wapeErr = 0, wmapeErr = 0, sumFc = 0, sumFcPos = 0, sumActual = 0;
    for (const r of rows) {
        const actual = precision_source === 'delivery' ? (r.total_delivered || 0) : (r.total_so_demand || 0);
        mapeSum   += r._mape_acc_sum  || 0;
        mapeCount += r._mape_acc_count || 0;
        wapeErr   += r._wape_abs_err  || 0;
        wmapeErr  += r._wmape_abs_err || 0;
        sumFc     += r.total_forecast || 0;
        if ((r.total_forecast || 0) > 0) sumFcPos += r.total_forecast;
        sumActual += actual;
    }
    const acc_all = {
        simple: sumFc > 0      ? r1(sumActual / sumFc * 100) : null,
        mape:   mapeCount > 0  ? r1(mapeSum / mapeCount) : null,
        wape:   sumActual > 0  ? r1(Math.max(0, 100 - wapeErr / sumActual * 100)) : null,
        wmape:  sumFcPos > 0   ? r1(Math.max(0, 100 - wmapeErr / sumFcPos * 100)) : null,
        bias:   sumFc > 0      ? r1((sumActual - sumFc) / sumFc * 100) : null,
    };
    const overall_forecast_acc = acc_all[acc_formula];
    // Términos crudos para los tooltips con números enchufados.
    const acc_terms = { wapeErr, wmapeErr, mapeSum, mapeCount, sumActual, sumFc, sumFcPos };

    const del_by_order_month = {};
    for (const r of rows) {
        for (const [ym, qty] of Object.entries(r.del_by_order_month || {})) {
            del_by_order_month[ym] = (del_by_order_month[ym] || 0) + qty;
        }
    }

    // Despachados (módulo de despacho): mismos agregados que las entregas
    // validadas pero solo sobre remitos marcados como despachados.
    const dispatch_by_order_month = {};
    let total_delivered_dispatched = 0, dispatched_no_fc = 0;
    for (const r of rows) {
        total_delivered_dispatched += r.total_delivered_dispatched || 0;
        if (!fcSet.has(r.product_id)) dispatched_no_fc += r.total_delivered_dispatched || 0;
        for (const [ym, qty] of Object.entries(r.dispatch_by_order_month || {})) {
            dispatch_by_order_month[ym] = (dispatch_by_order_month[ym] || 0) + qty;
        }
    }
    const overall_dispatch_rate = total_so_demand > 0
        ? r1(total_delivered_dispatched / total_so_demand * 100) : null;

    return {
        ...widget.state.data.kpis,
        total_forecast,
        total_mos,
        total_delivered,
        total_so_demand,
        total_demand_delivered,
        overall_forecast_acc,
        acc_all,
        acc_terms,
        overall_service_rate,
        overall_demand_service_rate,
        demand_gap_pct,
        mos_gap_pct,
        del_by_order_month,
        dispatch_by_order_month,
        total_delivered_dispatched: Math.round(total_delivered_dispatched * 10) / 10,
        dispatched_no_fc:           Math.round(dispatched_no_fc * 10) / 10,
        overall_dispatch_rate,
        so_demand_no_fc:        Math.round(so_demand_no_fc * 10) / 10,
        mos_no_fc:              Math.round(mos_no_fc * 10) / 10,
        delivered_no_fc:        Math.round(delivered_no_fc * 10) / 10,
        demand_delivered_no_fc: Math.round(demand_delivered_no_fc * 10) / 10,
    };
}

export function sortedRows(widget) {
    const rows = [...filteredRowsAll(widget)];
    const col  = widget.state.sortCol;
    const dir  = widget.state.sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
        let va = a[col], vb = b[col];
        if (typeof va === 'string') {
            if (!va && vb) return dir;
            if (va && !vb) return -dir;
            return dir * va.localeCompare(vb, 'es', { sensitivity: 'base' });
        }
        va = va ?? -Infinity;
        vb = vb ?? -Infinity;
        return dir * (va - vb);
    });
    return rows;
}

export function allGroupsForTabs(widget) {
    const gb = widget.state.groupBy;
    if (!gb) return null;
    const counts = new Map();
    for (const row of baseFilteredRows(widget)) {
        const key = row[gb] || '';
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    let entries = [...counts.entries()];
    if (gb === 'sale_category') {
        const CAT_ORDER = ['A', 'B', 'C', 'D', 'E', ''];
        entries.sort((a, b) => {
            const ia = CAT_ORDER.indexOf(a[0]);
            const ib = CAT_ORDER.indexOf(b[0]);
            return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
        });
    } else {
        entries.sort((a, b) => a[0].localeCompare(b[0], 'es', { sensitivity: 'base' }));
    }
    return entries.map(([key, count]) => ({ key, label: key || 'Sin categoría', count }));
}

export function onPeriodFromChange(widget, ev) {
    const val = ev.target.value;
    if (!val) return;
    widget.state.periodFrom = val;
    if (widget.state.periodFrom > widget.state.periodTo)
        widget.state.periodTo = widget.state.periodFrom;
    widget._loadDebounced();
}

export function onPeriodToChange(widget, ev) {
    const val = ev.target.value;
    if (!val) return;
    widget.state.periodTo = val;
    if (widget.state.periodTo < widget.state.periodFrom)
        widget.state.periodFrom = widget.state.periodTo;
    widget._loadDebounced();
}

export function onProductSearchInput(widget, ev) {
    widget.state.productSearch = ev.target.value;
    widget.state.page = 1;
}

export function setSearch(widget, text) {
    widget.state.productSearch = text;
    widget.state.page = 1;
}

export function toggleWhDropdown(widget, ev) {
    ev.stopPropagation();
    const opening = !widget.state.whDropdownOpen;
    widget.state.whDropdownOpen     = opening;
    widget.state.colsDropdownOpen   = false;
    widget.state.filterDropdownOpen = false;
    widget.state.groupDropdownOpen  = false;
    if (opening) widget.state.whSearch = "";
}

export function toggleColsDropdown(widget, ev) {
    ev.stopPropagation();
    widget.state.colsDropdownOpen   = !widget.state.colsDropdownOpen;
    widget.state.whDropdownOpen     = false;
    widget.state.whSearch           = "";
    widget.state.filterDropdownOpen = false;
    widget.state.groupDropdownOpen  = false;
}

export function toggleFilterDropdown(widget, ev) {
    ev.stopPropagation();
    widget.state.filterDropdownOpen = !widget.state.filterDropdownOpen;
    widget.state.colsDropdownOpen   = false;
    widget.state.whDropdownOpen     = false;
    widget.state.whSearch           = "";
    widget.state.groupDropdownOpen  = false;
}

export function toggleGroupDropdown(widget, ev) {
    ev.stopPropagation();
    widget.state.groupDropdownOpen  = !widget.state.groupDropdownOpen;
    widget.state.colsDropdownOpen   = false;
    widget.state.whDropdownOpen     = false;
    widget.state.whSearch           = "";
    widget.state.filterDropdownOpen = false;
}

export function toggleCol(widget, colKey) {
    widget.state.visibleCols[colKey] = !widget.state.visibleCols[colKey];
}

export function setFilter(widget, key) {
    widget.state.activeFilter = key;
    widget.state.page = 1;
}

export function setGroupBy(widget, key) {
    widget.state.groupBy = key;
    widget.state.page = 1;
    if (key) {
        const groups = allGroupsForTabs(widget);
        widget.state.selectedGroup = (groups && groups.length) ? groups[0].key : null;
    } else {
        widget.state.selectedGroup = null;
    }
}

export function setGroup(widget, key) {
    widget.state.selectedGroup = key;
    widget.state.page = 1;
}

export function toggleWarehouse(widget, ev) {
    const id = parseInt(ev.target.dataset.whId);
    const ids = widget.state.warehouseIds;
    widget.state.warehouseIds = ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id];
    widget._load();
}

export function clearWhFilter(widget) {
    widget.state.warehouseIds = [];
    widget._load();
}

export function onColHeaderClick(widget, col) {
    const sk = widget.fcSortKeys[col.key];
    if (sk) setSort(widget, sk);
}

export function setSort(widget, col) {
    if (widget.state.sortCol === col) {
        widget.state.sortDir = widget.state.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        widget.state.sortCol = col;
        widget.state.sortDir = 'asc';
    }
    widget.state.page = 1;
}
