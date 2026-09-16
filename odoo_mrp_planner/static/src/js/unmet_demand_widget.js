/** @odoo-module **/

/**
 * @widget UnmetDemandWidget
 * @description Análisis de demanda insatisfecha: de los pedidos confirmados en el
 * período, el backlog pendiente (pedido − entregado a la fecha) valuado a precio
 * unitario, agregado por una dimensión conmutable (cliente / producto / familia).
 *
 * Tiene DOS conjuntos de filtros independientes (período · dimensión · PxQ/Real):
 *   - los de arriba afectan SOLO al gráfico (dataset chartData);
 *   - los de la segunda línea afectan el dataset de la tabla (dataset data).
 * Las cards (Demanda real / Cumplimiento de demanda / Pendiente) son totales
 * FIJOS del período que llegan del backend en `data.kpis`: cierran entre sí
 * (Demanda real = Cumplimiento + Pendiente) y no dependen de la dimensión ni de
 * los filtros de la tabla — la dimensión y los filtros solo desagregan el detalle.
 * La tabla incluye un selector de columnas para armarla a gusto.
 *
 * RPC:
 *   - get_unmet_demand_data(periodFrom, periodTo, dimension, warehouseIds, amountMethod)
 *       → { rows, kpis, config, dimension }
 *
 * Props:
 *   - record: Object (opcional) — registro del dashboard (infra de widgets)
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { PlannerSearchBar } from "./planner_search_bar";
import { applyNumericFilters } from "./planner_table";
import { downloadExcelXml } from "./planner_export";
import { kpiNumClass } from "./forecast_formatters";
import { useColManager } from "./column_manager";

const DIM_LABELS  = { customer: "Cliente", product: "Producto", family: "Familia" };
const DIM_PLURALS = { customer: "Clientes", product: "Productos", family: "Familias" };

// Todas las columnas posibles de la tabla (unión de las tres dimensiones). El
// column manager gestiona el ORDEN (drag & drop) y el ancho (resize) sobre este
// conjunto fijo; el getter `columns` filtra por dimensión activa y visibilidad.
// Las etiquetas de name/category/cross_count se sobrescriben dinámicamente.
const UD_ALL_COLS = [
    { key: "name",            label: "Entidad",          width: 160, align: "start",  sortKey: "name",            fixed: true },
    { key: "category",        label: "Categoría",        width: 80,  align: "center", sortKey: "category",        kind: "cat"   },
    { key: "qty_ordered",     label: "Pedido",           width: 90,  align: "end",    sortKey: "qty_ordered",     kind: "num"   },
    { key: "qty_delivered",   label: "Entregado",        width: 90,  align: "end",    sortKey: "qty_delivered",   kind: "num"   },
    { key: "unmet_qty",       label: "Pendiente",        width: 90,  align: "end",    sortKey: "unmet_qty",       kind: "num"   },
    { key: "unmet_amount",    label: "Monto pendiente",  width: 120, align: "end",    sortKey: "unmet_amount",    kind: "money" },
    { key: "fulfillment_pct", label: "% Cumplim.",       width: 90,  align: "end",    sortKey: "fulfillment_pct", kind: "pct"   },
    { key: "unmet_pct",       label: "% Insatisf.",      width: 90,  align: "end",    sortKey: "unmet_pct",       kind: "pct"   },
    { key: "pending_age",     label: "Antig. pendiente", width: 110, align: "end",    sortKey: "pending_age",     kind: "days"  },
    { key: "break_days",      label: "Días quiebre",     width: 95,  align: "end",    sortKey: "break_days",      kind: "days", defaultHidden: true },
    { key: "diagnosis",       label: "Situación",        width: 230, align: "start",  sortKey: "diagnosis",       kind: "situation" },
    { key: "affected_orders", label: "# Pedidos",        width: 80,  align: "end",    sortKey: "affected_orders", kind: "num",  defaultHidden: true },
    { key: "cross_count",     label: "# Cruce",          width: 90,  align: "end",    sortKey: "cross_count",     kind: "num",  defaultHidden: true },
];

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── Persistencia de filtros (localStorage) ─────────────────────────────────────
// Se guardan los filtros del gráfico y de la tabla/cards para que sobrevivan al
// recargar el panel. La búsqueda de texto, los filtros numéricos y la paginación
// son transitorios y NO se persisten.
const FILTERS_KEY = "_planner_unmet_filters_v1";
const PERSIST_KEYS = [
    "chartDateFrom", "chartDateTo", "chartDimension", "chartAmountMethod",
    "chartMetric", "chartTopN",
    "dateFrom", "dateTo", "dimension", "amountMethod",
    "sortCol", "sortDir", "pageSize", "colsVisible", "showAll",
];
function loadFilters() {
    try {
        const raw = localStorage.getItem(FILTERS_KEY);
        const s = raw ? JSON.parse(raw) : null;
        return (s && typeof s === "object") ? s : {};
    } catch (e) { return {}; }
}
function saveFilters(state) {
    try {
        const data = {};
        for (const k of PERSIST_KEYS) data[k] = state[k];
        localStorage.setItem(FILTERS_KEY, JSON.stringify(data));
    } catch (e) { /* storage lleno o no disponible: ignorar */ }
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
        this._chartDrawn = null;   // {data, metric, topN} del último dibujo; evita redibujar en patches ajenos al gráfico
        this.cols     = useColManager("unmet_demand", UD_ALL_COLS);

        const now   = new Date();
        const first = toDateStr(new Date(now.getFullYear(), now.getMonth(), 1));
        const last  = toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));

        // Filtros persistidos (localStorage): pisan los defaults si existen.
        const saved = loadFilters();
        const pick = (k, dflt) => (saved[k] !== undefined && saved[k] !== null) ? saved[k] : dflt;

        this.state = useState({
            // ── Gráfico (filtros de arriba, independientes) ──
            chartLoading:      true,
            chartError:        null,
            chartDateFrom:     pick("chartDateFrom", first),
            chartDateTo:       pick("chartDateTo", last),
            chartDimension:    pick("chartDimension", "customer"),
            chartAmountMethod: pick("chartAmountMethod", ""),
            chartData:         null,
            chartMetric:       pick("chartMetric", "amount"),   // "amount" | "qty"
            chartTopN:         pick("chartTopN", 20),

            // ── Cards globales + tabla (segunda línea de filtros) ──
            loading:      true,
            loadError:    null,
            dateFrom:     pick("dateFrom", first),
            dateTo:       pick("dateTo", last),
            dimension:    pick("dimension", "customer"),
            amountMethod: pick("amountMethod", ""),
            data:         null,
            productSearch: "",
            numFilters:   [],
            sortCol:      pick("sortCol", "unmet_amount"),
            sortDir:      pick("sortDir", "desc"),
            page:         1,
            pageSize:     pick("pageSize", 50),
            showAll:      pick("showAll", false),   // toggle: todas las entidades vs solo con faltante
            expandedKey:  null,                     // fila expandida (análisis de entregabilidad, solo producto)
            expandData:   {},                       // cache {product_id: análisis} del expand
            expandLoading: false,
            colsVisible:      pick("colsVisible", {}),   // {key: false} = oculta; ausente/true = visible
            colsDropdownOpen: false,
        });

        // Persistir los filtros cada vez que cambia alguno de los relevantes.
        useEffect(
            () => { saveFilters(this.state); },
            () => PERSIST_KEYS.map(k => {
                const v = this.state[k];
                return (v && typeof v === "object") ? JSON.stringify(v) : v;
            }),
        );

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                await Promise.all([this._load(), this._loadChart()]);
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });
        onPatched(() => {
            if (this.state.chartLoading || !this.chartRef.el || !this.chartRowsAll.length) return;
            // Solo redibujar si cambió algo que afecta al gráfico (dataset, métrica o Top N).
            // Los patches por filtros/búsqueda/orden/paginación de la tabla se ignoran.
            const d = this._chartDrawn;
            if (d && this._chart
                && d.data === this.state.chartData
                && d.metric === this.state.chartMetric
                && d.topN === this.state.chartTopN) return;
            this._chartDrawn = {
                data:   this.state.chartData,
                metric: this.state.chartMetric,
                topN:   this.state.chartTopN,
            };
            this._drawChart();
        });
        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
            this.cols.cancelResize();
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
                 [], this.state.amountMethod || null, this.state.showAll]);
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
    /** Toggle tabla: mostrar todas las entidades del período (footer cuadra con las
     *  cards) o solo las que tienen faltante (defecto, foco en lo insatisfecho). */
    toggleShowAll() { this.state.showAll = !this.state.showAll; this._load(); }

    /** Drill de las cards: abre la lista de líneas del período enfocada según la
     *  card (focus = 'ordered' | 'delivered' | 'pending' | 'value' | 'fulfillment').
     *  Con groupByDimension=true, agrupa por la dimensión activa (card de afectados). */
    async openCardLines(focus, groupByDimension = false) {
        try {
            const action = await this.orm.call(
                "mrp.planner.dashboard", "action_open_unmet_lines",
                [this.state.dateFrom, this.state.dateTo, [], focus,
                 groupByDimension ? this.state.dimension : null]);
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
    /** Visibilidad efectiva de una columna opcional: el usuario manda (true/false
     *  explícito guardado); si no la tocó, visible salvo que sea defaultHidden. */
    isColVisible(key) {
        const v = this.state.colsVisible[key];
        if (v === false) return false;
        if (v === true)  return true;
        const col = this.cols.colMap[key];
        return !(col && col.defaultHidden);
    }
    toggleCol(key) {
        this.state.colsVisible = { ...this.state.colsVisible, [key]: !this.isColVisible(key) };
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

    /** ¿La columna aplica a la dimensión activa de la tabla? */
    _colApplies(key) {
        if (key === "category") return this.state.dimension !== "family";
        if (key === "break_days" || key === "diagnosis") return this.state.dimension === "product";
        return true;
    }
    /** Etiqueta dinámica (o null para usar la fija de UD_ALL_COLS). */
    _colLabel(key) {
        if (key === "name")        return this.dimensionLabel;
        if (key === "category")    return this.categoryLabel;
        if (key === "cross_count") return this.crossLabel;
        return null;
    }
    _withDynLabel(c) {
        const dyn = this._colLabel(c.key);
        return dyn ? { ...c, label: dyn } : c;
    }
    /** Columnas visibles, en el orden del usuario (drag), filtradas por dimensión
     *  y por el selector; con etiquetas dinámicas. */
    get columns() {
        return this.cols.visibleCols()
            .filter(c => this._colApplies(c.key))
            .filter(c => c.fixed || this.isColVisible(c.key))
            .map(c => this._withDynLabel(c));
    }
    /** Columnas opcionales aplicables (para el dropdown del selector). */
    get optionalColumns() {
        return this.cols.visibleCols()
            .filter(c => !c.fixed && this._colApplies(c.key))
            .map(c => this._withDynLabel(c));
    }
    /** Clic en encabezado: ordena por su sortKey (data-sort-key del th). */
    onHeaderClick(ev) {
        const sk = ev.currentTarget.dataset.sortKey;
        if (sk) this.setSort(sk);
    }

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

    /** Suma de un conjunto de filas (para el pie de tabla y los subtotales de grupo). */
    _sumRows(rows) {
        const sum = k => rows.reduce((s, r) => s + (r[k] || 0), 0);
        const ordered   = sum("qty_ordered");
        const delivered = sum("qty_delivered");
        const unmet     = sum("unmet_qty");
        return {
            count:           rows.length,
            qty_ordered:     ordered,
            qty_delivered:   delivered,
            unmet_qty:       unmet,
            unmet_amount:    sum("unmet_amount"),
            affected_orders: sum("affected_orders"),
            fulfillment_pct: ordered > 0 ? delivered / ordered * 100 : null,
            unmet_pct:       ordered > 0 ? unmet / ordered * 100 : null,
        };
    }
    /** Totales de la tabla, sobre TODAS las filas filtradas (no solo la página). */
    get totals() { return this._sumRows(this.filteredRows); }

    /** Texto de la celda de totales de una columna, dado un objeto de sumas. */
    _totalText(t, col) {
        switch (col.key) {
            case "qty_ordered":
            case "qty_delivered":
            case "unmet_qty":       return this.fmt(t[col.key]);
            case "unmet_amount":    return this.fmtMoney(t.unmet_amount);
            case "affected_orders": return this.fmt(t.affected_orders);
            case "fulfillment_pct": return this.fmtPct(t.fulfillment_pct);
            case "unmet_pct":       return this.fmtPct(t.unmet_pct);
            default:                return "";   // categoría, antigüedad, quiebre, diagnóstico, # cruce: no se totalizan
        }
    }
    footerText(col) { return this._totalText(this.totals, col); }

    // ── Análisis de entregabilidad (expandir fila, solo producto) ────────────────
    /** ¿Se puede expandir la fila para ver el análisis histórico? (solo producto) */
    get canExpand() { return this.state.dimension === "product"; }
    /** Expandir/colapsar una fila; al expandir carga el análisis on-demand. */
    async toggleExpand(row) {
        if (!this.canExpand) return;
        if (this.state.expandedKey === row.key) { this.state.expandedKey = null; return; }
        this.state.expandedKey = row.key;
        if (this.state.expandData[row.key] === undefined) {
            this.state.expandLoading = true;
            try {
                const res = await this.orm.call(
                    "mrp.planner.dashboard", "get_unmet_delivery_analysis",
                    [row.key, this.state.dateFrom, this.state.dateTo]);
                this.state.expandData = { ...this.state.expandData, [row.key]: res };
            } catch (e) {
                console.error("[UnmetDemandWidget] delivery analysis", e);
                this.state.expandData = { ...this.state.expandData, [row.key]: { error: true } };
            } finally {
                this.state.expandLoading = false;
            }
        }
    }
    /** Etiqueta + clases (badge, texto, barra) del diagnóstico refinado. */
    deliveryDiagnosis(diag) {
        const map = {
            fulfillment: { label: "Fulfillment",    cls: "bg-info text-dark",          text: "text-info",    bar: "bg-info" },
            shortage:    { label: "Falta de stock", cls: "bg-danger text-white",       text: "text-danger",  bar: "bg-danger" },
            mixed:       { label: "Mixto",          cls: "bg-warning text-dark",       text: "text-warning", bar: "bg-warning" },
            na:          { label: "Sin datos",      cls: "bg-light text-muted border", text: "text-muted",   bar: "bg-secondary" },
        };
        return map[diag] || map.na;
    }
    /** Frase del panel: proporción del pendiente que podías cubrir (histórico). */
    deliveryNarrative(a) {
        if (!a || a.index_pct === null || a.index_pct === undefined) return "";
        const idx = this.fmtPct(a.index_pct);
        switch (a.diagnosis) {
            case "shortage":
                return `En promedio, con el stock que tuviste solo podías cubrir ${idx} de lo pendiente. El faltante es por falta de stock: reponer o fabricar es la prioridad.`;
            case "fulfillment":
                return `En promedio tenías stock para cubrir ${idx} de lo pendiente y no se entregó. El problema no es de stock: revisá asignación, logística o prioridades de entrega.`;
            case "mixed":
                return `En promedio podías cubrir ${idx} de lo pendiente con el stock disponible. Es una mezcla: parte falta de stock, parte fulfillment.`;
            default:
                return "";
        }
    }
    /** Frase compacta de la columna "Situación" = cobertura de HOY (por fila). */
    rowSituation(row) {
        const dg = this.deliveryDiagnosis(row.diagnosis);
        if (this.state.dimension !== "product" || !row.diagnosis || row.diagnosis === "na") {
            return { text: "—", cls: "text-muted" };
        }
        const s = Math.round(row.stock_now || 0);
        const p = Math.round(row.unmet_qty || 0);
        return { text: `Hoy cubrís ${this.fmtPct(row.cover_pct)} (${s} de ${p})`, cls: dg.text };
    }
    /** Tooltip de la columna Situación. */
    rowSituationTooltip(row) {
        if (this.state.dimension !== "product" || !row.diagnosis || row.diagnosis === "na") return row.name;
        const s = Math.round(row.stock_now || 0);
        const p = Math.round(row.unmet_qty || 0);
        return `${row.name}\nHoy tenés ${s} en stock de ${p} pendientes (cubre ${this.fmtPct(row.cover_pct)}).\nExpandí la fila para ver la cobertura histórica (durante la espera).`;
    }

    /**
     * KPIs de los cards: TODOS son totales del período que vienen del backend.
     * No dependen de la dimensión (cliente/producto/familia) ni de los filtros de
     * la tabla — esos solo desagregan el detalle, no mueven los cards. Cierran
     * entre sí: Pedido = Entregado + Pendiente, y coinciden con la suma del drill
     * "Ver" de cada card.
     */
    get kpis() {
        const k = (this.state.data && this.state.data.kpis) || {};
        return {
            total_unmet_amount: k.total_unmet_amount ?? null,
            total_unmet_qty:    k.total_unmet_qty ?? null,
            total_ordered:      k.total_ordered ?? null,
            total_delivered:    k.total_delivered ?? null,
            fulfillment_pct:    k.fulfillment_pct ?? null,
            total_rows:         k.total_rows ?? 0,
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
        // En modo producto, el eje X muestra solo la referencia interna (queda
        // corto); el tooltip sigue mostrando el nombre completo. Fallback al nombre
        // si el producto no tiene referencia.
        const axisOf = r => (this.state.chartDimension === "product" && r.code) ? r.code : r.name;
        const labels = rows.map(r => { const s = axisOf(r); return s.length > 22 ? s.slice(0, 20) + "…" : s; });
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
                return `Valorización del pendiente del período\nCantidad pendiente × precio unitario\n→ ${m(k.total_unmet_amount)}` + this.amountNote();
            case "total_unmet_qty":
                return `Pendiente del período: Demanda real − Cumplimiento de demanda\n→ ${f(k.total_ordered)} − ${f(k.total_delivered)} = ${f(k.total_unmet_qty)} u.\nSe desagrega por cliente/producto/familia en la tabla.`;
            case "fulfillment_pct":
                return `Tasa de cumplimiento del período\nCumplimiento de demanda ÷ Demanda real × 100\n→ ${f(k.total_delivered)} ÷ ${f(k.total_ordered)} = ${p(k.fulfillment_pct)}\nTotal del período; no depende de la dimensión ni de los filtros de la tabla.`;
            case "total_ordered":
                return `Demanda real del período: unidades pedidas en pedidos de venta confirmados\n→ ${f(k.total_ordered)} u.\nTotal del período; no depende de la dimensión ni de los filtros de la tabla.\nDemanda real = Cumplimiento de demanda + Pendiente.`;
            case "total_delivered":
                return `Cumplimiento de demanda del período: suma de lo entregado (qty_delivered) de las líneas de esos pedidos, sin importar la fecha de entrega\n→ ${f(k.total_delivered)} u.\nTotal del período; no depende de la dimensión ni de los filtros de la tabla.`;
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
            diagnosis:       "Situación: qué proporción del pendiente cubrís con el stock que tenés HOY (stock actual ÷ pendiente). Expandí la fila para la cobertura histórica (a lo largo de la espera).",
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
                return `${row.name}\n${this.rowSituationTooltip(row)}`;
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
                if (c.kind === "situation") return this.rowSituation(row).text;
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
