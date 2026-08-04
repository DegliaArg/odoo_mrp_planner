/**
 * movements_dashboard_widget.js (odoo_mrp_planner_dispatch)
 *
 * Widget del panel "Movimientos pendientes": recepciones y transferencias
 * pendientes — el complemento del Panel de Inventario (que cubre la cadena
 * de entrega a clientes). Todo se deriva de una sola RPC de filas:
 *   - Gráfico de composición por depósito (preparado vs. sin preparar),
 *     sobre el conjunto que devuelve el servidor.
 *   - Cards KPI dinámicas que describen exactamente lo que la tabla muestra
 *     (búsqueda, filtros, depósitos, tipos y pestaña activa).
 *   - Tabla con agrupamiento por pestañas, paginación y export CSV.
 *
 * Misma estética y componentes compartidos que los demás paneles:
 * PlannerSearchBar, useColManager, formateadores es-AR y Chart.js.
 */

/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { fmt, fmtPct, svcClass, sortIcon } from "@odoo_mrp_planner/js/forecast_formatters";
import { PlannerSearchBar } from "@odoo_mrp_planner/js/planner_search_bar";
import { useColManager } from "@odoo_mrp_planner/js/column_manager";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfMonth() { const d = new Date(); return toDateStr(new Date(d.getFullYear(), d.getMonth(), 1)); }
function lastOfMonth()  { const d = new Date(); return toDateStr(new Date(d.getFullYear(), d.getMonth() + 1, 0)); }

const COLS = [
    { key: "name",          label: "Remito",       width: 110, fixed: true, align: "start" },
    { key: "type_name",     label: "Tipo",         width: 150, align: "start" },
    { key: "origin",        label: "Origen",       width: 110, align: "start" },
    { key: "partner",       label: "Contacto",     width: 130, align: "start" },
    { key: "route",         label: "Desde → Hasta", width: 190, align: "start" },
    { key: "warehouse",     label: "Depósito",     width: 120, align: "start" },
    { key: "scheduled",     label: "Fecha prog.",  width: 120, align: "start" },
    { key: "product_names", label: "Artículos",    width: 230, align: "start" },
    { key: "qty_pending",   label: "Pendiente",    width:  90, align: "end" },
    { key: "state",         label: "Estado",       width: 105, align: "start" },
];

const STATE_LABELS = {
    confirmed: "En espera",
    waiting:   "Esperando otra op.",
    assigned:  "Preparado",
};

class MovementsDashboardWidget extends Component {
    static template = "odoo_mrp_planner_dispatch.MovementsDashboardWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.chartRef     = useRef("movChartCanvas");
        this.chart        = null;
        this.tableCols    = COLS;
        this.cols         = useColManager("inventory_movements", COLS);

        this.state = useState({
            // Filtros (una sola barra para todo el panel; arranca en el mes en curso)
            dateFrom:       firstOfMonth(),
            dateTo:         lastOfMonth(),
            search:         "",
            filter:         null,
            groupBy:        null,
            selectedGroup:  null,
            whIds:          [],
            typeIds:        [],
            warehouses:     [],
            pickingTypes:   [],
            whDropdownOpen:   false,
            typeDropdownOpen: false,
            colsDropdownOpen: false,
            visibleCols: {
                name: true, type_name: true, origin: true, partner: true,
                route: true, warehouse: false, scheduled: true,
                product_names: true, qty_pending: true, state: true,
            },
            page:           1,
            pageSize:       30,
            rows:           [],
            loading:        true,
            loadError:      null,
            sortCol:        "scheduled",
            sortDir:        "asc",
        });

        this._closeAll = () => {
            this.state.whDropdownOpen    = false;
            this.state.typeDropdownOpen  = false;
            this.state.colsDropdownOpen  = false;
        };
        this._debounceTimer = null;

