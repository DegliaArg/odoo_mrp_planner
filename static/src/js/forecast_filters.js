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

    const kpis0 = widget.state.data.kpis;
    const no_fc_demand     = kpis0.so_demand_no_fc        || 0;
    const no_fc_delivered  = kpis0.delivered_no_fc        || 0;
    const no_fc_demand_del = kpis0.demand_delivered_no_fc || 0;
    const total_demand_all = total_so_demand + no_fc_demand;

    const overall_service_rate        = total_demand_all > 0
        ? Math.round((total_delivered        + no_fc_delivered)  / total_demand_all * 100) : null;
    const overall_demand_service_rate = total_demand_all > 0
        ? Math.round((total_demand_delivered + no_fc_demand_del) / total_demand_all * 100) : null;
    const demand_gap_pct = total_forecast > 0
        ? Math.round((total_so_demand - total_forecast) / total_forecast * 100) : null;
    const mos_gap_pct = total_forecast > 0
        ? Math.round((total_mos - total_forecast) / total_forecast * 100) : null;

    const accRows = rows.filter(r => r.total_forecast_acc !== null && r.total_forecast_acc !== undefined);
    const overall_forecast_acc = accRows.length > 0
        ? Math.round(accRows.reduce((s, r) => s + r.total_forecast_acc, 0) / accRows.length)
        : null;

    const del_by_order_month = {};
    for (const r of rows) {
        for (const [ym, qty] of Object.entries(r.del_by_order_month || {})) {
            del_by_order_month[ym] = (del_by_order_month[ym] || 0) + qty;
        }
    }

    return {
        ...widget.state.data.kpis,
        total_forecast,
        total_mos,
        total_delivered,
        total_so_demand,
        total_demand_delivered,
        overall_forecast_acc,
        overall_service_rate,
        overall_demand_service_rate,
        demand_gap_pct,
        mos_gap_pct,
        del_by_order_month,
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
