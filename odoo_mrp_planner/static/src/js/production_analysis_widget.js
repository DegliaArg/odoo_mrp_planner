/** @odoo-module **/

/**
 * Panel de Análisis de producción. Vista de detalle (se suma al Panel de
 * Producción, no lo reemplaza) con pestañas para profundizar en la parte
 * productiva. Fase 1: pestaña "Carga de CT" completa (evolución mensual de la
 * carga % + tabla por centro con filtros/facetas/numérico + KPIs + drill a las
 * órdenes de trabajo). El resto de las pestañas son placeholders a completar.
 *
 * RPC: get_wc_tags, get_wc_load_table, get_wc_load_trend.
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
    { key: "disponible",     label: "Disponible (h)",    width: 110, align: "end" },
    { key: "planificado",    label: "Planificado (h)",   width: 110, align: "end" },
    { key: "ejecutado",      label: "Ejecutado (h)",     width: 110, align: "end" },
    { key: "pendiente",      label: "Pendiente (h)",     width: 105, align: "end" },
    { key: "no_planificado", label: "No planif. (h)",    width: 110, align: "end" },
    { key: "carga_pct",      label: "Carga %",           width:  90, align: "end" },
    { key: "holgura",        label: "Holgura (h)",       width: 100, align: "end" },
    { key: "eficiencia",     label: "Eficiencia %",      width: 105, align: "end" },
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
const TABS = [
    { key: "wc",    label: "Carga de CT",             icon: "fa-tachometer" },
    { key: "ofs",   label: "OFs",                     icon: "fa-wrench" },
    { key: "cumpl", label: "Producido vs Programado", icon: "fa-bar-chart" },
    { key: "efic",  label: "Eficiencia",              icon: "fa-bolt" },
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
        this.trendChart = null;
        this.tableCols = WC_COLS;
        this.numColOptions = WC_NUM_COLS;
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
        });

        this._chartDirty = false;
        this.pager = makePager(this, () => this.sortedRows.length);

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
        });
        onWillUnmount(() => { if (this.trendChart) this.trendChart.destroy(); });
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

    // ── Navegación de pestañas ──────────────────────────────────────────────────
    setTab(key) {
        this.state.tab = key;
        if (key === "wc") this._chartDirty = true;
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

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value || firstOfYear(); this._loadWc(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value || today(); this._loadWc(); }
    onTagChange(ev)      { this.state.tagId = ev.target.value ? parseInt(ev.target.value) : null; this._loadWc(); }

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

    // ── Drill: órdenes de trabajo de un CT ──────────────────────────────────────
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
}

registry.category("view_widgets").add("production_analysis_widget", {
    component: ProductionAnalysisWidget,
});
