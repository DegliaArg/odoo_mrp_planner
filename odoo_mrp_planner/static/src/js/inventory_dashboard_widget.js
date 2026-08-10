/**
 * inventory_dashboard_widget.js (odoo_mrp_planner)
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

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { fmt, fmtPct, svcClass, sortIcon, kpiNumClass } from "@odoo_mrp_planner/js/forecast_formatters";
import { PlannerSearchBar } from "@odoo_mrp_planner/js/planner_search_bar";
import { useColManager } from "@odoo_mrp_planner/js/column_manager";
import { restoreFilters, saveFilters } from "@odoo_mrp_planner/js/filter_persistence";
import { sortRows, buildGroupTabs, resolveActiveGroup, pageSlice, makePager } from "@odoo_mrp_planner/js/planner_table";
import { makeSelection } from "@odoo_mrp_planner/js/planner_selection";
import { makeMultiFilter } from "@odoo_mrp_planner/js/planner_multiselect";
import { downloadCsv } from "@odoo_mrp_planner/js/planner_export";

// Filtros persistidos por empresa (mismo patrón que los demás paneles)
const INV_PERSIST_KEYS = [
    "chartFrom", "chartTo", "chartWhIds", "chartTypeIds",
    "tblFrom", "tblTo", "tblSearch", "tblFilter", "tblGroupBy",
    "tblSelectedGroup", "tblWhIds", "tblTypeIds", "visibleCols",
    "sortCol", "sortDir",
];

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
    { key: "type_name",      label: "Tipo",        width: 150, align: "start" },
    { key: "route",          label: "Desde → Hasta", width: 190, align: "start" },
    { key: "origin",         label: "Origen",      width: 110, align: "start" },
    { key: "warehouse",      label: "Depósito",    width: 120, align: "start" },
    { key: "scheduled",      label: "Fecha prog.", width: 120, align: "start" },
    { key: "product_names",  label: "Artículos",   width: 230, align: "start" },
    { key: "qty_pending",    label: "Pendiente",   width:  90, align: "end" },
    { key: "qty_available",  label: "Con stock",   width:  90, align: "end" },
    { key: "qty_done",       label: "Hecho",       width:  90, align: "end" },
    { key: "days_available", label: "Días disp.",  width:  85, align: "end" },
    { key: "state",          label: "Estado",      width: 105, align: "start" },
];

const PENDING_STATES = ["confirmed", "waiting", "assigned"];

const STATE_LABELS = {
    confirmed: "En espera",
    waiting:   "Esperando otra op.",
    assigned:  "Preparado",
    done:      "Validado",
};

class InventoryDashboardWidget extends Component {
    static template = "odoo_mrp_planner.InventoryDashboardWidget";
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
            chartTypeIds:   [],
            whDropdownOpen: false,
            typeDropdownOpen: false,
            warehouses:     [],
            pickingTypes:   [],
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
            tblTypeIds:     [],
            tblTypes:       [],
            tblWhDropdownOpen: false,
            tblTypeOpen:    false,
            colsDropdownOpen:  false,
            visibleCols: {
                name: true, stage_label: true, type_name: false, route: false,
                origin: true, warehouse: false, scheduled: true,
                product_names: true, qty_pending: true, qty_available: true,
                qty_done: true, days_available: true, state: true,
            },
            page:           1,
            pageSize:       30,
            rows:           [],
            periodKpis:     {},
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
            this.state.typeDropdownOpen  = false;
            this.state.tblWhDropdownOpen = false;
            this.state.tblTypeOpen       = false;
            this.state.colsDropdownOpen  = false;
        };

        // ── Mecánica compartida de los paneles (planner_*) ──
        // Los 4 dropdowns multi-selección (depósitos y tipos, de gráficos y de
        // tabla), la selección de filas y el paginador delegan en las factories
        // comunes; los métodos del template son wrappers de una línea.
        this.whFilter = makeMultiFilter(this, {
            open: "whDropdownOpen", ids: "chartWhIds",
            items: () => this.state.warehouses,
            all: "Todos los depósitos", one: "depósito", many: "depósitos",
            closeOthers: this._closeAll,
            onChange: () => this._onChartWhChanged(),
        });
        this.typeFilter = makeMultiFilter(this, {
            open: "typeDropdownOpen", ids: "chartTypeIds",
            items: () => this.state.pickingTypes,
            all: "Todos los tipos", one: "tipo", many: "tipos",
            closeOthers: this._closeAll,
            onChange: () => this._loadCharts(),
        });
        this.tblWhFilter = makeMultiFilter(this, {
            open: "tblWhDropdownOpen", ids: "tblWhIds",
            items: () => this.state.warehouses,
            all: "Todos los depósitos", one: "depósito", many: "depósitos",
            closeOthers: this._closeAll,
            onChange: () => this._onTblWhChanged(),
        });
        this.tblTypeFilter = makeMultiFilter(this, {
            open: "tblTypeOpen", ids: "tblTypeIds",
            items: () => this.state.tblTypes,
            all: "Todos los tipos", one: "tipo", many: "tipos",
            closeOthers: this._closeAll,
            onChange: () => this._loadTable(),
        });
        this.sel   = makeSelection(this, { key: "picking_id", pageRows: () => this.pagedRows });
        this.pager = makePager(this, () => this.sortedRows.length);
        // Restaurar filtros de la última visita (por empresa). Se guardan en
        // _loadCharts/_loadTable y en los setters client-side.
        const companyId = this.env.services.company?.currentCompany?.id || 0;
        this._persistKey = `inventory_dashboard.${companyId}`;
        restoreFilters(this._persistKey, this.state, INV_PERSIST_KEYS);
        // Columnas nuevas ausentes en lo guardado: completar con el default
        this.state.visibleCols = { qty_done: true, type_name: false, route: false, ...this.state.visibleCols };

        this._tblDebounceTimer = null;
        // En la primera carga los canvas no existen todavía (t-if del spinner):
        // el flag deja el redibujo pendiente y onPatched lo completa cuando el
        // DOM ya tiene los lienzos (mismo patrón que el gráfico de ventas).
        this._chartsDirty = false;

        onMounted(async () => {
            document.addEventListener("click", this._closeAll);
            await loadBundle("web.chartjs_lib");
            // Los depósitos, los tipos, los gráficos y la tabla son RPCs independientes
            await Promise.all([this._loadWarehouses(), this._loadPickingTypes(),
                               this._loadTblTypes(), this._loadCharts(),
                               this._loadTable()]);
        });
        onPatched(() => {
            if (this._chartsDirty && (this.trendRef.el || this.pendingRef.el)) {
                this._renderCharts();
            }
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
    /** Etiqueta de estado de la fila: la nativa del remito (traducida). */
    rowStateLabel(row) { return row.state_label || this.stateLabel(row.state); }

    /** Clase de tamaño de los números de las cards KPI (compartida). */
    kpiNumClass(text) { return kpiNumClass(text); }

    // ── Zona gráficos ─────────────────────────────────────────────────────────

    async _loadWarehouses() {
        try {
            this.state.warehouses = await this.orm.call(
                "mrp.planner.dashboard", "get_warehouses_for_forecast", []);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[InventoryPanel]", e);
        }
    }

    async _loadPickingTypes() {
        try {
            this.state.pickingTypes = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_picking_types",
                [this.state.chartWhIds]);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[InventoryPanel]", e);
        }
    }

    async _loadTblTypes() {
        try {
            this.state.tblTypes = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_picking_types",
                [this.state.tblWhIds]);
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[InventoryPanel]", e);
        }
    }

    /** Al cambiar los depósitos de los gráficos, la lista de tipos se recarga
     *  acotada a esos depósitos y la selección pierde los tipos que ya no
     *  aplican; recién después se recargan los gráficos. */
    async _onChartWhChanged() {
        await this._loadPickingTypes();
        const valid = new Set(this.state.pickingTypes.map(t => t.id));
        this.state.chartTypeIds = this.state.chartTypeIds.filter(id => valid.has(id));
        this._loadCharts();
    }

    _persist() {
        saveFilters(this._persistKey, this.state, INV_PERSIST_KEYS);
    }

    async _loadCharts() {
        this._persist();
        this.state.chartLoading = true;
        this.state.chartError   = null;
        try {
            this.state.data = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_dashboard_data",
                [this.state.chartFrom, this.state.chartTo, this.state.chartWhIds,
                 this.state.chartTypeIds]);
            this._chartsDirty = true;
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
    // Dropdowns de depósitos y tipos de los gráficos: mecánica compartida
    toggleWhDropdown(ev)  { this.whFilter.toggleOpen(ev); }
    toggleWarehouse(whId) { this.whFilter.toggleItem(whId); }
    clearChartWhs()       { this.whFilter.clear(); }
    get whFilterLabel()   { return this.whFilter.label; }

    toggleTypeDropdown(ev)  { this.typeFilter.toggleOpen(ev); }
    togglePickingType(typeId) { this.typeFilter.toggleItem(typeId); }
    clearChartTypes()       { this.typeFilter.clear(); }
    get typeFilterLabel()   { return this.typeFilter.label; }

    _destroyCharts() {
        if (this.trendChart)   { this.trendChart.destroy();   this.trendChart = null; }
        if (this.pendingChart) { this.pendingChart.destroy(); this.pendingChart = null; }
    }

    _renderCharts() {
        this._destroyCharts();
        const d = this.state.data;
        if (!d || typeof Chart === "undefined") {
            this._chartsDirty = false;
            return;
        }
        // Canvas aún no montados (primera carga): onPatched reintenta
        if (!this.trendRef.el && !this.pendingRef.el) return;
        this._chartsDirty = false;

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

    // ── Tooltips de KPIs y columnas ───────────────────────────────────────────

    /** KPIs del período: llegan con la llamada de la tabla (mismos filtros). */
    get periodKpis() {
        return this.state.periodKpis || {};
    }

    /** Tooltips de las cards: descripción, fórmula y sustitución numérica
     *  (→ X ÷ Y = Z), misma estructura que los demás paneles. La navegación
     *  a las listas es SOLO por el botón "Ver →" de cada card. */
    kpiTooltip(key) {
        const k = this.periodKpis;
        const t = this.tableKpis;
        // Las cards de la tabla describen la selección si la hay
        const scope = this.selectedRows.length
            ? `la selección (${this.selectedRows.length} remito(s))`
            : "la tabla";
        switch (key) {
            // ── Cards de la tabla (dinámicas: fechas, búsqueda, filtros, pestaña y selección) ──
            case "pending":
                return `Demanda aún no entregada de ${scope}, de cualquier operación (cadena de entrega, transferencias internas y recepciones)\nSuma de las cantidades pendientes de las líneas visibles\n→ ${fmt(t.pending)} en ${t.pickings} remito(s)`;
            case "available":
                return `Del pendiente de ${scope}, cantidad reservada de los movimientos cuyo estado cuenta como con stock (Ajustes → Inventario; por defecto Disponible y Parcialmente disponible)\nSuma por línea de la cantidad reservada de esos movimientos\n→ ${fmt(t.available)}`;
            case "blocked":
                return `Del pendiente de ${scope}, cantidad sin stock reservado (estados En espera / En espera de otro movimiento, o la parte no reservada de los parcialmente disponibles)\nPendiente − Con stock\n→ ${fmt(t.pending)} − ${fmt(t.available)} = ${fmt(t.blocked)}`;
            case "overdue":
                return `Remitos de ${scope} con la fecha programada vencida o que vencen hoy\n→ ${fmt(t.overdue)} remito(s)`;
            case "pct":
                return `Parte del pendiente de ${scope} que podría entregarse hoy\nCon stock ÷ Pendiente × 100\n→ ${fmt(t.available)} ÷ ${fmt(t.pending)} × 100 = ${fmtPct(t.pct_available)}`;
            // ── Validados: filas hechas de la tabla (dinámica como todas).
            //    La tasa sigue siendo la única card de servidor. ──
            case "delivered":
                return `Remitos HECHOS que muestra la tabla (validados en el rango, por fecha de validación), de ${scope}\nSin tipos seleccionados incluye TODAS las operaciones (recepciones, internas y toda la cadena): la misma mercadería puede sumar en cada eslabón que validó; para ver solo lo que salió, filtrá los tipos de entrega\nSuma de las cantidades hechas\n→ ${fmt(this.validatedKpis.qty)} en ${this.validatedKpis.pickings} remito(s)`;
            case "rate":
                return `De lo que estuvo disponible en el rango de la tabla, cuánto se entregó\nEntregado ÷ (entregado + disponible no entregado) × 100\n→ ${fmt(k.rate_available_num)} ÷ ${fmt(k.rate_available_den)} × 100 = ${fmtPct(k.rate_available)}\nMeses cerrados desde el consolidado; mes en curso desde los snapshots diarios. Requiere rango de fechas completo.${this.selectedRows.length ? "\nLa selección de filas no aplica acá: mide lo YA entregado, que no está en la tabla." : ""}`;
            default:
                return "";
        }
    }

    /** Explicación de cada columna de la tabla (convención de los paneles). */
    colTitle(col) {
        const titles = {
            name:           "Número del remito — clic para abrirlo.",
            stage_label:    "Etapa de la operación: Recolección, Embalaje o Entrega (cadena de entrega), Recepción o Transferencia. \"Validado s/ despachar\" (con el circuito activo) es la entrega ya validada que falta marcar como despachada.",
            type_name:      "Tipo de operación del remito.",
            route:          "Ubicación de origen → ubicación de destino del remito.",
            origin:         "Documento origen del remito — clic para abrir la venta o la compra asociada.",
            warehouse:      "Depósito del tipo de operación del remito.",
            scheduled:      "Fecha programada más próxima de las líneas consideradas del remito (fecha de los movimientos); el badge rojo indica cuántos días está vencida (\"hoy\" = vence hoy).",
            product_names:  "Artículos del remito — clic para abrir la ficha de cada uno; el tooltip de la celda lista todos.",
            qty_pending:    "Cantidad demandada por el remito aún no entregada (en canceladas: la demanda original, informativa).",
            qty_done:       "Cantidad hecha del remito (solo filas validadas).",
            qty_available:  "Cantidad reservada de los movimientos cuyo estado cuenta como con stock (Ajustes → Inventario; por defecto Disponible y Parcialmente disponible).",
            days_available: "Días corridos desde el primer snapshot en que el remito apareció con stock reservado — hace cuánto podría haberse entregado.",
            state:          "Estado nativo del remito en Odoo.",
        };
        const base = titles[col.key] || col.label;
        return `${base} Clic en el encabezado para ordenar.`;
    }

    // ── Drills ────────────────────────────────────────────────────────────────

    openPending(mode) {
        // El drill abre EXACTAMENTE los remitos que el KPI contó: las filas
        // visibles de la tabla (con selección, solo la selección), filtradas
        // por modo. Sin aproximaciones de dominio.
        const all = this.selectedRows.length ? this.selectedRows : this.groupedRows;
        const base = all.filter(r => PENDING_STATES.includes(r.state));
        let rows = base;
        let name = "Demanda pendiente de entrega";
        if (mode === "available") {
            rows = base.filter(r => (r.qty_available || 0) > 0);
            name = "Demanda pendiente con stock";
        } else if (mode === "blocked") {
            rows = base.filter(r => (r.qty_available || 0) < (r.qty_pending || 0));
            name = "Demanda pendiente sin stock";
        } else if (mode === "overdue") {
            rows = base.filter(r => r.overdue_days !== null && r.overdue_days >= 0);
            name = "Demanda pendiente vencida";
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "stock.picking",
            domain: [["id", "in", rows.map(r => r.picking_id)]],
            views: [[false, "list"], [false, "form"]],
            // Una sola página con todos los remitos: los totales del pie de
            // Odoo suman solo lo cargado, y así cierran con las cards
            limit: Math.max(rows.length, 80),
            // Lista propia de los drills de pendiente: Demanda / Con stock /
            // Sin stock por remito
            context: {
                create: false,
                list_view_ref: "odoo_mrp_planner.view_picking_list_planner_drill_pending",
                // Las columnas de cantidad de la lista respetan el mismo corte
                // por línea (stock.move.date) que la tabla del panel
                planner_date_from: this.state.tblFrom || false,
                planner_date_to: this.state.tblTo || false,
            },
            target: "current",
        });
    }
    openValidated() {
        // Exactamente las filas HECHAS que la card contó (con selección,
        // solo la selección). Lista con una sola columna de cantidad
        // ("Cantidad hecha"): para remitos ya entregados no aplican Con/Sin
        // stock (todo lo hecho está disponible), así que serían redundantes.
        const all = this.selectedRows.length ? this.selectedRows : this.groupedRows;
        const rows = all.filter(r => r.state === "done");
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Validados del período",
            res_model: "stock.picking",
            domain: [["id", "in", rows.map(r => r.picking_id)]],
            views: [[false, "list"], [false, "form"]],
            limit: Math.max(rows.length, 80),
            context: {
                create: false,
                list_view_ref: "odoo_mrp_planner.view_picking_list_planner_drill",
            },
            target: "current",
        });
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
            res_model: row.origin_model || "sale.order",
            res_id: row.origin_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ── Zona tabla ────────────────────────────────────────────────────────────

    async _loadTable() {
        this._persist();
        this.state.tableLoading = true;
        this.state.tableError   = null;
        try {
            const res = await this.orm.call(
                "mrp.planner.dashboard", "get_inventory_pending_table",
                [this.state.tblFrom || null, this.state.tblTo || null,
                 this.state.tblWhIds, this.state.tblSearch,
                 this.state.tblTypeIds]);
            this.state.rows            = res.rows || [];
            this.state.periodKpis      = res.period_kpis || {};
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

    // El rango es obligatorio: vaciar un extremo restaura el mes en curso
    onTblFromChange(ev)   { this.state.tblFrom   = ev.target.value || firstOfMonth(); this._loadTable(); }
    onTblToChange(ev)     { this.state.tblTo     = ev.target.value || lastOfMonth(); this._loadTable(); }
    // La búsqueda de texto sigue resolviéndose en el servidor (con debounce);
    // filtro y agrupación son client-side, así que no requieren RPC.
    setTblSearch(text)    { this.state.tblSearch = text; this._loadTableDebounced(); }
    setTblFilter(key)     { this.state.tblFilter  = key; this.state.page = 1; this._persist(); }
    setTblGroupBy(key)    { this.state.tblGroupBy = key; this.state.tblSelectedGroup = null; this.state.page = 1; this._persist(); }
    async _onTblWhChanged() {
        await this._loadTblTypes();
        const valid = new Set(this.state.tblTypes.map(t => t.id));
        this.state.tblTypeIds = this.state.tblTypeIds.filter(id => valid.has(id));
        this._loadTable();
    }
    // Dropdowns de depósitos y tipos de la tabla: mecánica compartida
    toggleTblWhDropdown(ev)  { this.tblWhFilter.toggleOpen(ev); }
    toggleTblWarehouse(whId) { this.tblWhFilter.toggleItem(whId); }
    clearTblWhs()            { this.tblWhFilter.clear(); }
    get tblWhFilterLabel()   { return this.tblWhFilter.label; }

    toggleTblTypeOpen(ev) { this.tblTypeFilter.toggleOpen(ev); }
    toggleTblType(typeId) { this.tblTypeFilter.toggleItem(typeId); }
    clearTblTypes()       { this.tblTypeFilter.clear(); }
    get tblTypeLabel()    { return this.tblTypeFilter.label; }
    toggleColsDropdown(ev) {
        ev.stopPropagation();
        const open = !this.state.colsDropdownOpen;
        this._closeAll();
        this.state.colsDropdownOpen = open;
    }
    toggleCol(key) { this.state.visibleCols[key] = !this.state.visibleCols[key]; this._persist(); }

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
        this._persist();
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
            { key: "with_stock",     label: "Con stock" },
            { key: "assigned",       label: "Listos" },
            { key: "waiting",        label: "En espera" },
            { key: "overdue",        label: "Vencidas" },
            { key: "available_days", label: "Disponibles hace 3+ días" },
        ];
        defs.push({ key: "done",      label: "Hechos" });
        defs.push({ key: "cancelled", label: "Canceladas" });
        if (this.state.dispatchEnabled) {
            defs.push({ key: "ready", label: "Validadas s/ despachar" });
        }
        return defs;
    }

    get filteredRows() {
        let rows = this.state.rows;
        const f = this.state.tblFilter;
        if (f === "with_stock")     rows = rows.filter(r => (r.qty_available || 0) > 0);
        if (f === "assigned")       rows = rows.filter(r => r.state === "assigned");
        if (f === "waiting")        rows = rows.filter(r => r.state === "confirmed" || r.state === "waiting");
        if (f === "done")           rows = rows.filter(r => r.state === "done");
        if (f === "cancelled")      rows = rows.filter(r => r.state === "cancel");
        if (f === "ready")          rows = rows.filter(r => r.stage === "ready");
        if (f === "overdue")        rows = rows.filter(r => r.overdue_days !== null && r.overdue_days >= 0);
        if (f === "available_days") rows = rows.filter(r => r.days_available !== null && r.days_available >= 3);
        return rows;
    }

    /** Clave de agrupación de una fila según state.tblGroupBy. */
    _groupKey(row) {
        const gb = this.state.tblGroupBy;
        if (gb === "stage")     return row.stage_label || "Sin etapa";
        if (gb === "warehouse") return row.warehouse || "Sin depósito";
        if (gb === "state")     return this.rowStateLabel(row);
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
        return buildGroupTabs(this.filteredRows, r => this._groupKey(r));
    }

    /** Pestaña activa: la seleccionada si sigue existiendo, si no la primera. */
    get activeGroupKey() {
        return resolveActiveGroup(this.allGroupsForTabs || [], this.state.tblSelectedGroup);
    }

    setGroup(key) {
        this.state.tblSelectedGroup = key;
        this.state.page = 1;
        this._persist();
    }

    /** Filas visibles: con agrupación activa, solo las de la pestaña activa. */
    get groupedRows() {
        if (!this.state.tblGroupBy) return this.filteredRows;
        const active = this.activeGroupKey;
        return this.filteredRows.filter(r => this._groupKey(r) === active);
    }

    get sortedRows() {
        return sortRows(this.groupedRows, this.state.sortCol, this.state.sortDir);
    }

    /** Filas seleccionadas dentro del conjunto visible (todas las páginas). */
    get selectedRows() {
        return this.sel.pick(this.groupedRows);
    }

    /** KPIs dinámicos de la zona tabla: describen exactamente lo que la tabla
     *  muestra — fechas, búsqueda, filtros, depósitos y pestaña activa — y,
     *  si hay filas seleccionadas, SOLO la selección (mismo dinamismo que
     *  buscar o agrupar). También alimentan la fila de totales del pie. */
    get tableKpis() {
        const sel = this.selectedRows;
        const base = sel.length ? sel : this.groupedRows;
        // Solo las filas PENDIENTES: las hechas tienen su card propia y las
        // canceladas no suman a ninguna
        const rows = base.filter(r => PENDING_STATES.includes(r.state));
        let pending = 0, available = 0, overdue = 0;
        for (const r of rows) {
            pending   += r.qty_pending   || 0;
            available += r.qty_available || 0;
            if (r.overdue_days !== null && r.overdue_days >= 0) overdue++;
        }
        return {
            pending:   Math.round(pending * 100) / 100,
            available: Math.round(available * 100) / 100,
            blocked:   Math.round((pending - available) * 100) / 100,
            pickings:  rows.length,
            overdue,
            pct_available: pending > 0 ? Math.round(available / pending * 1000) / 10 : null,
        };
    }

    /** KPIs de los VALIDADOS visibles (filas hechas de la tabla): dinámicos
     *  con fechas, búsqueda, filtros, pestaña y selección, como todos. */
    get validatedKpis() {
        const sel = this.selectedRows;
        const base = sel.length ? sel : this.groupedRows;
        const rows = base.filter(r => r.state === "done");
        let qty = 0;
        for (const r of rows) qty += r.qty_done || 0;
        return { qty: Math.round(qty * 100) / 100, pickings: rows.length };
    }

    // ── Paginación (mecánica compartida de los paneles) ───────────────────────

    get pagedRows()   { return pageSlice(this.sortedRows, this.state.page, this.state.pageSize); }
    get totalPages()  { return this.pager.totalPages; }
    get hasNextPage() { return this.pager.hasNext; }
    get hasPrevPage() { return this.pager.hasPrev; }
    nextPage() { this.pager.next(); }
    prevPage() { this.pager.prev(); }

    /** Title con la lista completa de artículos (para el sufijo "+N"). */
    productsTitle(row) {
        return (row.products_detail || []).map(p => p.name).join(", ");
    }

    // ── Selección (análisis + despacho masivo) ────────────────────────────────
    // Cualquier fila es seleccionable: la selección recalcula KPIs y totales.
    // El despacho masivo actúa solo sobre las seleccionadas ya validadas.

    toggleSelect(row)  { this.sel.toggle(row); }
    toggleSelectAll()  { this.sel.toggleAll(); }
    clearSelection()   { this.sel.clear(); }
    get allSelected()  { return this.sel.allSelected; }
    get selectedIds() {
        return Object.keys(this.state.selected).filter(k => this.state.selected[k]).map(Number);
    }
    /** Seleccionadas listas para despachar (validadas sin despachar). */
    get readySelectedIds() {
        return this.selectedRows.filter(r => r.stage === "ready").map(r => r.picking_id);
    }

    async markDispatched() {
        const ids = this.readySelectedIds;
        if (this.state.dispatching) return;
        if (!ids.length) {
            this.notification.add(
                "Ninguna de las filas seleccionadas está validada sin despachar.",
                { type: "warning" });
            return;
        }
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
        downloadCsv({
            filename: `salidas_pendientes_${toDateStr(new Date())}.csv`,
            headers:  cols.map(c => c.label),
            rows:     this.sortedRows,
            sep:      ";",
            bom:      true,
            quote:    "always",
            cell: r => cols.map(c => {
                if (c.key === "state") return this.rowStateLabel(r);
                if (c.key === "product_names" && r.products_detail && r.products_detail.length) {
                    return r.products_detail.map(p => p.name).join(", ");
                }
                return r[c.key];
            }),
        });
    }
}

registry.category("view_widgets").add("inventory_dashboard_widget", {
    component: InventoryDashboardWidget,
});
