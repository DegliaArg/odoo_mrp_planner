/** @odoo-module **/

/**
 * Panel de Análisis de producción. Vista de detalle (se suma al Panel de
 * Producción, no lo reemplaza) con pestañas para profundizar en la parte
 * productiva. Pestañas activas:
 * - "Carga de CT": evolución mensual de la carga % + tabla por centro con
 *   filtros/facetas/numérico + KPIs + drill a las órdenes de trabajo.
 * - "Scrap": evolución mensual de la cantidad desechada + tabla por producto
 *   con filtros/facetas/numérico + KPIs + drill a los desechos.
 * El resto de las pestañas son placeholders a completar.
 *
 * RPC: get_wc_tags, get_wc_load_table, get_wc_load_trend,
 *      get_scrap_analysis, get_scrap_trend.
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { fmt, fmtPct, sortIcon } from "@odoo_mrp_planner/js/forecast_formatters";
import { PlannerSearchBar } from "@odoo_mrp_planner/js/planner_search_bar";
import { sortRows, buildGroupTabs, resolveActiveGroup, pageSlice, makePager, applyNumericFilters } from "@odoo_mrp_planner/js/planner_table";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfYear() { const d = new Date(); return toDateStr(new Date(d.getFullYear(), 0, 1)); }
function today()       { return toDateStr(new Date()); }

const WC_COLS = [
    { key: "name",           label: "Centro de trabajo", width: 180, fixed: true, align: "start" },
    { key: "disponible",     label: "Disponible (h)",    width: 110, align: "center" },
    { key: "planificado",    label: "Planificado (h)",   width: 110, align: "center" },
    { key: "ejecutado",      label: "Ejecutado (h)",     width: 110, align: "center" },
    { key: "pendiente",      label: "Pendiente (h)",     width: 105, align: "center" },
    { key: "no_planificado", label: "No planif. (h)",    width: 110, align: "center" },
    { key: "carga_pct",      label: "Carga %",           width:  90, align: "center" },
    { key: "holgura",        label: "Holgura (h)",       width: 100, align: "center" },
    { key: "eficiencia",     label: "Eficiencia %",      width: 105, align: "center" },
];
const WC_NUM_COLS = [
    { key: "disponible",     label: "Disponible (h)" },
    { key: "planificado",    label: "Planificado (h)" },
    { key: "ejecutado",      label: "Ejecutado (h)" },
    { key: "pendiente",      label: "Pendiente (h)" },
    { key: "no_planificado", label: "No planificado (h)" },
    { key: "carga_pct",      label: "Carga %" },
    { key: "holgura",        label: "Holgura (h)" },
    { key: "eficiencia",     label: "Eficiencia %" },
];
const SCRAP_COLS = [
    { key: "name",       label: "Producto",         width: 220, fixed: true, align: "start" },
    { key: "category",   label: "Categoría",        width: 140, align: "start" },
    { key: "workcenter", label: "Centro de trabajo",width: 150, align: "start" },
    { key: "qty",        label: "Cantidad",         width: 110, align: "center" },
    { key: "uom",        label: "UdM",              width:  80, align: "center" },
    { key: "ops",        label: "Operaciones",      width: 110, align: "center" },
    { key: "pct",        label: "% del total",      width: 100, align: "center" },
];
const SCRAP_NUM_COLS = [
    { key: "qty", label: "Cantidad" },
    { key: "ops", label: "Operaciones" },
    { key: "pct", label: "% del total" },
];
const TABS = [
    { key: "wc",    label: "Carga de CT",             icon: "fa-tachometer" },
    { key: "ofs",   label: "OFs",                     icon: "fa-wrench" },
    { key: "cumpl", label: "Producido vs Programado", icon: "fa-bar-chart" },
    { key: "efic",  label: "Eficiencia",              icon: "fa-bolt" },
    { key: "scrap", label: "Scrap",                   icon: "fa-trash" },
    { key: "evol",  label: "Evolución",               icon: "fa-line-chart" },
];

class ProductionAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.ProductionAnalysisWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.trendRef = useRef("wcTrend");
        this.scrapTrendRef = useRef("scrapTrend");
        this.trendChart = null;
        this.scrapTrendChart = null;
        this.tableCols = WC_COLS;
        this.numColOptions = WC_NUM_COLS;
        this.scrapCols = SCRAP_COLS;
        this.scrapNumColOptions = SCRAP_NUM_COLS;
        this.tabs = TABS;

        this.state = useState({
            tab:      "wc",
            dateFrom: firstOfYear(),
            dateTo:   today(),
            tagId:    null,
            tags:     [],
            // Tabla Carga de CT
            search:       "",
            numFilters:   [],
            groupBy:      null,   // null | 'tag'
            selectedGroup:null,
            sortCol:      "carga_pct",
            sortDir:      "desc",
            page:         1,
            pageSize:     30,
            rows:         [],
            totals:       {},
            trend:        [],
            warnPct:      70,
            critPct:      90,
            loading:      true,
            error:        null,
            // Tabla Scrap
            scrapSearch:       "",
            scrapNumFilters:   [],
            scrapGroupBy:      null,   // null | 'category'
            scrapSelectedGroup:null,
            scrapSortCol:      "qty",
            scrapSortDir:      "desc",
            scrapPage:         1,
            scrapRows:         [],
            scrapTotals:       {},
            scrapTrend:        [],
            scrapLoaded:       false,
            scrapLoading:      false,
            scrapError:        null,
        });

        this._chartDirty = false;
        this._scrapChartDirty = false;
        this.pager = makePager(this, () => this.sortedRows.length);
        // Pager propio del tab Scrap (makePager está fijado a state.page).
        const self = this;
        this.scrapPager = {
            get totalPages() { return Math.max(1, Math.ceil(self.scrapSortedRows.length / self.state.pageSize)); },
            get hasNext()    { return self.state.scrapPage < this.totalPages; },
            get hasPrev()    { return self.state.scrapPage > 1; },
            next() { if (this.hasNext) self.state.scrapPage++; },
            prev() { if (this.hasPrev) self.state.scrapPage--; },
        };

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                await this._loadTags();
                await this._loadWc();
            } catch (e) {
                if (e.message !== "Component is destroyed") console.error("[ProdAnalysis]", e);
            }
        });
        onPatched(() => {
            if (this._chartDirty && this.trendRef.el) this._renderTrend();
            if (this._scrapChartDirty && this.scrapTrendRef.el) this._renderScrapTrend();
        });
        onWillUnmount(() => {
            if (this.trendChart) this.trendChart.destroy();
            if (this.scrapTrendChart) this.scrapTrendChart.destroy();
        });
    }

    // ── Formateadores ──────────────────────────────────────────────────────────
    fmt(n)      { return fmt(n); }
    fmtPct(n)   { return fmtPct(n); }
    sortIcon(c) { return sortIcon(c, this.state.sortCol, this.state.sortDir); }

    /** Color de la carga %: verde bajo el aviso, amarillo entre aviso y crítico,
     *  rojo por encima. Ojo: acá "más alto = peor" (inverso a las tasas). */
    cargaClass(pct) {
        if (pct === null || pct === undefined) return "text-muted";
        if (pct >= this.state.critPct) return "text-danger fw-semibold";
        if (pct >= this.state.warnPct) return "text-warning fw-semibold";
        return "text-success fw-semibold";
    }

    /** Tooltips de las cards KPI, con la estructura de 3 capas del resto del
     *  módulo: descripción · fórmula · sustitución numérica. Describen las
     *  filas visibles (búsqueda/numérico/pestaña de sector). */
    kpiTooltip(key) {
        const k = this.tableKpis;
        const f = n => fmt(n);
        const scope = `${k.centros} centro(s) visible(s)`;
        switch (key) {
            case "disponible":
                return `Horas de trabajo disponibles de ${scope}, según el calendario laboral (descuenta feriados y licencias)\nSuma de las horas de calendario de cada CT en el rango\n→ ${f(k.disponible)} h`;
            case "planificado":
                return `Horas planificadas de ${scope}: duración esperada de las OT asignadas al período\nSuma de la duración esperada (con el criterio de fechas de Ajustes)\n→ ${f(k.planificado)} h`;
            case "carga_pct":
                return `Qué parte de la capacidad disponible está comprometida por el plan, en ${scope}\nPlanificado ÷ Disponible × 100\n→ ${f(k.planificado)} ÷ ${f(k.disponible)} × 100 = ${fmtPct(k.carga_pct)}\nVerde < ${this.state.warnPct}% · Amarillo < ${this.state.critPct}% · Rojo ≥ ${this.state.critPct}% (umbrales de Ajustes)`;
            case "pendiente":
                return `Horas planificadas aún no ejecutadas de las OT abiertas de ${scope}\nSuma de máx(0, plan del período − real del período) de las OT no terminadas\n→ ${f(k.pendiente)} h`;
            case "no_planificado":
                return `Horas ejecutadas que superaron (o no tenían) plan, en ${scope}\nSuma de máx(0, real del período − plan del período)\n→ ${f(k.no_planificado)} h`;
        }
        return "";
    }

    /** Tooltips de los encabezados de columna (misma estructura/estilo). */
    colTitle(col) {
        const t = {
            name:           "Nombre del centro de trabajo. Clic para abrir su ficha; el botón abre sus órdenes de trabajo.",
            disponible:     "Horas de trabajo disponibles del CT en el rango, según su calendario laboral (descuenta feriados y licencias).",
            planificado:    "Horas planificadas: duración esperada de las OT del período (criterio de fechas de Ajustes).",
            ejecutado:      "Horas reales registradas en las OT del período (incluye las que siguen en curso).",
            pendiente:      "Horas planificadas aún no ejecutadas de las OT abiertas: máx(0, plan − real).",
            no_planificado: "Horas ejecutadas que superaron (o no tenían) plan: máx(0, real − plan).",
            carga_pct:      "Planificado ÷ Disponible × 100. Verde por debajo del aviso, amarillo hasta el crítico, rojo por encima (umbrales de Ajustes).",
            holgura:        "Capacidad libre: Disponible − Planificado. Negativa = sobrecarga.",
            eficiencia:     "Ejecutado ÷ Planificado × 100. Por encima de 100% se tardó más de lo previsto.",
        }[col.key] || col.label;
        return `${t} Clic en el encabezado para ordenar.`;
    }

    // ── Navegación de pestañas ──────────────────────────────────────────────────
    setTab(key) {
        this.state.tab = key;
        if (key === "wc") this._chartDirty = true;
        if (key === "scrap") {
            this._scrapChartDirty = true;
            if (!this.state.scrapLoaded) this._loadScrap();
        }
    }

    // ── Carga de datos ──────────────────────────────────────────────────────────
    async _loadTags() {
        try {
            const d = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
            this.state.tags = (d && d.tags) || [];
        } catch (e) {
            if (e.message !== "Component is destroyed") console.error("[ProdAnalysis]", e);
        }
    }

    async _loadWc() {
        this.state.loading = true;
        this.state.error   = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_wc_load_table",
                              [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_wc_load_trend",
                              [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
            ]);
            this.state.rows    = table.rows || [];
            this.state.totals  = table.totals || {};
            this.state.warnPct = (table.totals && table.totals.warn_pct) || 70;
            this.state.critPct = (table.totals && table.totals.crit_pct) || 90;
            this.state.trend   = trend.trend || [];
            this.state.page    = 1;
            this._chartDirty   = true;
            this._renderTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.error = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value || firstOfYear(); this._reloadActive(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value || today(); this._reloadActive(); }
    onTagChange(ev)      { this.state.tagId = ev.target.value ? parseInt(ev.target.value) : null; this._loadWc(); }

    /** Recarga la(s) fuente(s) afectada(s) por un cambio de rango: siempre la de
     *  Carga de CT y, si ya se abrió, la de Scrap. */
    _reloadActive() {
        this._loadWc();
        if (this.state.scrapLoaded) this._loadScrap();
    }

    // ── Gráfico de evolución mensual de la carga % ──────────────────────────────
    _renderTrend() {
        const el = this.trendRef.el;
        // Canvas aún no montado (primera carga con spinner) o bundle no listo:
        // dejar el flag para que onPatched reintente cuando el DOM lo tenga.
        if (!el || typeof Chart === "undefined") return;
        if (this.trendChart) { this.trendChart.destroy(); this.trendChart = null; }
        this._chartDirty = false;
        const t = this.state.trend || [];
        const labels = t.map(m => {
            const [y, mo] = m.ym.split("-");
            return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
        });
        this.trendChart = new Chart(el, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "Carga %",
                    data: t.map(m => m.carga_pct),
                    borderColor: "#0d6efd",
                    backgroundColor: "rgba(13,110,253,0.10)",
                    fill: true, spanGaps: true, tension: 0.25, pointRadius: 4,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { min: 0, ticks: { callback: v => v + "%" } } },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => {
                        const m = t[ctx.dataIndex];
                        return m.carga_pct === null ? "Sin datos"
                            : `${m.carga_pct}% — plan ${fmt(m.planificado)} h / disp ${fmt(m.disponible)} h`;
                    } } },
                },
            },
        });
    }

    // ── Tabla: filtros / orden / paginación / agrupación ────────────────────────
    _numVal(row, key) {
        const v = row[key];
        return (v === null || v === undefined) ? null : v;
    }

    setSearch(text) { this.state.search = text; this.state.page = 1; }
    setGroupBy(key) { this.state.groupBy = key; this.state.selectedGroup = null; this.state.page = 1; }
    addNumFilter(cond) { this.state.numFilters = [...this.state.numFilters, cond]; this.state.page = 1; }
    removeNumFilter(idx) { this.state.numFilters = this.state.numFilters.filter((_, i) => i !== idx); this.state.page = 1; }

    setSort(col) {
        if (this.state.sortCol === col) this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        else { this.state.sortCol = col; this.state.sortDir = "asc"; }
    }

    get filteredRows() {
        let rows = this.state.rows;
        const q = (this.state.search || "").trim().toLowerCase();
        if (q) rows = rows.filter(r => (r.name || "").toLowerCase().includes(q));
        return applyNumericFilters(rows, this.state.numFilters, (r, k) => this._numVal(r, k));
    }

    get allGroupsForTabs() {
        if (this.state.groupBy !== "tag") return null;
        // Un CT puede tener varios tags: cuenta en cada uno (M2M).
        return buildGroupTabs(this.filteredRows,
            r => (r.tags && r.tags.length) ? r.tags : ["Sin sector"]);
    }
    get activeGroupKey() { return resolveActiveGroup(this.allGroupsForTabs || [], this.state.selectedGroup); }
    setGroup(key) { this.state.selectedGroup = key; this.state.page = 1; }

    get groupedRows() {
        if (this.state.groupBy !== "tag") return this.filteredRows;
        const active = this.activeGroupKey;
        return this.filteredRows.filter(r =>
            ((r.tags && r.tags.length) ? r.tags : ["Sin sector"]).includes(active));
    }

    get sortedRows() { return sortRows(this.groupedRows, this.state.sortCol, this.state.sortDir); }
    get pagedRows()  { return pageSlice(this.sortedRows, this.state.page, this.state.pageSize); }
    get totalPages() { return this.pager.totalPages; }
    get hasNextPage(){ return this.pager.hasNext; }
    get hasPrevPage(){ return this.pager.hasPrev; }
    nextPage() { this.pager.next(); }
    prevPage() { this.pager.prev(); }

    /** KPIs dinámicos: describen las filas visibles (búsqueda/numérico/pestaña). */
    get tableKpis() {
        const rows = this.groupedRows;
        let disp = 0, plan = 0, ejec = 0, pend = 0, noplan = 0;
        for (const r of rows) {
            disp   += r.disponible     || 0;
            plan   += r.planificado    || 0;
            ejec   += r.ejecutado      || 0;
            pend   += r.pendiente      || 0;
            noplan += r.no_planificado || 0;
        }
        return {
            disponible:  Math.round(disp * 10) / 10,
            planificado: Math.round(plan * 10) / 10,
            ejecutado:   Math.round(ejec * 10) / 10,
            pendiente:   Math.round(pend * 10) / 10,
            no_planificado: Math.round(noplan * 10) / 10,
            carga_pct:   disp > 0 ? Math.round(plan / disp * 1000) / 10 : null,
            centros:     rows.length,
        };
    }

    /** Definición de las cards KPI (para iterar en el template). */
    get kpiCards() {
        const k = this.tableKpis;
        return [
            { key: "disponible",     label: "Disponible (h)",     value: fmt(k.disponible),     cls: "" },
            { key: "planificado",    label: "Planificado (h)",    value: fmt(k.planificado),    cls: "" },
            { key: "carga_pct",      label: "Carga %",            value: fmtPct(k.carga_pct),   cls: this.cargaClass(k.carga_pct) },
            { key: "pendiente",      label: "Pendiente (h)",      value: fmt(k.pendiente),      cls: "" },
            { key: "no_planificado", label: "No planificado (h)", value: fmt(k.no_planificado), cls: "" },
        ];
    }

    // ── Drill: órdenes de trabajo ───────────────────────────────────────────────
    openWcOrders(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Órdenes de trabajo — ${row.name}`,
            res_model: "mrp.workorder",
            domain: [["workcenter_id", "=", row.wc_id], ["state", "!=", "cancel"]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
    /** "Ver →" de las cards: OTs de los centros visibles en el rango. */
    openVisibleOrders() {
        const ids = this.groupedRows.map(r => r.wc_id);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Órdenes de trabajo del período",
            res_model: "mrp.workorder",
            domain: [["workcenter_id", "in", ids], ["state", "!=", "cancel"]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
    openWc(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mrp.workcenter",
            res_id: row.wc_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    cellValue(row, key) {
        if (key === "carga_pct" || key === "eficiencia") return fmtPct(row[key]);
        if (key === "name") return row.name;
        return fmt(row[key]);
    }

    // ════════════════════ Scrap ════════════════════
    scrapSortIcon(c) { return sortIcon(c, this.state.scrapSortCol, this.state.scrapSortDir); }

    async _loadScrap() {
        this.state.scrapLoading = true;
        this.state.scrapError   = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_scrap_analysis",
                              [this.state.dateFrom, this.state.dateTo]),
                this.orm.call("mrp.planner.dashboard", "get_scrap_trend",
                              [this.state.dateFrom, this.state.dateTo]),
            ]);
            this.state.scrapRows   = table.rows || [];
            this.state.scrapTotals = table.totals || {};
            this.state.scrapTrend  = trend.trend || [];
            this.state.scrapPage   = 1;
            this.state.scrapLoaded = true;
            this._scrapChartDirty  = true;
            this._renderScrapTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.scrapError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.scrapLoading = false;
        }
    }

    _renderScrapTrend() {
        const el = this.scrapTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.scrapTrendChart) { this.scrapTrendChart.destroy(); this.scrapTrendChart = null; }
        this._scrapChartDirty = false;
        const t = this.state.scrapTrend || [];
        const labels = t.map(m => {
            const [y, mo] = m.ym.split("-");
            return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
        });
        this.scrapTrendChart = new Chart(el, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Cantidad desechada",
                    data: t.map(m => m.qty),
                    backgroundColor: "rgba(220,53,69,0.55)",
                    borderColor: "#dc3545",
                    borderWidth: 1,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { min: 0 } },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => {
                        const m = t[ctx.dataIndex];
                        return `${fmt(m.qty)} u. desechadas · ${m.ops} operación(es)`;
                    } } },
                },
            },
        });
    }

    setScrapSearch(text) { this.state.scrapSearch = text; this.state.scrapPage = 1; }
    setScrapGroupBy(key) { this.state.scrapGroupBy = key; this.state.scrapSelectedGroup = null; this.state.scrapPage = 1; }
    addScrapNumFilter(cond) { this.state.scrapNumFilters = [...this.state.scrapNumFilters, cond]; this.state.scrapPage = 1; }
    removeScrapNumFilter(idx) { this.state.scrapNumFilters = this.state.scrapNumFilters.filter((_, i) => i !== idx); this.state.scrapPage = 1; }
    setScrapSort(col) {
        if (this.state.scrapSortCol === col) this.state.scrapSortDir = this.state.scrapSortDir === "asc" ? "desc" : "asc";
        else { this.state.scrapSortCol = col; this.state.scrapSortDir = "asc"; }
    }

    get scrapFilteredRows() {
        let rows = this.state.scrapRows;
        const q = (this.state.scrapSearch || "").trim().toLowerCase();
        if (q) rows = rows.filter(r =>
            (r.name || "").toLowerCase().includes(q) ||
            (r.category || "").toLowerCase().includes(q) ||
            (r.workcenter || "").toLowerCase().includes(q));
        return applyNumericFilters(rows, this.state.scrapNumFilters, (r, k) => this._numVal(r, k));
    }
    get scrapAllGroupsForTabs() {
        if (this.state.scrapGroupBy !== "category") return null;
        return buildGroupTabs(this.scrapFilteredRows, r => [r.category || "Sin categoría"]);
    }
    get scrapActiveGroupKey() { return resolveActiveGroup(this.scrapAllGroupsForTabs || [], this.state.scrapSelectedGroup); }
    setScrapGroup(key) { this.state.scrapSelectedGroup = key; this.state.scrapPage = 1; }
    get scrapGroupedRows() {
        if (this.state.scrapGroupBy !== "category") return this.scrapFilteredRows;
        const active = this.scrapActiveGroupKey;
        return this.scrapFilteredRows.filter(r => (r.category || "Sin categoría") === active);
    }
    get scrapSortedRows() { return sortRows(this.scrapGroupedRows, this.state.scrapSortCol, this.state.scrapSortDir); }
    get scrapPagedRows()  { return pageSlice(this.scrapSortedRows, this.state.scrapPage, this.state.pageSize); }
    get scrapTotalPages() { return this.scrapPager.totalPages; }
    get scrapHasNextPage(){ return this.scrapPager.hasNext; }
    get scrapHasPrevPage(){ return this.scrapPager.hasPrev; }
    scrapNextPage() { this.scrapPager.next(); }
    scrapPrevPage() { this.scrapPager.prev(); }

    /** KPIs del scrap: describen las filas visibles. */
    get scrapKpis() {
        const rows = this.scrapGroupedRows;
        let qty = 0, ops = 0;
        for (const r of rows) { qty += r.qty || 0; ops += r.ops || 0; }
        return {
            qty:      Math.round(qty * 100) / 100,
            ops,
            products: rows.length,
        };
    }
    get scrapKpiCards() {
        const k = this.scrapKpis;
        return [
            { key: "qty",      label: "Cantidad desechada", value: fmt(k.qty),      cls: "text-danger fw-semibold" },
            { key: "ops",      label: "Operaciones",        value: fmt(k.ops),      cls: "" },
            { key: "products", label: "Productos",          value: fmt(k.products), cls: "" },
        ];
    }
    scrapKpiTooltip(key) {
        const k = this.scrapKpis;
        const scope = `${k.products} producto(s) visible(s)`;
        switch (key) {
            case "qty":
                return `Cantidad total desechada de ${scope} en el período (desechos validados)\nSuma de la cantidad de cada operación de desecho\n→ ${fmt(k.qty)} u.\nOjo: suma unidades posiblemente mixtas (distintos productos/UdM); leer como tendencia, no como magnitud única.`;
            case "ops":
                return `Cantidad de operaciones de desecho de ${scope} en el período\nConteo de registros de stock.scrap validados\n→ ${fmt(k.ops)} operación(es)`;
            case "products":
                return `Productos distintos con al menos un desecho en el período\nConteo de productos únicos\n→ ${fmt(k.products)} producto(s)`;
        }
        return "";
    }
    scrapColTitle(col) {
        const t = {
            name:       "Producto desechado. Clic en el botón para ver sus operaciones de desecho.",
            category:   "Categoría de producto del ítem desechado.",
            workcenter: "Centro de trabajo con más cantidad desechada del producto (— si el desecho no proviene de una OT).",
            qty:        "Cantidad total desechada del producto en el período (desechos validados).",
            uom:        "Unidad de medida del producto.",
            ops:        "Cantidad de operaciones de desecho del producto en el período.",
            pct:        "Participación del producto sobre la cantidad total desechada del período.",
        }[col.key] || col.label;
        return `${t} Clic en el encabezado para ordenar.`;
    }
    scrapCellValue(row, key) {
        if (key === "pct") return fmtPct(row.pct);
        if (key === "qty" || key === "ops") return fmt(row[key]);
        return row[key] || "—";
    }

    // ── Drill: desechos ─────────────────────────────────────────────────────────
    _scrapRangeDomain() {
        return [
            ["state", "=", "done"],
            ["date_done", ">=", this.state.dateFrom + " 00:00:00"],
            ["date_done", "<=", this.state.dateTo + " 23:59:59"],
        ];
    }
    openScrapAll() {
        const ids = this.scrapGroupedRows.map(r => r.product_id);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Desechos del período",
            res_model: "stock.scrap",
            domain: [...this._scrapRangeDomain(), ["product_id", "in", ids]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
    openProductScraps(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Desechos — ${row.name}`,
            res_model: "stock.scrap",
            domain: [...this._scrapRangeDomain(), ["product_id", "=", row.product_id]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
}

registry.category("view_widgets").add("production_analysis_widget", {
    component: ProductionAnalysisWidget,
});
