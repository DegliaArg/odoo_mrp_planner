/** @odoo-module **/

/**
 * @widget UnmetDemandWidget
 * @description Análisis de demanda insatisfecha: de los pedidos confirmados en el
 * período, el backlog pendiente (pedido − entregado a la fecha) valuado a precio
 * unitario, agregado por una dimensión conmutable (cliente / producto / familia).
 * Muestra KPIs, un gráfico top-N y una tabla ordenable con filtros.
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

        const now = new Date();
        this.state = useState({
            loading:      true,
            loadError:    null,
            dateFrom:     toDateStr(new Date(now.getFullYear(), now.getMonth(), 1)),
            dateTo:       toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
            dimension:    "customer",
            amountMethod: "",          // "" = hereda de config; "pxq" | "real" override
            productSearch: "",
            numFilters:   [],
            sortCol:      "unmet_amount",
            sortDir:      "desc",
            page:         1,
            pageSize:     50,
            chartMetric:  "amount",    // "amount" | "qty"
            chartTopN:    20,
            data:         null,
        });

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                await this._load();
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
        onPatched(() => {
            if (!this.state.loading && this.chartRef.el && this.pagedRowsAll.length) {
                this._drawChart();
            }
        });
        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
        });
    }

    // ── Carga ─────────────────────────────────────────────────────────────────
    async _load() {
        this.state.loading   = true;
        this.state.loadError = null;
        this.state.page      = 1;
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_unmet_demand_data",
                [this.state.dateFrom, this.state.dateTo, this.state.dimension,
                 [], this.state.amountMethod || null],
            );
            this.state.data = d;
        } catch (e) {
            console.error("[UnmetDemandWidget]", e);
            this.state.data      = null;
            this.state.loadError = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Controles ───────────────────────────────────────────────────────────────
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
    setDimension(d)   {
        if (this.state.dimension === d) return;
        this.state.dimension = d;
        // Reiniciar el orden por si estaba en una columna exclusiva de producto.
        this.state.sortCol = "unmet_amount";
        this.state.sortDir = "desc";
        this._load();
    }
    setAmountMethod(m){ if (this.state.amountMethod !== m) { this.state.amountMethod = m; this._load(); } }
    setChartMetric(m) { if (this.state.chartMetric !== m)  { this.state.chartMetric = m; } }
    setChartTopN(n)   { if (this.state.chartTopN !== n)    { this.state.chartTopN = n; } }

    /** Drill de las cards: abre la lista de líneas del período (pendientes o todas). */
    async openCardLines(onlyPending) {
        try {
            const action = await this.orm.call(
                "mrp.planner.dashboard", "action_open_unmet_lines",
                [this.state.dateFrom, this.state.dateTo, [], onlyPending],
            );
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

    // ── Config activa ───────────────────────────────────────────────────────────
    get effAmountMethod() {
        return this.state.amountMethod
            || (this.state.data && this.state.data.config && this.state.data.config.amount_method)
            || "pxq";
    }
    get dimensionLabel() { return DIM_LABELS[this.state.dimension] || "Entidad"; }
    get dimensionPlural(){ return DIM_PLURALS[this.state.dimension] || "Filas"; }
    get crossLabel()     { return this.state.dimension === "product" ? "# Clientes" : "# Productos"; }

    get columns() {
        const cols = [
            { key: "name",            label: this.dimensionLabel, align: "start" },
            { key: "qty_ordered",     label: "Pedido",           align: "end", kind: "num"   },
            { key: "qty_delivered",   label: "Entregado",        align: "end", kind: "num"   },
            { key: "unmet_qty",       label: "Pendiente",        align: "end", kind: "num"   },
            { key: "unmet_amount",    label: "Monto pendiente",  align: "end", kind: "money" },
            { key: "fulfillment_pct", label: "% Cumplim.",       align: "end", kind: "pct"   },
            { key: "unmet_pct",       label: "% Insatisf.",      align: "end", kind: "pct"   },
            { key: "backlog_age",     label: "Días backlog",     align: "end", kind: "days"  },
        ];
        // Cruce con quiebre de stock: solo tiene sentido por producto.
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
    get numColOptions() {
        return this.columns.filter(c => c.kind && c.kind !== "chip").map(c => ({ key: c.key, label: c.label }));
    }

    // ── Filas / KPIs ─────────────────────────────────────────────────────────────
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

    /** Filas filtradas y ordenadas (todas, sin paginar) — usadas por chart y export. */
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

    // ── Gráfico ───────────────────────────────────────────────────────────────
    _drawChart() {
        const canvas = this.chartRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._chart) { this._chart.destroy(); this._chart = null; }

        const isAmt  = this.state.chartMetric === "amount";
        const field  = isAmt ? "unmet_amount" : "unmet_qty";
        const rows   = [...this.pagedRowsAll]
            .sort((a, b) => (b[field] || 0) - (a[field] || 0))
            .slice(0, this.state.chartTopN);
        const labels = rows.map(r => r.name.length > 22 ? r.name.slice(0, 20) + "…" : r.name);
        const data   = rows.map(r => r[field]);
        // Color por severidad de insatisfacción (más rojo = mayor % insatisfecho).
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
    /** Verde/amarillo/rojo según el % de cumplimiento (más alto = mejor). */
    fulfillClass(pct) {
        if (pct === null || pct === undefined) return "";
        if (pct >= 90) return "text-success";
        if (pct >= 70) return "text-warning";
        return "text-danger";
    }
    /** Severidad de la insatisfacción (más alto = peor). */
    unmetSeverityClass(pct) {
        if (pct === null || pct === undefined) return "";
        if (pct >= 50) return "text-danger fw-semibold";
        if (pct >= 20) return "text-warning";
        return "text-muted";
    }

    // ── Tooltips (mismo formato que los demás paneles) ──────────────────────────
    /** Nota de valorización, se anexa a los tooltips de monto. */
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
            qty_ordered:     "Unidades pedidas en el período (suma de las líneas).",
            qty_delivered:   "Unidades entregadas a la fecha de los pedidos del período (cualquier fecha de entrega).",
            unmet_qty:       "Backlog pendiente: pedido − entregado (suma por línea, solo faltantes).",
            unmet_amount:    "Monto del backlog pendiente: cantidad pendiente × precio unitario.",
            fulfillment_pct: "Tasa de cumplimiento: entregado ÷ pedido × 100.",
            unmet_pct:       "Insatisfacción: pendiente ÷ pedido × 100. Cuánto de lo pedido quedó sin entregar.",
            backlog_age:     "Antigüedad del backlog: días desde el pedido, ponderada por la cantidad pendiente. El tooltip muestra el promedio y el más viejo.",
            break_days:      "Días en quiebre: hace cuántos días el stock está bajo el mínimo (solo productos en quiebre con mínimo configurado). '—' = sin quiebre.",
            diagnosis:       "Diagnóstico del cruce quiebre × backlog: Crónico (sin stock + viejo) · Sin stock (quiebre reciente) · Fulfillment (hay stock pero no entregás) · OK.",
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
            case "backlog_age":
                return `${row.name}\nAntigüedad del backlog (ponderada por cantidad)\nPromedio: ${f(row.backlog_age)} d — cuánto esperó la unidad pendiente promedio\nMás viejo: ${f(row.backlog_age_oldest)} d`;
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
                if (v === null || v === undefined) return "";
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
