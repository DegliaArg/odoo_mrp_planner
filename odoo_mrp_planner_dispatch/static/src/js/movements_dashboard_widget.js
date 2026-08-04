/**
 * movements_dashboard_widget.js (odoo_mrp_planner_dispatch)
 *
 * Widget del panel "Movimientos pendientes": recepciones y transferencias
 * pendientes — el complemento del Panel de Inventario (que cubre la cadena
 * de entrega a clientes).
 *
 * Misma estructura que los demás paneles, con dos zonas independientes:
 *   - Zona gráfico: barra de filtros propia (fechas programadas, tipos de
 *     operación y depósitos) + composición del pendiente por depósito.
 *     RPC: get_movements_pending_table con los filtros de esta zona.
 *   - Zona tabla: barra propia (fechas, búsqueda, tipos, depósitos,
 *     columnas, export) + cards KPI dinámicas que describen exactamente lo
 *     que la tabla muestra + pestañas de agrupamiento + tabla.
 *     RPC: get_movements_pending_table con los filtros de esta zona.
 *
 * Reutiliza los componentes compartidos: PlannerSearchBar, useColManager,
 * formateadores es-AR y Chart.js.
 */

/** @odoo-module **/

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
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
            warehouses:     [],
            // ── Zona gráfico (filtros propios; arranca en el mes en curso) ──
            chartFrom:      firstOfMonth(),
            chartTo:        lastOfMonth(),
            chartWhIds:     [],
            chartTypeIds:   [],
            chartTypes:     [],
            chartWhOpen:    false,
            chartTypeOpen:  false,
            chartRows:      [],
            chartLoading:   true,
            chartError:     null,
            // ── Zona tabla (filtros propios; arranca en el mes en curso) ──
            tblFrom:        firstOfMonth(),
            tblTo:          lastOfMonth(),
            tblSearch:      "",
            tblFilter:      null,
            tblGroupBy:     null,
            tblSelectedGroup: null,
            tblWhIds:       [],
            tblTypeIds:     [],
            tblTypes:       [],
            tblWhOpen:      false,
            tblTypeOpen:    false,
            colsDropdownOpen: false,
            visibleCols: {
                name: true, type_name: true, origin: true, partner: true,
                route: true, warehouse: false, scheduled: true,
                product_names: true, qty_pending: true, state: true,
            },
            page:           1,
            pageSize:       30,
            rows:           [],
            selected:       {},
            tableLoading:   true,
            tableError:     null,
            sortCol:        "scheduled",
            sortDir:        "asc",
        });

        this._closeAll = () => {
            this.state.chartWhOpen      = false;
            this.state.chartTypeOpen    = false;
            this.state.tblWhOpen        = false;
            this.state.tblTypeOpen      = false;
            this.state.colsDropdownOpen = false;
        };
        this._debounceTimer = null;
        // En la primera carga el canvas no existe todavía (t-if del spinner):
        // el flag deja el redibujo pendiente y onPatched lo completa cuando el
        // DOM ya tiene el lienzo (mismo patrón que el gráfico de ventas).
        this._chartDirty = false;

        onMounted(async () => {
            document.addEventListener("click", this._closeAll);
            await loadBundle("web.chartjs_lib");
            // Depósitos, tipos, gráfico y tabla: RPCs independientes
            await Promise.all([
                this._loadWarehouses(),
                this._loadTypes("chart"), this._loadTypes("tbl"),
                this._loadChart(), this._loadTable(),
            ]);
        });
        onPatched(() => {
            if (this._chartDirty && this.chartRef.el) this._renderChart();
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

    /** Lista de tipos de operación de una zona, acotada a sus depósitos. */
    async _loadTypes(zone) {
        try {
            const whIds = zone === "chart" ? this.state.chartWhIds : this.state.tblWhIds;
            const types = await this.orm.call(
                "mrp.planner.dashboard", "get_movements_picking_types", [whIds]);
            if (zone === "chart") this.state.chartTypes = types;
            else                  this.state.tblTypes   = types;
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[MovementsPanel]", e);
        }
    }

    async _loadChart() {
        this.state.chartLoading = true;
        this.state.chartError   = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_movements_pending_table",
                [this.state.chartFrom || null, this.state.chartTo || null,
                 this.state.chartWhIds, this.state.chartTypeIds, ""]);
            this.state.chartRows = res.rows || [];
            this._chartDirty = true;
            this._renderChart();
        } catch (e) {
            console.error("[MovementsPanel]", e);
            this.state.chartError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.chartLoading = false;
        }
    }

    async _loadTable() {
        this.state.tableLoading = true;
        this.state.tableError   = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_movements_pending_table",
                [this.state.tblFrom || null, this.state.tblTo || null,
                 this.state.tblWhIds, this.state.tblTypeIds, this.state.tblSearch]);
            this.state.rows     = res.rows || [];
            this.state.selected = {};
            this.state.page     = 1;
        } catch (e) {
            console.error("[MovementsPanel]", e);
            this.state.tableError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.tableLoading = false;
        }
    }

    _loadTableDebounced() {
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(() => this._loadTable(), 400);
    }

    // ── Filtros de la zona gráfico ────────────────────────────────────────────

    onChartFromChange(ev) { this.state.chartFrom = ev.target.value; this._loadChart(); }
    onChartToChange(ev)   { this.state.chartTo   = ev.target.value; this._loadChart(); }
    setCurrentMonth() {
        this.state.chartFrom = firstOfMonth();
        this.state.chartTo   = lastOfMonth();
        this._loadChart();
    }
    get isCurrentMonth() {
        return this.state.chartFrom === firstOfMonth() && this.state.chartTo === lastOfMonth();
    }

    toggleChartWhOpen(ev) {
        ev.stopPropagation();
        const open = !this.state.chartWhOpen;
        this._closeAll();
        this.state.chartWhOpen = open;
    }
    async _onChartWhChanged() {
        await this._loadTypes("chart");
        const valid = new Set(this.state.chartTypes.map(t => t.id));
        this.state.chartTypeIds = this.state.chartTypeIds.filter(id => valid.has(id));
        this._loadChart();
    }
    toggleChartWarehouse(whId) {
        const ids = this.state.chartWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._onChartWhChanged();
    }
    clearChartWhs() {
        if (!this.state.chartWhIds.length) return;
        this.state.chartWhIds = [];
        this._onChartWhChanged();
    }
    toggleChartTypeOpen(ev) {
        ev.stopPropagation();
        const open = !this.state.chartTypeOpen;
        this._closeAll();
        this.state.chartTypeOpen = open;
    }
    toggleChartType(typeId) {
        const ids = this.state.chartTypeIds;
        const i = ids.indexOf(typeId);
        if (i >= 0) ids.splice(i, 1); else ids.push(typeId);
        this._loadChart();
    }
    clearChartTypes() {
        if (!this.state.chartTypeIds.length) return;
        this.state.chartTypeIds = [];
        this._loadChart();
    }
    get chartWhLabel()   { return this._whLabel(this.state.chartWhIds); }
    get chartTypeLabel() { return this._typeLabel(this.state.chartTypeIds, this.state.chartTypes); }

    // ── Filtros de la zona tabla ──────────────────────────────────────────────

    onTblFromChange(ev)  { this.state.tblFrom   = ev.target.value; this._loadTable(); }
    onTblToChange(ev)    { this.state.tblTo     = ev.target.value; this._loadTable(); }
    setTblSearch(text)   { this.state.tblSearch = text; this._loadTableDebounced(); }
    setTblFilter(key)    { this.state.tblFilter  = key; this.state.page = 1; }
    setTblGroupBy(key)   { this.state.tblGroupBy = key; this.state.tblSelectedGroup = null; this.state.page = 1; }

    toggleTblWhOpen(ev) {
        ev.stopPropagation();
        const open = !this.state.tblWhOpen;
        this._closeAll();
        this.state.tblWhOpen = open;
    }
    async _onTblWhChanged() {
        await this._loadTypes("tbl");
        const valid = new Set(this.state.tblTypes.map(t => t.id));
        this.state.tblTypeIds = this.state.tblTypeIds.filter(id => valid.has(id));
        this._loadTable();
    }
    toggleTblWarehouse(whId) {
        const ids = this.state.tblWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._onTblWhChanged();
    }
    clearTblWhs() {
        if (!this.state.tblWhIds.length) return;
        this.state.tblWhIds = [];
        this._onTblWhChanged();
    }
    toggleTblTypeOpen(ev) {
        ev.stopPropagation();
        const open = !this.state.tblTypeOpen;
        this._closeAll();
        this.state.tblTypeOpen = open;
    }
    toggleTblType(typeId) {
        const ids = this.state.tblTypeIds;
        const i = ids.indexOf(typeId);
        if (i >= 0) ids.splice(i, 1); else ids.push(typeId);
        this._loadTable();
    }
    clearTblTypes() {
        if (!this.state.tblTypeIds.length) return;
        this.state.tblTypeIds = [];
        this._loadTable();
    }
    get tblWhLabel()   { return this._whLabel(this.state.tblWhIds); }
    get tblTypeLabel() { return this._typeLabel(this.state.tblTypeIds, this.state.tblTypes); }

    _whLabel(ids) {
        const n = ids.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === ids[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }
    _typeLabel(ids, types) {
        const n = ids.length;
        if (!n) return "Todos los tipos";
        if (n === 1) {
            const t = types.find(t => t.id === ids[0]);
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

    // ── Gráfico: composición del pendiente por depósito (zona gráfico) ───────

    _destroyChart() {
        if (this.chart) { this.chart.destroy(); this.chart = null; }
    }

    _renderChart() {
        this._destroyChart();
        if (typeof Chart === "undefined") {
            this._chartDirty = false;
            return;
        }
        // Canvas aún no montado (primera carga): onPatched reintenta
        if (!this.chartRef.el) return;
        this._chartDirty = false;
        const byWh = new Map();  // {wh: [preparado, sinPreparar]}
        for (const r of this.state.chartRows) {
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

    // ── Filtros client-side + pestañas de agrupamiento (zona tabla) ──────────

    get filteredRows() {
        let rows = this.state.rows;
        const f = this.state.tblFilter;
        if (f === "assigned") rows = rows.filter(r => r.state === "assigned");
        if (f === "waiting")  rows = rows.filter(r => r.state === "confirmed" || r.state === "waiting");
        if (f === "overdue")  rows = rows.filter(r => r.overdue_days > 0);
        return rows;
    }

    _groupKey(row) {
        const gb = this.state.tblGroupBy;
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
        if (!this.state.tblGroupBy) return null;
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
        if (groups.some(g => g.key === this.state.tblSelectedGroup)) {
            return this.state.tblSelectedGroup;
        }
        return groups.length ? groups[0].key : null;
    }

    setGroup(key) {
        this.state.tblSelectedGroup = key;
        this.state.page = 1;
    }

    get groupedRows() {
        if (!this.state.tblGroupBy) return this.filteredRows;
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

    // ── Selección: recalcula KPIs y totales, igual que buscar o agrupar ──────

    toggleSelect(row) {
        this.state.selected[row.picking_id] = !this.state.selected[row.picking_id];
    }
    get selectedRows() {
        return this.groupedRows.filter(r => this.state.selected[r.picking_id]);
    }
    // "Seleccionar todos" opera sobre la página visible
    get allSelected() {
        const rows = this.pagedRows;
        return rows.length > 0 && rows.every(r => this.state.selected[r.picking_id]);
    }
    toggleSelectAll() {
        const target = !this.allSelected;
        for (const r of this.pagedRows) {
            this.state.selected[r.picking_id] = target;
        }
    }
    clearSelection() {
        this.state.selected = {};
    }

    /** KPIs dinámicos: describen exactamente lo que la tabla muestra —
     *  fechas, búsqueda, filtros, pestaña activa — y, si hay filas
     *  seleccionadas, SOLO la selección. */
    get movKpis() {
        const sel = this.selectedRows;
        const rows = sel.length ? sel : this.groupedRows;
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

    /** Explicación de cada columna de la tabla (convención de los paneles). */
    colTitle(col) {
        const titles = {
            name:          "Número del remito — clic para abrirlo.",
            type_name:     "Tipo de operación del remito: recepción, transferencia interna o salida sin destino cliente (tramo entre depósitos).",
            origin:        "Documento origen del remito — clic para abrir la compra o la venta asociada.",
            partner:       "Contacto del remito (proveedor en recepciones).",
            route:         "Ubicación de origen → ubicación de destino del remito.",
            warehouse:     "Depósito del tipo de operación del remito.",
            scheduled:     "Fecha programada del remito; el badge rojo indica cuántos días está vencido.",
            product_names: "Artículos del remito — clic para abrir la ficha de cada uno; el tooltip de la celda lista todos.",
            qty_pending:   "Piezas demandadas por el remito aún no procesadas.",
            state:         "Estado nativo del remito en Odoo (Preparado = reserva completa, listo para procesar).",
        };
        const base = titles[col.key] || col.label;
        return `${base} Clic en el encabezado para ordenar.`;
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
