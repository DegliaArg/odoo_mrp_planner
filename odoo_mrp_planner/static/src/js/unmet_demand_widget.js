/** @odoo-module **/

/**
 * @widget UnmetDemandWidget
 * @description Análisis de demanda insatisfecha: de los pedidos confirmados en el
 * período, el backlog pendiente (pedido − entregado a la fecha) valuado a precio
 * unitario, agregado por una dimensión conmutable (cliente / producto / familia).
 *
 * Tiene DOS conjuntos de filtros independientes (período · dimensión · PxQ/Real):
 *   - los de arriba afectan SOLO al gráfico (dataset chartData);
 *   - los de la segunda línea afectan las cards globales + la tabla (dataset data).
 * La tabla incluye un selector de columnas para armarla a gusto.
 *
 * RPC:
 *   - get_unmet_demand_data(periodFrom, periodTo, dimension, warehouseIds, amountMethod)
 *       → { rows, kpis, config, dimension }
 *
 * Props:
 *   - record: Object (opcional) — registro del dashboard (infra de widgets)
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { PlannerSearchBar } from "./planner_search_bar";
import { applyNumericFilters } from "./planner_table";
import { downloadExcelXml } from "./planner_export";
import { kpiNumClass } from "./forecast_formatters";

const DIM_LABELS  = { customer: "Cliente", product: "Producto", family: "Familia" };
const DIM_PLURALS = { customer: "Clientes", product: "Productos", family: "Familias" };

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class UnmetDemandWidget extends Component {
    static template = "odoo_mrp_planner.UnmetDemandWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm      = useService("orm");
        this.action   = useService("action");
        this.chartRef = useRef("chartCanvas");
        this._chart   = null;

        const now   = new Date();
        const first = toDateStr(new Date(now.getFullYear(), now.getMonth(), 1));
        const last  = toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));

        this.state = useState({
            // ── Gráfico (filtros de arriba, independientes) ──
            chartLoading:      true,
            chartError:        null,
            chartDateFrom:     first,
            chartDateTo:       last,
            chartDimension:    "customer",
            chartAmountMethod: "",
            chartData:         null,
            chartMetric:       "amount",   // "amount" | "qty"
            chartTopN:         20,

            // ── Cards globales + tabla (segunda línea de filtros) ──
            loading:      true,
            loadError:    null,
            dateFrom:     first,
            dateTo:       last,
            dimension:    "customer",
            amountMethod: "",
            data:         null,
            productSearch: "",
            numFilters:   [],
            sortCol:      "unmet_amount",
            sortDir:      "desc",
            page:         1,
            pageSize:     50,
            colsVisible:      {},          // {key: false} = oculta; ausente/true = visible
            colsDropdownOpen: false,
        });

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                await Promise.all([this._load(), this._loadChart()]);
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
        onPatched(() => {
            if (!this.state.chartLoading && this.chartRef.el && this.chartRowsAll.length) {
                this._drawChart();
            }
        });
        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
        });
    }

    // ── Carga: tabla + cards ────────────────────────────────────────────────────
    async _load() {
        this.state.loading   = true;
        this.state.loadError = null;
        this.state.page      = 1;
        try {
            this.state.data = await this.orm.call(
                "mrp.planner.dashboard", "get_unmet_demand_data",
                [this.state.dateFrom, this.state.dateTo, this.state.dimension,
                 [], this.state.amountMethod || null]);
        } catch (e) {
            console.error("[UnmetDemandWidget] table", e);
            this.state.data      = null;
            this.state.loadError = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Carga: gráfico (dataset propio) ─────────────────────────────────────────
    async _loadChart() {
        this.state.chartLoading = true;
        this.state.chartError   = null;
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        try {
            this.state.chartData = await this.orm.call(
                "mrp.planner.dashboard", "get_unmet_demand_data",
                [this.state.chartDateFrom, this.state.chartDateTo, this.state.chartDimension,
                 [], this.state.chartAmountMethod || null]);
        } catch (e) {
            console.error("[UnmetDemandWidget] chart", e);
            this.state.chartData  = null;
            this.state.chartError = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.chartLoading = false;
        }
    }

    // ── Controles del gráfico ───────────────────────────────────────────────────
    onChartDateFromChange(ev) {
        this.state.chartDateFrom = ev.target.value;
        if (this.state.chartDateFrom > this.state.chartDateTo) this.state.chartDateTo = this.state.chartDateFrom;
        this._loadChart();
    }
    onChartDateToChange(ev) {
        this.state.chartDateTo = ev.target.value;
        if (this.state.chartDateTo < this.state.chartDateFrom) this.state.chartDateFrom = this.state.chartDateTo;
        this._loadChart();
    }
    setChartDimension(d)    { if (this.state.chartDimension !== d)    { this.state.chartDimension = d; this._loadChart(); } }
    setChartAmountMethod(m) { if (this.state.chartAmountMethod !== m) { this.state.chartAmountMethod = m; this._loadChart(); } }
    setChartMetric(m)       { if (this.state.chartMetric !== m)       { this.state.chartMetric = m; } }
    setChartTopN(n)         { if (this.state.chartTopN !== n)         { this.state.chartTopN = n; } }

    // ── Controles de cards + tabla ──────────────────────────────────────────────
    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) this.state.dateTo = this.state.dateFrom;
        this._load();
    }
    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) this.state.dateFrom = this.state.dateTo;
        this._load();
    }
    setDimension(d) {
        if (this.state.dimension === d) return;
        this.state.dimension = d;
        this.state.sortCol = "unmet_amount";
        this.state.sortDir = "desc";
        this._load();
    }
    setAmountMethod(m) { if (this.state.amountMethod !== m) { this.state.amountMethod = m; this._load(); } }

    /** Drill de las cards: abre la lista de líneas del período (pendientes o todas). */
    async openCardLines(onlyPending) {
        try {
            const action = await this.orm.call(
                "mrp.planner.dashboard", "action_open_unmet_lines",
                [this.state.dateFrom, this.state.dateTo, [], onlyPending]);
            this.action.doAction(action);
        } catch (e) {
            console.error("[UnmetDemandWidget] drill", e);
        }
    }
    setSearch(text)   { this.state.productSearch = text; this.state.page = 1; }
    addNumFilter(c)   { this.state.numFilters = [...this.state.numFilters, c]; this.state.page = 1; }
    removeNumFilter(i){ this.state.numFilters = this.state.numFilters.filter((_, idx) => idx !== i); this.state.page = 1; }
    setSort(key) {
        if (this.state.sortCol === key) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortCol = key;
            this.state.sortDir = key === "name" ? "asc" : "desc";
        }
        this.state.page = 1;
    }

    // ── Selector de columnas ────────────────────────────────────────────────────
    toggleColsDropdown(ev) {
        if (ev) ev.stopPropagation();
        this.state.colsDropdownOpen = !this.state.colsDropdownOpen;
    }
    toggleCol(key) {
        const cur = this.state.colsVisible[key];
        this.state.colsVisible = { ...this.state.colsVisible, [key]: cur === false ? true : false };
    }

    // ── Config activa ───────────────────────────────────────────────────────────
    _effMethod(stateMethod, dataset) {
        return stateMethod || (dataset && dataset.config && dataset.config.amount_method) || "pxq";
    }
    get effAmountMethod()      { return this._effMethod(this.state.amountMethod, this.state.data); }
    get effChartAmountMethod() { return this._effMethod(this.state.chartAmountMethod, this.state.chartData); }

    get dimensionLabel()      { return DIM_LABELS[this.state.dimension] || "Entidad"; }
    get dimensionPlural()     { return DIM_PLURALS[this.state.dimension] || "Filas"; }
    get chartDimensionLabel() { return DIM_LABELS[this.state.chartDimension] || "Entidad"; }
    get crossLabel()          { return this.state.dimension === "product" ? "# Clientes" : "# Productos"; }
    get categoryLabel()       { return this.state.dimension === "product" ? "Cat. venta" : "Categoría"; }

    /** Todas las columnas aplicables a la dimensión activa de la TABLA. */
    get allColumns() {
        const cols = [
            { key: "name", label: this.dimensionLabel, align: "start", fixed: true },
        ];
        if (this.state.dimension !== "family") {
            cols.push({ key: "category", label: this.categoryLabel, align: "center", kind: "cat" });
        }
        cols.push(
            { key: "qty_ordered",     label: "Pedido",           align: "end", kind: "num"   },
            { key: "qty_delivered",   label: "Entregado",        align: "end", kind: "num"   },
            { key: "unmet_qty",       label: "Pendiente",        align: "end", kind: "num"   },
            { key: "unmet_amount",    label: "Monto pendiente",  align: "end", kind: "money" },
            { key: "fulfillment_pct", label: "% Cumplim.",       align: "end", kind: "pct"   },
            { key: "unmet_pct",       label: "% Insatisf.",      align: "end", kind: "pct"   },
            { key: "pending_age",     label: "Antig. pendiente", align: "end", kind: "days"  },
        );
        if (this.state.dimension === "product") {
            cols.push(
                { key: "break_days", label: "Días quiebre", align: "end",    kind: "days" },
                { key: "diagnosis",  label: "Diagnóstico",  align: "center", kind: "chip" },
            );
        }
        cols.push(
            { key: "affected_orders", label: "# Pedidos",     align: "end", kind: "num" },
            { key: "cross_count",     label: this.crossLabel, align: "end", kind: "num" },
        );
        return cols;
    }
    /** Columnas visibles (fijas + las no ocultadas por el selector). */
    get columns() {
        return this.allColumns.filter(c => c.fixed || this.state.colsVisible[c.key] !== false);
    }
    /** Columnas opcionales (para el dropdown del selector). */
    get optionalColumns() { return this.allColumns.filter(c => !c.fixed); }

    get numColOptions() {
        return this.columns
            .filter(c => c.kind && c.kind !== "chip" && c.kind !== "cat")
            .map(c => ({ key: c.key, label: c.label }));
    }

    // ── Filas / KPIs (dataset de la tabla) ──────────────────────────────────────
    get baseRows() { return (this.state.data && this.state.data.rows) || []; }

    /** Filas tras búsqueda + filtros numéricos (sin ordenar ni paginar). */
    get filteredRows() {
        let rows = this.baseRows;
        const q = this.state.productSearch.toLowerCase();
        if (q) rows = rows.filter(r => (r.name || "").toLowerCase().includes(q));
        return applyNumericFilters(rows, this.state.numFilters, (r, k) => {
            const v = r[k];
            return (v === null || v === undefined) ? null : v;
        });
    }

    /** Filas filtradas y ordenadas (todas, sin paginar). */
    get pagedRowsAll() {
        const rows = [...this.filteredRows];
        const col  = this.state.sortCol;
        const dir  = this.state.sortDir === "asc" ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === "string") {
                if (!va && vb) return dir;
                if (va && !vb) return -dir;
                return dir * va.localeCompare(vb, "es", { sensitivity: "base" });
            }
            va = va ?? -Infinity; vb = vb ?? -Infinity;
            return dir * (va - vb);
        });
        return rows;
    }
    get pagedRows() {
        const start = (this.state.page - 1) * this.state.pageSize;
        return this.pagedRowsAll.slice(start, start + this.state.pageSize);
    }
    get totalPages()  { return Math.max(1, Math.ceil(this.pagedRowsAll.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }

    /** KPIs recalculados sobre las filas filtradas (consistentes con la tabla). */
    get kpis() {
        const rows = this.filteredRows;
        const sum = k => rows.reduce((s, r) => s + (r[k] || 0), 0);
        const ordered   = sum("qty_ordered");
        const delivered = sum("qty_delivered");
        return {
            total_unmet_amount: Math.round(sum("unmet_amount") * 100) / 100,
            total_unmet_qty:    Math.round(sum("unmet_qty") * 10) / 10,
            total_ordered:      Math.round(ordered * 10) / 10,
            total_delivered:    Math.round(delivered * 10) / 10,
            fulfillment_pct:    ordered > 0 ? Math.round(delivered / ordered * 1000) / 10 : null,
            total_rows:         rows.length,
        };
    }

    // ── Gráfico (dataset propio) ────────────────────────────────────────────────
    get chartRowsAll() { return (this.state.chartData && this.state.chartData.rows) || []; }

    _drawChart() {
        const canvas = this.chartRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._chart) { this._chart.destroy(); this._chart = null; }

        const isAmt  = this.state.chartMetric === "amount";
        const field  = isAmt ? "unmet_amount" : "unmet_qty";
        const rows   = [...this.chartRowsAll]
            .sort((a, b) => (b[field] || 0) - (a[field] || 0))
            .slice(0, this.state.chartTopN);
        const labels = rows.map(r => r.name.length > 22 ? r.name.slice(0, 20) + "…" : r.name);
        const data   = rows.map(r => r[field]);
        const colors = rows.map(r => {
            const p = r.unmet_pct || 0;
            if (p >= 50) return "rgba(220, 53, 69, 0.85)";
            if (p >= 20) return "rgba(255, 193, 7, 0.85)";
            return "rgba(13, 110, 253, 0.80)";
        });
        const fmt = isAmt
            ? v => "$ " + new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(v)
            : v => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v) + " u.";

        this._chart = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: isAmt ? "Monto pendiente" : "Pendiente (u.)",
                    data, backgroundColor: colors, borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => rows[items[0].dataIndex].name,
                            label: ctx => fmt(ctx.raw),
                            afterLabel: ctx => {
                                const r = rows[ctx.dataIndex];
                                return `Insatisf.: ${r.unmet_pct != null ? r.unmet_pct + "%" : "—"}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 45 } },
                    y: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.06)" }, ticks: { font: { size: 10 } } },
                },
            },
        });
    }

    // ── Formateo ────────────────────────────────────────────────────────────────
    fmt(n)      { return (n === null || n === undefined) ? "—" : new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(n); }
    fmtMoney(n) { return (n === null || n === undefined) ? "—" : "$ " + new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(n); }
    fmtPct(n)   { return (n === null || n === undefined) ? "—" : new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(n) + "%"; }
    kpiNumClass(text) { return kpiNumClass(text); }
    cellText(row, col) {
        if (col.kind === "money") return this.fmtMoney(row[col.key]);
        if (col.kind === "pct")   return this.fmtPct(row[col.key]);
        if (col.kind === "days")  {
            const v = row[col.key];
            return (v === null || v === undefined) ? "—" : this.fmt(v) + " d";
        }
        if (col.kind === "num")   return this.fmt(row[col.key]);
        return row[col.key];
    }

    /** Color del badge de categoría A–E (misma paleta que el análisis de clientes). */
    catColor(name) {
        const map = { A: "#198754", B: "#0d6efd", C: "#ffc107", D: "#6c757d", E: "#c8d2dc" };
        return map[name] || "#6c757d";
    }

    /** Etiqueta + clase del chip de diagnóstico (solo productos). */
    diagnosisChip(row) {
        const map = {
            chronic:     { label: "Crónico",     cls: "bg-danger text-white" },
            supply:      { label: "Sin stock",   cls: "bg-warning text-dark" },
            fulfillment: { label: "Fulfillment", cls: "bg-info text-dark" },
            ok:          { label: "OK",          cls: "bg-light text-muted border" },
        };
        return map[row.diagnosis] || map.ok;
    }
    diagnosisTooltip(diag) {
        return {
            chronic:     "Crónico: en quiebre de stock y con backlog viejo. Venís fallando hace rato por falta de stock → reponer/fabricar es prioridad.",
            supply:      "Sin stock: en quiebre pero el backlog es reciente. Problema de abastecimiento; al reponer se limpia.",
            fulfillment: "Fulfillment: NO estás en quiebre (hay stock o no bajás del mínimo) y el backlog igual es viejo. El problema no es de stock: mirá asignación / logística / compromiso.",
            ok:          "OK: sin quiebre y backlog reciente. Situación transitoria o normal.",
        }[diag] || "";
    }
    sortIcon(key) {
        if (this.state.sortCol !== key) return "fa fa-sort ms-1 text-muted";
        return this.state.sortDir === "asc" ? "fa fa-sort-asc ms-1" : "fa fa-sort-desc ms-1";
    }

    // ── Semáforos ─────────────────────────────────────────────────────────────
    fulfillClass(pct) {
        if (pct === null || pct === undefined) return "";
        if (pct >= 90) return "text-success";
        if (pct >= 70) return "text-warning";
        return "text-danger";
    }
    unmetSeverityClass(pct) {
        if (pct === null || pct === undefined) return "";
        if (pct >= 50) return "text-danger fw-semibold";
        if (pct >= 20) return "text-warning";
        return "text-muted";
    }

    // ── Tooltips (mismo formato que los demás paneles) ──────────────────────────
    amountNote() {
        const m = this.effAmountMethod === "real"
            ? "Real (precio efectivo con descuentos)"
            : "PxQ (precio de lista × cantidad)";
        return `\nValorización: ${m}`;
    }

    kpiTooltip(key) {
        const k = this.kpis;
        const m = v => this.fmtMoney(v);
        const f = v => this.fmt(v);
        const p = v => this.fmtPct(v);
        const dp = this.dimensionPlural.toLowerCase();
        switch (key) {
            case "total_unmet_amount":
                return `Monto de la demanda insatisfecha del período\nCantidad pendiente × precio unitario\n→ ${m(k.total_unmet_amount)}` + this.amountNote();
            case "total_unmet_qty":
                return `Unidades pedidas en el período aún sin entregar\nΣ(pedido − entregado) por línea, solo faltantes\n→ ${f(k.total_unmet_qty)} u.`;
            case "fulfillment_pct":
                return `Tasa de cumplimiento de ${dp} con faltante\nEntregado ÷ Pedido × 100\n→ ${f(k.total_delivered)} ÷ ${f(k.total_ordered)} = ${p(k.fulfillment_pct)}`;
            case "total_ordered":
                return `Unidades pedidas de ${dp} con demanda insatisfecha en el período\n→ ${f(k.total_ordered)} u.`;
            case "total_delivered":
                return `Unidades entregadas (a la fecha) de ${dp} con demanda insatisfecha\n→ ${f(k.total_delivered)} u.`;
            case "total_rows":
                return `${this.dimensionPlural} con al menos una unidad pendiente en el período\n→ ${f(k.total_rows)}`;
            default:
                return "";
        }
    }

    colTitle(col) {
        const crossTip = this.state.dimension === "product"
            ? "Clientes distintos con faltante de este producto."
            : "Productos distintos con faltante.";
        const base = {
            name:            `${this.dimensionLabel}. Clic para ordenar.`,
            category:        this.state.dimension === "product"
                ? "Categoría de venta A–E del producto (x_sale_category)."
                : "Categoría del cliente A–E. Con clientes unificados por casa matriz, la de la matriz.",
            qty_ordered:     "Unidades pedidas en el período (suma de las líneas).",
            qty_delivered:   "Unidades entregadas a la fecha de los pedidos del período (cualquier fecha de entrega).",
            unmet_qty:       "Backlog pendiente: pedido − entregado (suma por línea, solo faltantes).",
            unmet_amount:    "Monto del backlog pendiente: cantidad pendiente × precio unitario.",
            fulfillment_pct: "Tasa de cumplimiento: entregado ÷ pedido × 100.",
            unmet_pct:       "Insatisfacción: pendiente ÷ pedido × 100. Cuánto de lo pedido quedó sin entregar.",
            pending_age:     "Antigüedad del pendiente: días que lleva esperando lo que no se entregó. El método (ponderado por cantidad o pedido más antiguo) se elige en Ajustes. El tooltip muestra ambos.",
            break_days:      "Días en quiebre: hace cuántos días el stock está bajo el mínimo (solo productos en quiebre con mínimo configurado). '—' = sin quiebre.",
            diagnosis:       "Diagnóstico del cruce quiebre × antigüedad del pendiente: Crónico (sin stock + viejo) · Sin stock (quiebre reciente) · Fulfillment (hay stock pero no entregás) · OK.",
            affected_orders: "Pedidos distintos del período con al menos una unidad pendiente.",
            cross_count:     crossTip,
        }[col.key] || "";
        if (col.key === "unmet_amount") return base + this.amountNote();
        return base;
    }

    cellTooltip(col, row) {
        const m = v => this.fmtMoney(v);
        const f = v => this.fmt(v);
        const p = v => this.fmtPct(v);
        switch (col.key) {
            case "name":
                return row.name;
            case "unmet_qty":
                return `${row.name}\nPedido − entregado\n→ ${f(row.qty_ordered)} − ${f(row.qty_delivered)} = ${f(row.unmet_qty)} u.`;
            case "unmet_amount":
                return `${row.name}\nPendiente × precio unitario\n→ ${f(row.unmet_qty)} u. = ${m(row.unmet_amount)}` + this.amountNote();
            case "fulfillment_pct":
                return `${row.name}\nEntregado ÷ Pedido × 100\n→ ${f(row.qty_delivered)} ÷ ${f(row.qty_ordered)} = ${p(row.fulfillment_pct)}`;
            case "unmet_pct":
                return `${row.name}\nPendiente ÷ Pedido × 100\n→ ${f(row.unmet_qty)} ÷ ${f(row.qty_ordered)} = ${p(row.unmet_pct)}`;
            case "affected_orders":
                return `${row.name}\n${f(row.affected_orders)} pedido(s) del período con faltante`;
            case "cross_count":
                return `${row.name}\n${f(row.cross_count)} ${this.state.dimension === "product" ? "cliente(s)" : "producto(s)"} con faltante`;
            case "pending_age":
                return `${row.name}\nAntigüedad del pendiente (días que lleva esperando lo no entregado)\nPonderada por cantidad: ${f(row.pending_age_weighted)} d — la unidad pendiente promedio\nPedido más antiguo: ${f(row.pending_age_oldest)} d`;
            case "break_days":
                return row.break_days == null
                    ? `${row.name}\nSin quiebre de stock (no está bajo el mínimo, o no tiene mínimo configurado)`
                    : `${row.name}\nDías bajo el punto de reorden (mínimo)\n→ ${f(row.break_days)} d en quiebre`;
            case "diagnosis":
                return `${row.name}\n${this.diagnosisTooltip(row.diagnosis)}`;
            default:
                return `${row.name}\n${this.cellText(row, col)}`;
        }
    }

    // ── Export ──────────────────────────────────────────────────────────────────
    exportToExcel() {
        const cols = this.columns;
        downloadExcelXml({
            filename: `demanda_insatisfecha_${this.state.dateFrom}_${this.state.dateTo}.xls`,
            sheet:    "Demanda insatisfecha",
            headers:  cols.map(c => c.label),
            rows:     this.pagedRowsAll,
            cell:     row => cols.map(c => {
                if (c.kind === "chip") return this.diagnosisChip(row).label;
                const v = row[c.key];
                if (v === null || v === undefined || v === "") return "";
                if (c.kind === "pct")  return v + "%";
                if (c.kind === "days") return v + " d";
                return v;
            }),
        });
    }
}

registry.category("view_widgets").add("unmet_demand_widget", {
    component: UnmetDemandWidget,
});