        onMounted(async () => {
            document.addEventListener("click", this._closeAll);
            await loadBundle("web.chartjs_lib");
            await Promise.all([this._loadWarehouses(), this._loadPickingTypes(),
                               this._loadRows()]);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this._closeAll);
            clearTimeout(this._debounceTimer);
            this.cols.cancelResize();
            this._destroyChart();
        });
    }

    // ── Formateadores compartidos ─────────────────────────────────────────────
    fmt(n)     { return fmt(n); }
    fmtPct(n)  { return fmtPct(n); }
    svcClass(n){ return svcClass(n); }
    sortIcon(col) { return sortIcon(col, this.state.sortCol, this.state.sortDir); }
    stateLabel(s) { return STATE_LABELS[s] || s; }
    kpiNumClass(text) {
        const len = String(text ?? "").length;
        if (len <= 10) return "o_planner_num_xl";
        if (len <= 14) return "";
        return "o_planner_num_md";
    }

    // ── Carga de datos ────────────────────────────────────────────────────────

    async _loadWarehouses() {
        try {
            this.state.warehouses = await this.orm.call(
                "mrp.planner.dashboard", "get_warehouses_for_forecast", []);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[MovementsPanel]", e);
        }
    }

    async _loadPickingTypes() {
        try {
            this.state.pickingTypes = await this.orm.call(
                "mrp.planner.dashboard", "get_movements_picking_types",
                [this.state.whIds]);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[MovementsPanel]", e);
        }
    }

    async _loadRows() {
        this.state.loading   = true;
        this.state.loadError = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_movements_pending_table",
                [this.state.dateFrom || null, this.state.dateTo || null,
                 this.state.whIds, this.state.typeIds, this.state.search]);
            this.state.rows = res.rows || [];
            this.state.page = 1;
            this._renderChart();
        } catch (e) {
            console.error("[MovementsPanel]", e);
            this.state.loadError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    _loadRowsDebounced() {
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(() => this._loadRows(), 400);
    }

    // ── Filtros de la barra ───────────────────────────────────────────────────

    onFromChange(ev) { this.state.dateFrom = ev.target.value; this._loadRows(); }
    onToChange(ev)   { this.state.dateTo   = ev.target.value; this._loadRows(); }
    setSearch(text)  { this.state.search  = text; this._loadRowsDebounced(); }
    setFilter(key)   { this.state.filter  = key; this.state.page = 1; }
    setGroupBy(key)  { this.state.groupBy = key; this.state.selectedGroup = null; this.state.page = 1; }

    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.whDropdownOpen;
        this._closeAll();
        this.state.whDropdownOpen = open;
    }
    async _onWhChanged() {
        await this._loadPickingTypes();
        const valid = new Set(this.state.pickingTypes.map(t => t.id));
        this.state.typeIds = this.state.typeIds.filter(id => valid.has(id));
        this._loadRows();
    }
    toggleWarehouse(whId) {
        const ids = this.state.whIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._onWhChanged();
    }
    clearWhs() {
        if (!this.state.whIds.length) return;
        this.state.whIds = [];
        this._onWhChanged();
    }
    get whFilterLabel() {
        const n = this.state.whIds.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.whIds[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }

    toggleTypeDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.typeDropdownOpen;
        this._closeAll();
        this.state.typeDropdownOpen = open;
    }
    togglePickingType(typeId) {
        const ids = this.state.typeIds;
        const i = ids.indexOf(typeId);
        if (i >= 0) ids.splice(i, 1); else ids.push(typeId);
        this._loadRows();
    }
    clearTypes() {
        if (!this.state.typeIds.length) return;
        this.state.typeIds = [];
        this._loadRows();
    }
    get typeFilterLabel() {
        const n = this.state.typeIds.length;
        if (!n) return "Todos los tipos";
        if (n === 1) {
            const t = this.state.pickingTypes.find(t => t.id === this.state.typeIds[0]);
            return t ? t.name : "1 tipo";
        }
        return `${n} tipos`;
    }

    toggleColsDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.colsDropdownOpen;
        this._closeAll();
        this.state.colsDropdownOpen = open;
    }
    toggleCol(key) { this.state.visibleCols[key] = !this.state.visibleCols[key]; }

    get staticVisibleCols() {
        return this.cols.visibleCols().filter(col => {
            if (col.fixed) return true;
            return !!this.state.visibleCols[col.key];
        });
    }

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortCol = col;
            this.state.sortDir = "asc";
        }
    }

    // ── Gráfico: composición del pendiente por depósito ──────────────────────
    //    (sobre el conjunto que devuelve el servidor: fechas/depósitos/tipos/búsqueda)

    _destroyChart() {
        if (this.chart) { this.chart.destroy(); this.chart = null; }
    }

    _renderChart() {
        this._destroyChart();
        if (!this.chartRef.el || typeof Chart === "undefined") return;
        const byWh = new Map();  // {wh: [preparado, sinPreparar]}
        for (const r of this.state.rows) {
            const key = r.warehouse || "Sin depósito";
            if (!byWh.has(key)) byWh.set(key, [0, 0]);
            byWh.get(key)[r.state === "assigned" ? 0 : 1] += r.qty_pending || 0;
        }
        const labels = [...byWh.keys()].sort((a, b) => a.localeCompare(b, "es"));
        this.chart = new Chart(this.chartRef.el, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Preparado",
                        data: labels.map(l => byWh.get(l)[0]),
                        backgroundColor: "rgba(13,202,240,0.75)",
                    },
                    {
                        label: "Sin preparar",
                        data: labels.map(l => byWh.get(l)[1]),
                        backgroundColor: "rgba(220,53,69,0.65)",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { x: { stacked: true }, y: { stacked: true } },
                plugins: { legend: { position: "bottom" } },
            },
        });
    }

    // ── Filtros client-side + pestañas de agrupamiento ───────────────────────

    get filteredRows() {
        let rows = this.state.rows;
        const f = this.state.filter;
        if (f === "assigned") rows = rows.filter(r => r.state === "assigned");
        if (f === "waiting")  rows = rows.filter(r => r.state === "confirmed" || r.state === "waiting");
        if (f === "overdue")  rows = rows.filter(r => r.overdue_days > 0);
        return rows;
    }

    _groupKey(row) {
        const gb = this.state.groupBy;
        if (gb === "type")      return row.type_name || "Sin tipo";
        if (gb === "warehouse") return row.warehouse || "Sin depósito";
        if (gb === "state")     return this.stateLabel(row.state);
        if (gb === "sched_month") {
            if (!row.scheduled) return "Sin fecha";
            const parts = String(row.scheduled).split("/");
            return parts.length === 3 ? `${parts[1]}/${parts[2]}` : "Sin fecha";
        }
        return "";
    }

    get allGroupsForTabs() {
        if (!this.state.groupBy) return null;
        const counts = new Map();
        for (const r of this.filteredRows) {
            const key = this._groupKey(r);
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        return [...counts.entries()]
            .sort((a, b) => a[0].localeCompare(b[0], "es", { sensitivity: "base" }))
            .map(([key, count]) => ({ key, label: key, count }));
    }

    get activeGroupKey() {
        const groups = this.allGroupsForTabs || [];
        if (groups.some(g => g.key === this.state.selectedGroup)) {
            return this.state.selectedGroup;
        }
        return groups.length ? groups[0].key : null;
    }

    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
    }

    get groupedRows() {
        if (!this.state.groupBy) return this.filteredRows;
        const active = this.activeGroupKey;
        return this.filteredRows.filter(r => this._groupKey(r) === active);
    }

    get sortedRows() {
        const { sortCol, sortDir } = this.state;
        const dir = sortDir === "asc" ? 1 : -1;
        return [...this.groupedRows].sort((a, b) => {
            const va = a[sortCol], vb = b[sortCol];
            if (va === null || va === undefined) return 1;
            if (vb === null || vb === undefined) return -1;
            if (typeof va === "number") return (va - vb) * dir;
            return String(va).localeCompare(String(vb), "es") * dir;
        });
    }

    /** KPIs dinámicos: describen exactamente lo que la tabla muestra. */
    get movKpis() {
        const rows = this.groupedRows;
        let pending = 0, ready = 0, overdue = 0;
        for (const r of rows) {
            pending += r.qty_pending || 0;
            if (r.state === "assigned") ready += r.qty_pending || 0;
            if (r.overdue_days > 0) overdue++;
        }
        return {
            pending:  Math.round(pending * 100) / 100,
            ready:    Math.round(ready * 100) / 100,
            notready: Math.round((pending - ready) * 100) / 100,
            pickings: rows.length,
            overdue,
            pct_ready: pending > 0 ? Math.round(ready / pending * 1000) / 10 : null,
        };
    }

    // ── Paginación ────────────────────────────────────────────────────────────

    get pagedRows() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.sortedRows.slice(start, start + this.state.pageSize);
    }
    get totalPages()  { return Math.max(1, Math.ceil(this.sortedRows.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    productsTitle(row) {
        return (row.products_detail || []).map(p => p.name).join(", ");
    }

    // ── Drills ────────────────────────────────────────────────────────────────

    openPicking(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: row.picking_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
    openOrigin(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: row.origin_model,
            res_id: row.origin_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
    openProduct(productId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ── Export CSV ────────────────────────────────────────────────────────────

    exportCsv() {
        const cols = this.staticVisibleCols;
        const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const lines = [cols.map(c => esc(c.label)).join(";")];
        for (const r of this.sortedRows) {
            lines.push(cols.map(c => {
                if (c.key === "state") return esc(this.stateLabel(r.state));
                if (c.key === "route") return esc(`${r.loc_from} → ${r.loc_to}`);
                if (c.key === "product_names" && r.products_detail && r.products_detail.length) {
                    return esc(r.products_detail.map(p => p.name).join(", "));
                }
                return esc(r[c.key]);
            }).join(";"));
        }
        const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `movimientos_pendientes_${toDateStr(new Date())}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
}

registry.category("view_widgets").add("movements_dashboard_widget", {
    component: MovementsDashboardWidget,
});
