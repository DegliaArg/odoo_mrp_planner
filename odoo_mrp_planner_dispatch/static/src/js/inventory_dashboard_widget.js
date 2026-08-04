/**
 * inventory_dashboard_widget.js (odoo_mrp_planner_dispatch)
 *
 * Widget del Panel de Inventario. Los números usan solo datos estándar de
 * Odoo (pendiente = eslabones sin validar, entregado = salida validada por
 * date_done); el circuito de despacho, si está activo, agrega únicamente la
 * cola "Validado s/ despachar" y el botón masivo en la tabla.
 *
 * Dos zonas con barras de filtros independientes (misma estructura que el
 * panel de ventas):
 *   - Zona superior: KPIs de entregas + gráficos (evolución mensual de la
 *     tasa de entrega s/ disponible y composición del pendiente por depósito).
 *     RPC: get_inventory_dashboard_data(periodFrom, periodTo, warehouseIds).
 *   - Zona inferior: tabla operativa de salidas pendientes (con selección y
 *     "Marcar despachado" masivo solo si el circuito está activo).
 *     RPC: get_inventory_pending_table(dateFrom, dateTo, warehouseIds, search).
 *
 * Reutiliza los patrones compartidos del módulo base para mantener la
 * estética de los demás paneles:
 *   - formateadores (números es-AR, tasas con un decimal y semáforo),
 *   - PlannerSearchBar (búsqueda + Filtros/Agrupar por/Favoritos),
 *   - useColManager (columnas reordenables por drag & drop, resize y
 *     persistencia en localStorage — mismo uso que el forecast).
 *
 * La búsqueda de texto de la tabla sigue yendo al servidor; los filtros y la
 * agrupación de la barra de búsqueda se aplican client-side sobre state.rows.
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

// Columnas de la tabla de salidas pendientes. El orden y el ancho los
// gestiona useColManager (drag & drop + resize, persistidos en localStorage);
// la visibilidad vive en state.visibleCols (mismo esquema que el forecast).
const COLS = [
    { key: "name",           label: "Remito",      width: 110, fixed: true, align: "start" },
    { key: "stage_label",    label: "Etapa",       width: 120, align: "start" },
    { key: "origin",         label: "Origen",      width: 110, align: "start" },
    { key: "warehouse",      label: "Depósito",    width: 120, align: "start" },
    { key: "scheduled",      label: "Fecha prog.", width: 120, align: "start" },
    { key: "product_names",  label: "Artículos",   width: 230, align: "start" },
    { key: "qty_pending",    label: "Pendiente",   width:  90, align: "end" },
    { key: "qty_available",  label: "Con stock",   width:  90, align: "end" },
    { key: "days_available", label: "Días disp.",  width:  85, align: "end" },
    { key: "state",          label: "Estado",      width: 105, align: "start" },
];

const STATE_LABELS = {
    confirmed: "En espera",
    waiting:   "Esperando otra op.",
    assigned:  "Preparado",
    done:      "Validado",
};

class InventoryDashboardWidget extends Component {
    static template = "odoo_mrp_planner_dispatch.InventoryDashboardWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm          = useService("orm");
        this.action       = useService("action");
        this.notification = useService("notification");
        this.trendRef     = useRef("trendCanvas");
        this.pendingRef   = useRef("pendingCanvas");
        this.trendChart   = null;
        this.pendingChart = null;
        this.tableCols    = COLS;
        // Columnas reordenables/redimensionables — mismo hook que el forecast
        this.cols         = useColManager("inventory_static", COLS);

        this.state = useState({
            // ── Zona gráficos ──
            chartFrom:      firstOfMonth(),
            chartTo:        lastOfMonth(),
            chartWhIds:     [],
            whDropdownOpen: false,
            warehouses:     [],
            data:           null,
            chartLoading:   true,
            chartError:     null,
            // ── Zona tabla ── (arranca en el mes en curso)
            tblFrom:        firstOfMonth(),
            tblTo:          lastOfMonth(),
            tblSearch:      "",
            tblFilter:      null,   // filtro client-side de la barra de búsqueda
            tblGroupBy:     null,   // agrupación client-side de la barra de búsqueda
            tblSelectedGroup: null, // pestaña activa del agrupamiento
            tblWhIds:       [],
            tblWhDropdownOpen: false,
            colsDropdownOpen:  false,
            visibleCols: {
                name: true, stage_label: true, origin: true, warehouse: false,
                scheduled: true, product_names: true, qty_pending: true,
                qty_available: true, days_available: true, state: true,
            },
            page:           1,
            pageSize:       30,
            rows:           [],
            canDispatch:    false,
            dispatchEnabled: false,
            tableLoading:   true,
            tableError:     null,
            selected:       {},
            sortCol:        "scheduled",
            sortDir:        "asc",
            dispatching:    false,
        });

        this._closeAll = () => {
            this.state.whDropdownOpen    = false;
            this.state.tblWhDropdownOpen = false;
            this.state.colsDropdownOpen  = false;
        };
        this._tblDebounceTimer = null;

        onMounted(async () => {
            document.addEventListener("click", this._closeAll);
            await loadBundle("web.chartjs_lib");
            // Los depósitos, los gráficos y la tabla son RPCs independientes
            await Promise.all([this._loadWarehouses(), this._loadCharts(), this._loadTable()]);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this._closeAll);
            clearTimeout(this._tblDebounceTimer);
            this.cols.cancelResize();
            this._destroyCharts();
        });
    }

    // ── Formateadores compartidos ─────────────────────────────────────────────
    fmt(n)     { return fmt(n); }
    fmtPct(n)  { return fmtPct(n); }
    svcClass(n){ return svcClass(n); }
    sortIcon(col) { return sortIcon(col, this.state.sortCol, this.state.sortDir); }
    stateLabel(s) { return STATE_LABELS[s] || s; }

    // ── Zona gráficos ─────────────────────────────────────────────────────────

    async _loadWarehouses() {
        try {
            this.state.warehouses = await this.orm.call(
                "mrp.planner.dashboard", "get_warehouses_for_forecast", []);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[InventoryPanel]", e);
        }
    }

    async _loadCharts() {
        this.state.chartLoading = true;
        this.state.chartError   = null;
        try {
            this.state.data = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_dashboard_data",
                [this.state.chartFrom, this.state.chartTo, this.state.chartWhIds]);
            this._renderCharts();
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.state.chartError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.chartLoading = false;
        }
    }

    onChartFromChange(ev) { this.state.chartFrom = ev.target.value; this._loadCharts(); }
    onChartToChange(ev)   { this.state.chartTo   = ev.target.value; this._loadCharts(); }
    setCurrentMonth() {
        this.state.chartFrom = firstOfMonth();
        this.state.chartTo   = lastOfMonth();
        this._loadCharts();
    }
    /** True si el rango activo coincide con el mes en curso (para pintar el preset). */
    get isCurrentMonth() {
        return this.state.chartFrom === firstOfMonth() && this.state.chartTo === lastOfMonth();
    }
    toggleWhDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.whDropdownOpen;
        this._closeAll();
        this.state.whDropdownOpen = open;
    }
    toggleWarehouse(whId) {
        const ids = this.state.chartWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._loadCharts();
    }
    clearChartWhs() {
        if (!this.state.chartWhIds.length) return;
        this.state.chartWhIds = [];
        this._loadCharts();
    }
    get whFilterLabel() {
        const n = this.state.chartWhIds.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.chartWhIds[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }

    _destroyCharts() {
        if (this.trendChart)   { this.trendChart.destroy();   this.trendChart = null; }
        if (this.pendingChart) { this.pendingChart.destroy(); this.pendingChart = null; }
    }

    _renderCharts() {
        this._destroyCharts();
        const d = this.state.data;
        if (!d || typeof Chart === "undefined") return;

        // ── Evolución mensual de la tasa s/ disponible ──
        if (this.trendRef.el && d.trend && d.trend.length) {
            const labels = d.trend.map(m => {
                const [y, mo] = m.ym.split("-");
                return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
            });
            this.trendChart = new Chart(this.trendRef.el, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Tasa de entrega s/ disponible",
                        data: d.trend.map(m => m.rate),
                        borderColor: "#0d6efd",
                        backgroundColor: "rgba(13,110,253,0.10)",
                        fill: true,
                        spanGaps: true,
                        tension: 0.25,
                        pointRadius: 4,
                        // Meses en vivo (sin consolidar) con punto vacío
                        pointBackgroundColor: d.trend.map(
                            m => m.source === "monthly" ? "#0d6efd" : "#ffffff"),
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: { y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => {
                                    const m = d.trend[ctx.dataIndex];
                                    const src = m.source === "monthly" ? "consolidado" : "en vivo";
                                    return m.rate === null
                                        ? "Sin datos"
                                        : `${m.rate}% (${src}) — entr. ${fmt(m.num)} / disp. no entr. ${fmt(m.den_extra)}`;
                                },
                            },
                        },
                    },
                },
            });
        }

        // ── Composición del pendiente por depósito ──
        if (this.pendingRef.el && d.pending_by_wh && d.pending_by_wh.length) {
            this.pendingChart = new Chart(this.pendingRef.el, {
                type: "bar",
                data: {
                    labels: d.pending_by_wh.map(w => w.warehouse),
                    datasets: [
                        {
                            label: "Con stock",
                            data: d.pending_by_wh.map(w => w.available),
                            backgroundColor: "rgba(13,202,240,0.75)",
                        },
                        {
                            label: "Sin stock",
                            data: d.pending_by_wh.map(w => w.blocked),
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
    }

    // ── Tooltips de KPIs ──────────────────────────────────────────────────────

    kpiTooltip(key) {
        const k = (this.state.data && this.state.data.kpis) || {};
        switch (key) {
            case "pending":
                return `Demanda aún no entregada, en cualquier eslabón de la cadena de entrega (recolección, embalaje o salida a cliente)\n${k.pending_pickings || 0} remito(s) pendiente(s)`;
            case "available":
                return "Del pendiente actual, cantidad con stock reservado en su eslabón: podría entregarse hoy. Clic para ver los remitos.";
            case "blocked":
                return "Del pendiente actual, cantidad sin stock reservado en su eslabón: frenada por falta de disponibilidad. Clic para ver los remitos en espera.";
            case "delivered":
                return `Cantidad entregada en el período: salidas a cliente validadas, por fecha de validación\n${k.delivered_pickings || 0} remito(s)`;
            case "rate":
                return `Entregado ÷ (entregado + lo que estuvo disponible y no salió)\n→ ${fmt(k.rate_available_num)} ÷ ${fmt(k.rate_available_den)} = ${fmtPct(k.rate_available)}\nMeses cerrados desde el consolidado; mes en curso desde los snapshots diarios.`;
            case "delay":
                return "Días promedio entre la fecha programada y la validación de las salidas entregadas del período (negativo = se entregó antes de lo programado).";
            default:
                return "";
        }
    }

    // ── Drills ────────────────────────────────────────────────────────────────

    async openPending(mode) {
        const act = await this.orm.call("mrp.planner.dashboard", "action_inventory_pending",
            [mode, this.state.chartWhIds]);
        this.action.doAction(act);
    }
    async openDelivered() {
        const act = await this.orm.call("mrp.planner.dashboard", "action_inventory_delivered",
            [this.state.chartFrom, this.state.chartTo, this.state.chartWhIds]);
        this.action.doAction(act);
    }
    openPicking(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: row.picking_id,
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
    openOrigin(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: row.origin_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ── Zona tabla ────────────────────────────────────────────────────────────

    async _loadTable() {
        this.state.tableLoading = true;
        this.state.tableError   = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_pending_table",
                [this.state.tblFrom || null, this.state.tblTo || null,
                 this.state.tblWhIds, this.state.tblSearch]);
            this.state.rows            = res.rows || [];
            this.state.canDispatch     = !!res.can_dispatch;
            this.state.dispatchEnabled = !!res.dispatch_enabled;
            this.state.selected        = {};
            this.state.page        = 1;
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.state.tableError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.tableLoading = false;
        }
    }

    _loadTableDebounced() {
        clearTimeout(this._tblDebounceTimer);
        this._tblDebounceTimer = setTimeout(() => this._loadTable(), 400);
    }

    onTblFromChange(ev)   { this.state.tblFrom   = ev.target.value; this._loadTable(); }
    onTblToChange(ev)     { this.state.tblTo     = ev.target.value; this._loadTable(); }
    // La búsqueda de texto sigue resolviéndose en el servidor (con debounce);
    // filtro y agrupación son client-side, así que no requieren RPC.
    setTblSearch(text)    { this.state.tblSearch = text; this._loadTableDebounced(); }
    setTblFilter(key)     { this.state.tblFilter  = key; this.state.page = 1; }
    setTblGroupBy(key)    { this.state.tblGroupBy = key; this.state.tblSelectedGroup = null; this.state.page = 1; }
    toggleTblWhDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.tblWhDropdownOpen;
        this._closeAll();
        this.state.tblWhDropdownOpen = open;
    }
    toggleTblWarehouse(whId) {
        const ids = this.state.tblWhIds;
        const i = ids.indexOf(whId);
        if (i >= 0) ids.splice(i, 1); else ids.push(whId);
        this._loadTable();
    }
    clearTblWhs() {
        if (!this.state.tblWhIds.length) return;
        this.state.tblWhIds = [];
        this._loadTable();
    }
    get tblWhFilterLabel() {
        const n = this.state.tblWhIds.length;
        if (!n) return "Todos los depósitos";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.tblWhIds[0]);
            return wh ? wh.name : "1 depósito";
        }
        return `${n} depósitos`;
    }
    toggleColsDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.colsDropdownOpen;
        this._closeAll();
        this.state.colsDropdownOpen = open;
    }
    toggleCol(key) { this.state.visibleCols[key] = !this.state.visibleCols[key]; }

    /** Columnas visibles en el orden gestionado por el col manager (como el forecast). */
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

    // ── Filtros y agrupación client-side (barra de búsqueda) ──────────────────

    /** Remitos de la cola operativa "Validado s/ despachar" (solo existe con
     *  el circuito de despacho activo; no participan de los KPIs). */
    get readyCount() {
        return this.state.rows.filter(r => r.stage === "ready").length;
    }

    /** Filtros de la barra de búsqueda; la cola de despacho solo aparece con
     *  el circuito activo. */
    get tblFilterDefs() {
        const defs = [
            { key: "assigned",       label: "Preparados" },
            { key: "waiting",        label: "En espera" },
            { key: "overdue",        label: "Vencidas" },
            { key: "available_days", label: "Disponibles hace 3+ días" },
        ];
        if (this.state.dispatchEnabled) {
            defs.push({ key: "ready", label: "Validadas s/ despachar" });
        }
        return defs;
    }

    get filteredRows() {
        let rows = this.state.rows;
        const f = this.state.tblFilter;
        if (f === "assigned")       rows = rows.filter(r => r.state === "assigned");
        if (f === "waiting")        rows = rows.filter(r => r.state === "confirmed" || r.state === "waiting");
        if (f === "ready")          rows = rows.filter(r => r.stage === "ready");
        if (f === "overdue")        rows = rows.filter(r => r.overdue_days > 0);
        if (f === "available_days") rows = rows.filter(r => r.days_available !== null && r.days_available >= 3);
        return rows;
    }

    /** Clave de agrupación de una fila según state.tblGroupBy. */
    _groupKey(row) {
        const gb = this.state.tblGroupBy;
        if (gb === "stage")     return row.stage_label || "Sin etapa";
        if (gb === "warehouse") return row.warehouse || "Sin depósito";
        if (gb === "state")     return this.stateLabel(row.state);
        if (gb === "sched_month") {
            // scheduled llega como 'dd/mm/yyyy' → agrupar por 'mm/yyyy'
            if (!row.scheduled) return "Sin fecha";
            const parts = String(row.scheduled).split("/");
            return parts.length === 3 ? `${parts[1]}/${parts[2]}` : "Sin fecha";
        }
        return "";
    }

    // ── Pestañas de agrupamiento (mismo patrón que clientes/forecast/quiebres:
    //    la tabla muestra solo el grupo activo) ────────────────────────────────

    /** Un grupo por valor del campo activo, con conteo, sobre el conjunto
     *  filtrado/buscado (sin la pestaña aplicada). null sin agrupación. */
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

    /** Pestaña activa: la seleccionada si sigue existiendo, si no la primera. */
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

    /** Filas visibles: con agrupación activa, solo las de la pestaña activa. */
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

    // ── Paginación (mismo esquema que el forecast: 50 filas por página) ───────

    get pagedRows() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.sortedRows.slice(start, start + this.state.pageSize);
    }
    get totalPages()  { return Math.max(1, Math.ceil(this.sortedRows.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    /** Title con la lista completa de artículos (para el sufijo "+N"). */
    productsTitle(row) {
        return (row.products_detail || []).map(p => p.name).join(", ");
    }

    // ── Selección + despacho masivo ───────────────────────────────────────────

    toggleSelect(row) {
        // Solo lo validado sin despachar puede marcarse como despachado
        if (row.stage !== "ready") return;
        this.state.selected[row.picking_id] = !this.state.selected[row.picking_id];
    }
    get selectedIds() {
        return Object.keys(this.state.selected).filter(k => this.state.selected[k]).map(Number);
    }
    // "Seleccionar todos" opera sobre la página visible, para no despachar filas fuera de vista
    get selectableRows() { return this.pagedRows.filter(r => r.stage === "ready"); }
    get allSelected() {
        const sel = this.selectableRows;
        return sel.length > 0 && sel.every(r => this.state.selected[r.picking_id]);
    }
    toggleSelectAll() {
        const target = !this.allSelected;
        for (const r of this.selectableRows) {
            this.state.selected[r.picking_id] = target;
        }
    }

    async markDispatched() {
        const ids = this.selectedIds;
        if (!ids.length || this.state.dispatching) return;
        this.state.dispatching = true;
        try {
            await this.orm.call("stock.picking", "action_mark_dispatched", [ids]);
            this.notification.add(
                `${ids.length} remito(s) marcados como despachados.`, { type: "success" });
            await Promise.all([this._loadTable(), this._loadCharts()]);
        } catch (e) {
            console.error("[InventoryPanel]", e);
            this.notification.add(
                (e && e.data && e.data.message) || e.message || String(e), { type: "danger" });
        } finally {
            this.state.dispatching = false;
        }
    }

    // ── Export CSV ────────────────────────────────────────────────────────────

    exportCsv() {
        // Exporta las columnas visibles en su orden actual; con agrupación
        // activa se exportan igual las filas planas (sin encabezados de grupo).
        const cols = this.staticVisibleCols;
        const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
        const lines = [cols.map(c => esc(c.label)).join(";")];
        for (const r of this.sortedRows) {
            lines.push(cols.map(c => {
                if (c.key === "state") return esc(this.stateLabel(r.state));
                if (c.key === "product_names" && r.products_detail && r.products_detail.length) {
                    return esc(r.products_detail.map(p => p.name).join(", "));
                }
                return esc(r[c.key]);
            }).join(";"));
        }
        const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `salidas_pendientes_${toDateStr(new Date())}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
}

registry.category("view_widgets").add("inventory_dashboard_widget", {
    component: InventoryDashboardWidget,
});
