/** @odoo-module **/

/**
 * Panel de Análisis de producción. Vista de detalle (se suma al Panel de
 * Producción, no lo reemplaza) con pestañas para profundizar en la parte
 * productiva. Cada pestaña combina un gráfico de evolución mensual, KPIs con
 * tooltips de 3 capas y una tabla con búsqueda/facetas/filtro numérico y drill:
 * - "Carga de CT": carga % por centro de trabajo.
 * - "OFs": órdenes de fabricación por producto (cantidades, estados, atrasos).
 * - "Producido vs Programado": comparativo ponderado por producto.
 * - "Eficiencia": horas planificadas vs reales por producto.
 * - "Scrap": desechos por producto.
 * - "Evolución": resumen mensual que compone carga, cumplimiento y eficiencia.
 *
 * Las tablas OFs/Comparativo/Eficiencia comparten la maquinaria vía TableCtl.
 *
 * RPC: get_wc_tags, get_wc_load_table, get_wc_load_trend, get_scrap_analysis,
 *      get_scrap_trend, get_of_analysis, get_of_trend, get_comparison_analysis,
 *      get_comparison_trend, get_efficiency_analysis, get_efficiency_trend,
 *      get_evolution_analysis.
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
    { key: "category",   label: "Categoría",        width: 130, align: "start" },
    { key: "workcenter", label: "Centro de trabajo",width: 140, align: "start" },
    { key: "qty",        label: "Desecho",          width: 100, align: "center" },
    { key: "uom",        label: "UdM",              width:  70, align: "center" },
    { key: "producido",  label: "Producido",        width: 100, align: "center" },
    { key: "tasa",       label: "Tasa scrap %",     width: 110, align: "center" },
    { key: "pct",        label: "% del total",      width:  95, align: "center" },
];
const SCRAP_NUM_COLS = [
    { key: "qty", label: "Desecho" },
    { key: "producido", label: "Producido" },
    { key: "tasa", label: "Tasa scrap %" },
    { key: "pct", label: "% del total" },
];
const OF_COLS = [
    { key: "name",       label: "Producto",   width: 220, fixed: true, align: "start" },
    { key: "category",   label: "Categoría",  width: 130, align: "start" },
    { key: "uom",        label: "UdM",        width:  70, align: "center" },
    { key: "ofs",        label: "OFs",        width:  70, align: "center" },
    { key: "programado", label: "Programado", width: 110, align: "center" },
    { key: "producido",  label: "Producido",  width: 110, align: "center" },
    { key: "avance_pct", label: "Avance %",   width:  90, align: "center" },
    { key: "terminadas", label: "Term.",      width:  75, align: "center" },
    { key: "en_curso",   label: "En curso",   width:  85, align: "center" },
    { key: "atrasadas",  label: "Atrasadas",  width:  90, align: "center" },
];
const OF_NUM_COLS = [
    { key: "ofs", label: "OFs" }, { key: "programado", label: "Programado" },
    { key: "producido", label: "Producido" }, { key: "avance_pct", label: "Avance %" },
    { key: "terminadas", label: "Terminadas" }, { key: "en_curso", label: "En curso" },
    { key: "atrasadas", label: "Atrasadas" },
];
const CMP_COLS = [
    { key: "name",       label: "Producto",       width: 240, fixed: true, align: "start" },
    { key: "uom",        label: "UdM",            width:  80, align: "center" },
    { key: "programado", label: "Programado",     width: 120, align: "center" },
    { key: "producido",  label: "Producido",      width: 120, align: "center" },
    { key: "desvio",     label: "Desvío",         width: 110, align: "center" },
    { key: "pct",        label: "Cumplimiento %", width: 130, align: "center" },
];
const CMP_NUM_COLS = [
    { key: "programado", label: "Programado" }, { key: "producido", label: "Producido" },
    { key: "desvio", label: "Desvío" }, { key: "pct", label: "Cumplimiento %" },
];
const EF_COLS = [
    { key: "name",       label: "Producto",     width: 240, fixed: true, align: "start" },
    { key: "category",   label: "Categoría",    width: 150, align: "start" },
    { key: "ofs",        label: "OFs",          width:  80, align: "center" },
    { key: "plan_h",     label: "Plan (h)",     width: 110, align: "center" },
    { key: "real_h",     label: "Real (h)",     width: 110, align: "center" },
    { key: "eficiencia", label: "Eficiencia %", width: 120, align: "center" },
];
const EF_NUM_COLS = [
    { key: "ofs", label: "OFs" }, { key: "plan_h", label: "Plan (h)" },
    { key: "real_h", label: "Real (h)" }, { key: "eficiencia", label: "Eficiencia %" },
];
const EVOL_COLS = [
    { key: "ym",         label: "Mes",           width: 110, align: "start" },
    { key: "ofs",        label: "OFs",           width:  80, align: "center" },
    { key: "terminadas", label: "Terminadas",    width: 100, align: "center" },
    { key: "producido",  label: "Producido",     width: 110, align: "center" },
    { key: "carga_pct",  label: "Carga %",       width:  95, align: "center" },
    { key: "cumpl_pct",  label: "Cumplimiento %",width: 130, align: "center" },
    { key: "efic_pct",   label: "Eficiencia %",  width: 120, align: "center" },
    { key: "scrap",      label: "Scrap",         width:  95, align: "center" },
];
// Facetas de agrupación reutilizables. Sector es M2M (un producto puede caer en
// varios, como en Carga de CT); Categoría es escalar. El accesor devuelve la(s)
// clave(s) de cada fila.
const SECTOR_GROUP   = { key: "sector",   label: "Sector",    accessor: r => (r.sectors && r.sectors.length) ? r.sectors : ["Sin sector"] };
const CATEGORY_GROUP = { key: "category", label: "Categoría", accessor: r => [r.category || "Sin categoría"] };

const OEE_COLS = [
    { key: "name",         label: "Centro de trabajo", width: 200, fixed: true, align: "start" },
    { key: "availability", label: "Disp. %",           width:  90, align: "center" },
    { key: "performance",  label: "Rend. %",           width:  90, align: "center" },
    { key: "quality",      label: "Calidad %",         width: 100, align: "center" },
    { key: "oee",          label: "OEE %",             width:  90, align: "center" },
    { key: "ooe",          label: "OOE %",             width:  90, align: "center" },
    { key: "teep",         label: "TEEP %",            width:  90, align: "center" },
    { key: "productive_h", label: "Productivo (h)",    width: 110, align: "center" },
];
const OEE_NUM_COLS = [
    { key: "availability", label: "Disponibilidad %" }, { key: "performance", label: "Rendimiento %" },
    { key: "quality", label: "Calidad %" }, { key: "oee", label: "OEE %" },
    { key: "ooe", label: "OOE %" }, { key: "teep", label: "TEEP %" },
    { key: "productive_h", label: "Productivo (h)" },
];
const TABS = [
    { key: "wc",    label: "Carga de CT",             icon: "fa-tachometer" },
    { key: "ofs",   label: "OFs",                     icon: "fa-wrench" },
    { key: "cumpl", label: "Producido vs Programado", icon: "fa-bar-chart" },
    { key: "efic",  label: "Plan vs Real",            icon: "fa-balance-scale" },
    { key: "oee",   label: "OEE",                     icon: "fa-heartbeat" },
    { key: "scrap", label: "Scrap",                   icon: "fa-trash" },
    { key: "evol",  label: "Evolución",               icon: "fa-line-chart" },
];

/**
 * Controlador de tabla reutilizable para las pestañas del panel (OFs, Producido
 * vs Programado, Eficiencia). Encapsula búsqueda, filtro numérico, agrupación
 * por facetas, orden y paginación operando sobre un "slice" de state.<prefix>*,
 * de modo que cada pestaña sea un objeto de configuración y no una copia de la
 * misma maquinaria. Sus getters leen state reactivo → OWL los rastrea al
 * renderizar; sus setters mutan state → disparan re-render.
 */
class TableCtl {
    constructor(widget, cfg) { this.w = widget; this.cfg = cfg; }
    _k(sfx) { return this.cfg.prefix + sfx; }
    get s() { return this.w.state; }

    get rows()       { return this.s[this._k("Rows")] || []; }
    get loaded()     { return this.s[this._k("Loaded")]; }
    get loading()    { return this.s[this._k("Loading")]; }
    get error()      { return this.s[this._k("Error")]; }
    get search()     { return this.s[this._k("Search")]; }
    get numFilters() { return this.s[this._k("NumFilters")]; }
    get groupBy()    { return this.s[this._k("GroupBy")]; }
    get sortColV()   { return this.s[this._k("SortCol")]; }
    get sortDirV()   { return this.s[this._k("SortDir")]; }
    get page()       { return this.s[this._k("Page")]; }

    setSearch(t) { this.s[this._k("Search")] = t; this.s[this._k("Page")] = 1; }
    setGroupBy(k) { this.s[this._k("GroupBy")] = k; this.s[this._k("SelGroup")] = null; this.s[this._k("Page")] = 1; }
    addNumFilter(c) { this.s[this._k("NumFilters")] = [...this.numFilters, c]; this.s[this._k("Page")] = 1; }
    removeNumFilter(i) { this.s[this._k("NumFilters")] = this.numFilters.filter((_, j) => j !== i); this.s[this._k("Page")] = 1; }
    setSort(col) {
        if (this.sortColV === col) this.s[this._k("SortDir")] = this.sortDirV === "asc" ? "desc" : "asc";
        else { this.s[this._k("SortCol")] = col; this.s[this._k("SortDir")] = "asc"; }
    }
    sortIcon(c) { return sortIcon(c, this.sortColV, this.sortDirV); }

    _numVal(r, k) { const v = r[k]; return (v === null || v === undefined) ? null : v; }
    get filteredRows() {
        let rows = this.rows;
        const q = (this.search || "").trim().toLowerCase();
        if (q) rows = rows.filter(r => this.cfg.textFields.some(f => (r[f] || "").toLowerCase().includes(q)));
        return applyNumericFilters(rows, this.numFilters, (r, k) => this._numVal(r, k));
    }
    _activeGroupDef() { return (this.cfg.groupDefs || []).find(d => d.key === this.groupBy) || null; }
    get groupsForTabs() {
        const d = this._activeGroupDef();
        if (!d) return null;
        return buildGroupTabs(this.filteredRows, d.accessor);
    }
    get activeGroupKey() { return resolveActiveGroup(this.groupsForTabs || [], this.s[this._k("SelGroup")]); }
    setGroup(k) { this.s[this._k("SelGroup")] = k; this.s[this._k("Page")] = 1; }
    get groupedRows() {
        const d = this._activeGroupDef();
        if (!d) return this.filteredRows;
        const a = this.activeGroupKey;
        return this.filteredRows.filter(r => d.accessor(r).includes(a));
    }
    get sortedRows() { return sortRows(this.groupedRows, this.sortColV, this.sortDirV); }
    get pagedRows()  { return pageSlice(this.sortedRows, this.page, this.s.pageSize); }
    get totalPages() { return Math.max(1, Math.ceil(this.sortedRows.length / this.s.pageSize)); }
    get hasNext()    { return this.page < this.totalPages; }
    get hasPrev()    { return this.page > 1; }
    next() { if (this.hasNext) this.s[this._k("Page")]++; }
    prev() { if (this.hasPrev) this.s[this._k("Page")]--; }

    get kpis()          { return this.cfg.computeKpis(this.groupedRows, this.w); }
    get kpiCards()      { return this.cfg.kpiCards(this.kpis, this.w); }
    kpiTooltip(key)     { return this.cfg.kpiTooltip(key, this.kpis, this.w); }
    colTitle(col)       { return this.cfg.colTitle(col); }
    cellValue(row, key) { return this.cfg.cellValue(row, key, this.w); }
    cellClass(row, key) { return this.cfg.cellClass ? this.cfg.cellClass(row, key, this.w) : ""; }
    viewAll() { this.cfg.onViewAll(this.groupedRows, this.w); }
    viewRow(row) { this.cfg.onViewRow(row, this.w); }

    get cols()         { return this.cfg.cols; }
    get numColOptions(){ return this.cfg.numCols; }
    get groupByDefs()  { return (this.cfg.groupDefs || []).map(d => ({ key: d.key, label: d.label })); }
    get widgetKey()    { return "production_analysis_" + this.cfg.prefix; }
    get placeholder()  { return this.cfg.placeholder; }
    get emptyMsg()     { return this.cfg.emptyMsg; }
    get rowKey()       { return this.cfg.rowKey || "product_id"; }
    get unit()         { return this.cfg.unit || "producto(s)"; }
}

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

        this.state = useState({
            tab:      "wc",
            dateFrom: firstOfYear(),
            dateTo:   today(),
            tagId:    null,
            tags:     [],
            enableOee: false,
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
            // Tabla OFs
            ofRows: [], ofSearch: "", ofNumFilters: [], ofGroupBy: null, ofSelGroup: null,
            ofSortCol: "programado", ofSortDir: "desc", ofPage: 1, ofTrend: [],
            ofGreen: 90, ofWarn: 50, ofLoaded: false, ofLoading: false, ofError: null,
            // Tabla Producido vs Programado
            cmpRows: [], cmpSearch: "", cmpNumFilters: [], cmpGroupBy: null, cmpSelGroup: null,
            cmpSortCol: "programado", cmpSortDir: "desc", cmpPage: 1, cmpTrend: [],
            cmpKpisData: {}, cmpGreen: 90, cmpWarn: 50, cmpTruncated: false, cmpTotal: 0,
            cmpLoaded: false, cmpLoading: false, cmpError: null,
            // Tabla Eficiencia
            efRows: [], efSearch: "", efNumFilters: [], efGroupBy: null, efSelGroup: null,
            efSortCol: "plan_h", efSortDir: "desc", efPage: 1, efTrend: [],
            efLoaded: false, efLoading: false, efError: null,
            // Evolución (resumen mensual)
            evolRows: [], evolWarnPct: 70, evolCritPct: 90, evolGreen: 90,
            evolLoaded: false, evolLoading: false, evolError: null,
            // Tabla OEE (avanzado)
            oeeRows: [], oeeSearch: "", oeeNumFilters: [], oeeGroupBy: null, oeeSelGroup: null,
            oeeSortCol: "oee", oeeSortDir: "desc", oeePage: 1, oeeTrend: [],
            oeeHasData: true, oeeGreen: 85, oeeWarn: 60,
            oeeLoaded: false, oeeLoading: false, oeeError: null,
        });

        this._chartDirty = false;
        this._scrapChartDirty = false;
        this._ofChartDirty = false;
        this._cmpChartDirty = false;
        this._efChartDirty = false;
        this._evolChartDirty = false;
        this._oeeChartDirty = false;
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

        // Refs de gráficos de las nuevas pestañas
        this.ofTrendRef   = useRef("ofTrend");
        this.cmpTrendRef  = useRef("cmpTrend");
        this.efTrendRef   = useRef("efTrend");
        this.evolTrendRef = useRef("evolTrend");
        this.oeeTrendRef  = useRef("oeeTrend");
        this.ofTrendChart = this.cmpTrendChart = this.efTrendChart = this.evolTrendChart = this.oeeTrendChart = null;

        // Controladores de tabla (una config por pestaña, misma maquinaria)
        this.ctls = {
            of:  new TableCtl(this, this._ofCfg()),
            cmp: new TableCtl(this, this._cmpCfg()),
            ef:  new TableCtl(this, this._efCfg()),
            oee: new TableCtl(this, this._oeeCfg()),
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
            if (this._ofChartDirty && this.ofTrendRef.el) this._renderOfTrend();
            if (this._cmpChartDirty && this.cmpTrendRef.el) this._renderCmpTrend();
            if (this._efChartDirty && this.efTrendRef.el) this._renderEfTrend();
            if (this._evolChartDirty && this.evolTrendRef.el) this._renderEvolTrend();
            if (this._oeeChartDirty && this.oeeTrendRef.el) this._renderOeeTrend();
        });
        onWillUnmount(() => {
            for (const c of [this.trendChart, this.scrapTrendChart, this.ofTrendChart,
                             this.cmpTrendChart, this.efTrendChart, this.evolTrendChart,
                             this.oeeTrendChart]) {
                if (c) c.destroy();
            }
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

    /** Pestañas visibles: la de OEE solo si está habilitada en Ajustes. */
    get tabs() {
        return this.state.enableOee ? TABS : TABS.filter(t => t.key !== "oee");
    }

    // ── Navegación de pestañas ──────────────────────────────────────────────────
    setTab(key) {
        this.state.tab = key;
        if (key === "wc") this._chartDirty = true;
        if (key === "scrap") { this._scrapChartDirty = true; if (!this.state.scrapLoaded) this._loadScrap(); }
        if (key === "ofs")   { this._ofChartDirty = true; if (!this.state.ofLoaded) this._loadOf(); }
        if (key === "cumpl") { this._cmpChartDirty = true; if (!this.state.cmpLoaded) this._loadCmp(); }
        if (key === "efic")  { this._efChartDirty = true; if (!this.state.efLoaded) this._loadEf(); }
        if (key === "oee")   { this._oeeChartDirty = true; if (!this.state.oeeLoaded) this._loadOee(); }
        if (key === "evol")  { this._evolChartDirty = true; if (!this.state.evolLoaded) this._loadEvol(); }
    }

    // ── Carga de datos ──────────────────────────────────────────────────────────
    async _loadTags() {
        try {
            const d = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
            this.state.tags = (d && d.tags) || [];
            this.state.enableOee = !!(d && d.enable_oee);
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
    onTagChange(ev)      { this.state.tagId = ev.target.value ? parseInt(ev.target.value) : null; this._reloadActive(); }

    /** Recarga las fuentes ya abiertas al cambiar el rango o el sector (la de
     *  Carga de CT siempre; el resto solo si su pestaña se visitó). */
    _reloadActive() {
        this._loadWc();
        if (this.state.scrapLoaded) this._loadScrap();
        if (this.state.ofLoaded)    this._loadOf();
        if (this.state.cmpLoaded)   this._loadCmp();
        if (this.state.efLoaded)    this._loadEf();
        if (this.state.oeeLoaded)   this._loadOee();
        if (this.state.evolLoaded)  this._loadEvol();
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
                              [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_scrap_trend",
                              [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
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
            data: {
                labels,
                datasets: [
                    { type: "bar", label: "Cantidad desechada", yAxisID: "y",
                      data: t.map(m => m.qty), backgroundColor: "rgba(220,53,69,0.45)",
                      borderColor: "#dc3545", borderWidth: 1, order: 2 },
                    { type: "line", label: "Tasa de scrap %", yAxisID: "y1",
                      data: t.map(m => m.tasa), borderColor: "#6f42c1",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25,
                      pointRadius: 3, order: 1 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    y:  { min: 0, position: "left", title: { display: true, text: "Cantidad" } },
                    y1: { min: 0, position: "right", grid: { drawOnChartArea: false },
                          ticks: { callback: v => v + "%" }, title: { display: true, text: "Tasa %" } },
                },
                plugins: {
                    legend: { display: true, position: "bottom" },
                    tooltip: { callbacks: { label: (ctx) => {
                        const m = t[ctx.dataIndex];
                        if (ctx.datasetIndex === 1) {
                            return m.tasa === null ? "Tasa: s/prod" : `Tasa: ${m.tasa}%`;
                        }
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
    /** Facetas de agrupación del scrap: por sector (M2M) o por categoría. */
    _scrapGroupDef() {
        if (this.state.scrapGroupBy === "sector") return SECTOR_GROUP;
        if (this.state.scrapGroupBy === "category") return CATEGORY_GROUP;
        return null;
    }
    get scrapAllGroupsForTabs() {
        const d = this._scrapGroupDef();
        if (!d) return null;
        return buildGroupTabs(this.scrapFilteredRows, d.accessor);
    }
    get scrapActiveGroupKey() { return resolveActiveGroup(this.scrapAllGroupsForTabs || [], this.state.scrapSelectedGroup); }
    setScrapGroup(key) { this.state.scrapSelectedGroup = key; this.state.scrapPage = 1; }
    get scrapGroupedRows() {
        const d = this._scrapGroupDef();
        if (!d) return this.scrapFilteredRows;
        const active = this.scrapActiveGroupKey;
        return this.scrapFilteredRows.filter(r => d.accessor(r).includes(active));
    }
    get scrapSortedRows() { return sortRows(this.scrapGroupedRows, this.state.scrapSortCol, this.state.scrapSortDir); }
    get scrapPagedRows()  { return pageSlice(this.scrapSortedRows, this.state.scrapPage, this.state.pageSize); }
    get scrapTotalPages() { return this.scrapPager.totalPages; }
    get scrapHasNextPage(){ return this.scrapPager.hasNext; }
    get scrapHasPrevPage(){ return this.scrapPager.hasPrev; }
    scrapNextPage() { this.scrapPager.next(); }
    scrapPrevPage() { this.scrapPager.prev(); }

    /** KPIs del scrap: describen las filas visibles. Solo hay terminados (los
     *  insumos se excluyen en backend). La tasa = desecho ÷ (producido + desecho)
     *  de los productos visibles. */
    get scrapKpis() {
        const rows = this.scrapGroupedRows;
        let qty = 0, prod = 0;
        for (const r of rows) { qty += r.qty || 0; prod += r.producido || 0; }
        const denom = qty + prod;
        return {
            qty:       Math.round(qty * 100) / 100,
            products:  rows.length,
            producido: Math.round(prod * 100) / 100,
            tasa:      denom > 0 ? Math.round(qty / denom * 1000) / 10 : null,
        };
    }
    /** Semáforo de la tasa de scrap: acá "más alto = peor". */
    scrapRateClass(pct) {
        if (pct === null || pct === undefined) return "text-muted";
        if (pct >= 10) return "text-danger fw-semibold";
        if (pct >= 3) return "text-warning fw-semibold";
        return "text-success fw-semibold";
    }
    get scrapKpiCards() {
        const k = this.scrapKpis;
        return [
            { key: "qty",      label: "Desecho total",   value: fmt(k.qty),      cls: "text-danger fw-semibold" },
            { key: "tasa",     label: "Tasa de scrap %", value: k.tasa === null ? "s/prod" : fmtPct(k.tasa),
              cls: this.scrapRateClass(k.tasa) },
            { key: "producido", label: "Producido",      value: fmt(k.producido), cls: "" },
            { key: "products", label: "Productos",       value: fmt(k.products), cls: "" },
        ];
    }
    scrapKpiTooltip(key) {
        const k = this.scrapKpis;
        const scope = `${k.products} producto(s) visible(s)`;
        switch (key) {
            case "qty":
                return `Cantidad total desechada de ${scope} en el período (desechos validados de productos terminados)\nSuma de la cantidad de cada desecho\n→ ${fmt(k.qty)} u.\nOjo: suma unidades posiblemente mixtas (distintos productos/UdM); leer como tendencia, no como magnitud única.`;
            case "tasa":
                return `Qué parte de lo procesado se desechó (dimensión Calidad del OEE), sobre los productos terminados visibles\nDesecho ÷ (Producido + Desecho) × 100\n→ ${fmt(k.qty)} ÷ (${fmt(k.producido)} + ${fmt(k.qty)}) × 100 = ${k.tasa === null ? "s/prod" : fmtPct(k.tasa)}\nVerde < 3% · Amarillo < 10% · Rojo ≥ 10%. «s/prod» = no hubo producción en el rango. Unidades mixtas: leer como indicador.`;
            case "producido":
                return `Cantidad producida de los productos visibles en el período (denominador de la tasa)\nSuma de lo producido de cada producto\n→ ${fmt(k.producido)} u.`;
            case "products":
                return `Productos terminados distintos con al menos un desecho en el período\nConteo de productos únicos\n→ ${fmt(k.products)} producto(s)`;
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
            producido:  "Cantidad producida del producto en el período (mismo criterio de fechas que el resto del panel). 0 = insumo sin producción propia.",
            tasa:       "Tasa de scrap: Desecho ÷ (Producido + Desecho) × 100. «—» = insumo sin producción en el rango.",
            ops:        "Cantidad de operaciones de desecho del producto en el período.",
            pct:        "Participación del producto sobre la cantidad total desechada del período.",
        }[col.key] || col.label;
        return `${t} Clic en el encabezado para ordenar.`;
    }
    scrapCellValue(row, key) {
        if (key === "pct") return fmtPct(row.pct);
        if (key === "tasa") return row.tasa === null || row.tasa === undefined ? "—" : fmtPct(row.tasa);
        if (key === "qty" || key === "ops" || key === "producido") return fmt(row[key]);
        return row[key] || "—";
    }
    scrapCellClass(row, key) {
        if (key === "tasa") return this.scrapRateClass(row.tasa);
        return "";
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

    // ════════════════ Helpers compartidos por las nuevas pestañas ════════════════

    /** Color de una tasa (más alto = mejor): verde ≥ verde, amarillo ≥ aviso,
     *  rojo por debajo; gris si no aplica. Inverso a cargaClass. */
    rateClass(pct, green, warn) {
        if (pct === null || pct === undefined) return "text-muted";
        if (pct >= green) return "text-success fw-semibold";
        if (pct >= warn) return "text-warning fw-semibold";
        return "text-danger fw-semibold";
    }
    _monthLabels(t) {
        return (t || []).map(m => {
            const [y, mo] = m.ym.split("-");
            return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
        });
    }
    /** Dominio de OFs que solapan el rango (para los drills de OFs/Comparativo). */
    _moRangeDomain() {
        return [
            ["state", "not in", ["cancel", "draft"]],
            ["date_start", "<=", this.state.dateTo + " 23:59:59"],
            "|", ["date_finished", ">=", this.state.dateFrom + " 00:00:00"], ["date_finished", "=", false],
        ];
    }
    _openMos(ids, name) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.production",
            domain: [...this._moRangeDomain(), ["product_id", "in", ids]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
    _openWorkorders(ids, name) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.workorder",
            domain: [["production_id.product_id", "in", ids], ["state", "!=", "cancel"]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
    _openProductivity(ids, name) {
        this.action.doAction({
            type: "ir.actions.act_window", name,
            res_model: "mrp.workcenter.productivity",
            domain: [["workcenter_id", "in", ids],
                     ["date_start", ">=", this.state.dateFrom + " 00:00:00"],
                     ["date_start", "<=", this.state.dateTo + " 23:59:59"]],
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    // ════════════════ Config de las pestañas con TableCtl ════════════════

    _ofCfg() {
        return {
            prefix: "of", cols: OF_COLS, numCols: OF_NUM_COLS,
            groupDefs: [SECTOR_GROUP, CATEGORY_GROUP], textFields: ["name", "category"],
            placeholder: "Buscar producto o categoría…", emptyMsg: "Sin OFs en el período/filtros.",
            unit: "producto(s)",
            computeKpis: (rows) => {
                let ofs = 0, term = 0, curso = 0, atr = 0, prog = 0, prod = 0;
                for (const r of rows) {
                    ofs += r.ofs || 0; term += r.terminadas || 0; curso += r.en_curso || 0;
                    atr += r.atrasadas || 0; prog += r.programado || 0; prod += r.producido || 0;
                }
                return { ofs, terminadas: term, en_curso: curso, atrasadas: atr,
                         programado: Math.round(prog * 100) / 100, producido: Math.round(prod * 100) / 100,
                         products: rows.length };
            },
            kpiCards: (k) => [
                { key: "ofs",        label: "OFs",        value: fmt(k.ofs),        cls: "" },
                { key: "terminadas", label: "Terminadas", value: fmt(k.terminadas), cls: "text-success fw-semibold" },
                { key: "en_curso",   label: "En curso",   value: fmt(k.en_curso),   cls: "" },
                { key: "atrasadas",  label: "Atrasadas",  value: fmt(k.atrasadas),  cls: k.atrasadas > 0 ? "text-danger fw-semibold" : "" },
                { key: "producido",  label: "Producido",  value: fmt(k.producido),  cls: "" },
            ],
            kpiTooltip: (key, k) => {
                const scope = `${k.products} producto(s) visible(s)`;
                switch (key) {
                    case "ofs":        return `OFs del período de ${scope} (excluye canceladas y borradores)\nConteo de órdenes de fabricación\n→ ${fmt(k.ofs)} OF(s)`;
                    case "terminadas": return `OFs terminadas (estado Hecho) de ${scope}\nConteo de OFs en estado done\n→ ${fmt(k.terminadas)}`;
                    case "en_curso":   return `OFs en proceso o por cerrar de ${scope}\nConteo de OFs en estado en curso / por cerrar\n→ ${fmt(k.en_curso)}`;
                    case "atrasadas":  return `OFs abiertas cuya fecha de fin ya venció, de ${scope}\nConteo de OFs no terminadas con fecha de fin < ahora\n→ ${fmt(k.atrasadas)}`;
                    case "producido":  return `Cantidad producida acumulada de ${scope}\nSuma de la cantidad producida de cada OF\n→ ${fmt(k.producido)} u.\nOjo: suma unidades posiblemente mixtas.`;
                }
                return "";
            },
            colTitle: (col) => {
                const t = {
                    name: "Producto fabricado. El botón abre sus OFs del período.",
                    category: "Categoría de producto.", uom: "Unidad de medida.",
                    ofs: "Cantidad de OFs del producto en el período.",
                    programado: "Cantidad total programada (suma de la cantidad a producir de las OFs).",
                    producido: "Cantidad total producida (suma de la cantidad producida de las OFs).",
                    avance_pct: "Producido ÷ Programado × 100.",
                    terminadas: "OFs terminadas (estado Hecho).", en_curso: "OFs en proceso o por cerrar.",
                    atrasadas: "OFs abiertas con fecha de fin vencida.",
                }[col.key] || col.label;
                return `${t} Clic en el encabezado para ordenar.`;
            },
            cellValue: (row, key) => {
                if (key === "avance_pct") return fmtPct(row.avance_pct);
                if (["programado", "producido", "ofs", "terminadas", "en_curso", "atrasadas"].includes(key)) return fmt(row[key]);
                return row[key] || "—";
            },
            cellClass: (row, key) => (key === "atrasadas" && row.atrasadas > 0) ? "text-danger fw-semibold" : "",
            onViewAll: (rows, w) => w._openMos(rows.map(r => r.product_id), "OFs del período"),
            onViewRow: (row, w) => w._openMos([row.product_id], `OFs — ${row.name}`),
        };
    }

    _cmpCfg() {
        const WEIGHT_LABELS = { qty: "cantidad", cost: "costo estándar", sale_price: "precio de venta", wc_hours: "horas de ruta" };
        return {
            prefix: "cmp", cols: CMP_COLS, numCols: CMP_NUM_COLS,
            groupDefs: [SECTOR_GROUP], textFields: ["name"],
            placeholder: "Buscar producto…", emptyMsg: "Sin datos de comparativo en el período/filtros.",
            unit: "producto(s)",
            // KPIs ponderados del backend: describen TODO el período (no las filas
            // filtradas), porque la ponderación por valor/horas vive en el servidor.
            computeKpis: (rows, w) => w.state.cmpKpisData || {},
            kpiCards: (k, w) => [
                { key: "planned",   label: "Programado",     value: fmt(k.planned),  cls: "" },
                { key: "produced",  label: "Producido",      value: fmt(k.produced), cls: "" },
                { key: "pct",       label: "Cumplimiento %", value: k.pct === null || k.pct === undefined ? "s/plan" : fmtPct(k.pct),
                  cls: w.rateClass(k.pct, k.pct_green || 90, k.pct_warn || 50) },
                { key: "on_target", label: "En target",      value: `${k.on_target || 0}/${k.planned_products || 0}`, cls: "" },
                { key: "desvio",    label: "Desvío",         value: fmt(k.desvio),   cls: k.desvio > 0 ? "text-warning fw-semibold" : "" },
            ],
            kpiTooltip: (key, k) => {
                const wl = WEIGHT_LABELS[k.weight_mode] || k.weight_mode || "costo estándar";
                switch (key) {
                    case "planned":   return `Programado ponderado del período (por ${wl})\nΣ (cantidad programada × peso del producto)\n→ ${fmt(k.planned)}`;
                    case "produced":  return `Producido ponderado del período (por ${wl})\nΣ (cantidad producida × peso del producto)\n→ ${fmt(k.produced)}`;
                    case "pct":       return `Cumplimiento ponderado del período (por ${wl})${k.fill_cap ? ", con tope 100% por producto" : ""}\nProducido ÷ Programado × 100\n→ ${k.pct === null || k.pct === undefined ? "s/plan" : fmtPct(k.pct)}\nVerde ≥ ${k.pct_green}% · Amarillo ≥ ${k.pct_warn}% (umbrales de Ajustes)`;
                    case "on_target": return `Productos que alcanzaron el umbral verde (≥ ${k.pct_green}%)\nConteo mix-justo (cada producto cuenta una vez)\n→ ${k.on_target || 0} de ${k.planned_products || 0} con plan`;
                    case "desvio":    return `Faltante ponderado: Programado − Producido del período\n→ ${fmt(k.desvio)}${k.excluded ? `\n${k.excluded} producto(s) sin peso para el criterio elegido (no ponderan).` : ""}`;
                }
                return "";
            },
            colTitle: (col) => {
                const t = {
                    name: "Producto fabricado. El botón abre sus OFs del período.",
                    uom: "Unidad de medida.",
                    programado: "Cantidad programada del producto (sin ponderar).",
                    producido: "Cantidad producida del producto (sin ponderar).",
                    desvio: "Programado − Producido del producto.",
                    pct: "Producido ÷ Programado × 100 del producto. «s/plan» = producido sin cantidad programada.",
                }[col.key] || col.label;
                return `${t} Clic en el encabezado para ordenar.`;
            },
            cellValue: (row, key) => {
                if (key === "pct") return row.pct === null || row.pct === undefined ? "s/plan" : fmtPct(row.pct);
                if (["programado", "producido", "desvio"].includes(key)) return fmt(row[key]);
                return row[key] || "—";
            },
            cellClass: (row, key, w) => {
                if (key === "pct") return w.rateClass(row.pct, w.state.cmpGreen, w.state.cmpWarn);
                if (key === "desvio" && row.desvio > 0) return "text-warning";
                return "";
            },
            onViewAll: (rows, w) => w._openMos(rows.map(r => r.product_id), "OFs del comparativo"),
            onViewRow: (row, w) => w._openMos([row.product_id], `OFs — ${row.name}`),
        };
    }

    _efCfg() {
        return {
            prefix: "ef", cols: EF_COLS, numCols: EF_NUM_COLS,
            groupDefs: [SECTOR_GROUP, CATEGORY_GROUP], textFields: ["name", "category"],
            placeholder: "Buscar producto o categoría…", emptyMsg: "Sin OT con horas en el período/filtros.",
            unit: "producto(s)",
            computeKpis: (rows) => {
                let plan = 0, real = 0, ofs = 0;
                for (const r of rows) { plan += r.plan_h || 0; real += r.real_h || 0; ofs += r.ofs || 0; }
                return { plan_h: Math.round(plan * 10) / 10, real_h: Math.round(real * 10) / 10,
                         eficiencia: plan > 0 ? Math.round(real / plan * 1000) / 10 : null, products: rows.length };
            },
            kpiCards: (k) => [
                { key: "plan_h",     label: "Plan (h)",     value: fmt(k.plan_h),     cls: "" },
                { key: "real_h",     label: "Real (h)",     value: fmt(k.real_h),     cls: "" },
                { key: "eficiencia", label: "Eficiencia %", value: fmtPct(k.eficiencia), cls: "" },
                { key: "products",   label: "Productos",    value: fmt(k.products),   cls: "" },
            ],
            kpiTooltip: (key, k) => {
                const scope = `${k.products} producto(s) visible(s)`;
                switch (key) {
                    case "plan_h":     return `Horas planificadas de ${scope}: duración esperada de las OT (criterio de fechas de Ajustes)\nSuma de la duración esperada\n→ ${fmt(k.plan_h)} h`;
                    case "real_h":     return `Horas reales registradas en las OT de ${scope}\nSuma de la duración real\n→ ${fmt(k.real_h)} h`;
                    case "eficiencia": return `Cuánto se tardó respecto de lo previsto, en ${scope}\nReal ÷ Planificado × 100\n→ ${fmt(k.real_h)} ÷ ${fmt(k.plan_h)} × 100 = ${fmtPct(k.eficiencia)}\nPor encima de 100% se tardó más de lo previsto.`;
                    case "products":   return `Productos con OT y horas en el período\nConteo de productos únicos\n→ ${fmt(k.products)}`;
                }
                return "";
            },
            colTitle: (col) => {
                const t = {
                    name: "Producto fabricado. El botón abre las OT de sus OFs.",
                    category: "Categoría de producto.",
                    ofs: "Cantidad de OFs del producto con OT en el período.",
                    plan_h: "Horas planificadas (duración esperada de las OT).",
                    real_h: "Horas reales registradas en las OT.",
                    eficiencia: "Real ÷ Planificado × 100. Por encima de 100% se tardó más de lo previsto.",
                }[col.key] || col.label;
                return `${t} Clic en el encabezado para ordenar.`;
            },
            cellValue: (row, key) => {
                if (key === "eficiencia") return fmtPct(row.eficiencia);
                if (["plan_h", "real_h", "ofs"].includes(key)) return fmt(row[key]);
                return row[key] || "—";
            },
            onViewAll: (rows, w) => w._openWorkorders(rows.map(r => r.product_id), "OT del período"),
            onViewRow: (row, w) => w._openWorkorders([row.product_id], `OT — ${row.name}`),
        };
    }

    _oeeCfg() {
        const oeeCls = (pct, w) => w.rateClass(pct, w.state.oeeGreen, w.state.oeeWarn);
        return {
            prefix: "oee", cols: OEE_COLS, numCols: OEE_NUM_COLS,
            groupDefs: [SECTOR_GROUP], textFields: ["name"],
            placeholder: "Buscar centro de trabajo…", emptyMsg: "Sin registros de productividad en el período/filtros.",
            unit: "centro(s)", rowKey: "wc_id",
            computeKpis: (rows) => {
                let prod = 0, ppt = 0, run = 0, net = 0, disp = 0, allav = 0;
                for (const r of rows) {
                    prod += r.productive_h || 0; ppt += r.ppt_h || 0; run += r.run_h || 0;
                    net += r.net_h || 0; disp += r.disponible_h || 0; allav += r.allavail_h || 0;
                }
                const p = (n, d) => d > 0 ? Math.round(n / d * 1000) / 10 : null;
                return {
                    oee: p(prod, ppt), ooe: p(prod, disp), teep: p(prod, allav),
                    availability: p(run, ppt), performance: p(net, run), quality: p(prod, net),
                    productive: Math.round(prod * 10) / 10, wcs: rows.length,
                };
            },
            kpiCards: (k, w) => [
                { key: "oee",        label: "OEE %",         value: fmtPct(k.oee),  cls: oeeCls(k.oee, w) },
                { key: "ooe",        label: "OOE %",         value: fmtPct(k.ooe),  cls: oeeCls(k.ooe, w) },
                { key: "teep",       label: "TEEP %",        value: fmtPct(k.teep), cls: oeeCls(k.teep, w) },
                { key: "productive", label: "Productivo (h)", value: fmt(k.productive), cls: "" },
                { key: "wcs",        label: "Centros",       value: fmt(k.wcs),     cls: "" },
            ],
            kpiTooltip: (key, k, w) => {
                const scope = `${k.wcs} centro(s) visible(s)`;
                const bench = `Referencia world-class: verde ≥ ${w.state.oeeGreen}% · amarillo ≥ ${w.state.oeeWarn}%.`;
                switch (key) {
                    case "oee":  return `Efectividad global del equipo en ${scope}, contra el tiempo REGISTRADO de producción (PPT)\nDisponibilidad × Rendimiento × Calidad = Productivo ÷ PPT\n→ ${fmtPct(k.availability)} × ${fmtPct(k.performance)} × ${fmtPct(k.quality)} = ${fmtPct(k.oee)}\n${bench}`;
                    case "ooe":  return `Efectividad contra el tiempo de TURNO de calendario (más exigente que OEE)\nProductivo ÷ horas de turno\n→ ${fmtPct(k.ooe)}\nCae por debajo del OEE cuando el turno tiene tiempo no registrado.`;
                    case "teep": return `Efectividad contra el calendario COMPLETO (24×7): cuánto de la capacidad teórica se aprovecha\nProductivo ÷ (24 h × días)\n→ ${fmtPct(k.teep)}\nEl más exigente de los tres.`;
                    case "productive": return `Horas plenamente productivas de ${scope} (tiempo registrado como productivo)\nSuma del tiempo productivo\n→ ${fmt(k.productive)} h`;
                    case "wcs": return `Centros de trabajo con registro de productividad en el período\n→ ${fmt(k.wcs)} centro(s)`;
                }
                return "";
            },
            colTitle: (col) => {
                const t = {
                    name: "Centro de trabajo. El botón abre sus registros de productividad del período.",
                    availability: "Disponibilidad = tiempo corriendo ÷ tiempo registrado. Pérdidas: paros/averías/cambios.",
                    performance: "Rendimiento = tiempo neto ÷ tiempo corriendo. Pérdidas: micro-paradas y velocidad reducida.",
                    quality: "Calidad = tiempo de producto bueno ÷ tiempo neto. Pérdidas: scrap/reproceso.",
                    oee: "OEE = Disp. × Rend. × Calidad, contra el tiempo registrado de producción.",
                    ooe: "OOE = productivo ÷ horas de turno del calendario (más exigente que OEE).",
                    teep: "TEEP = productivo ÷ calendario 24×7 (el más exigente).",
                    productive_h: "Horas plenamente productivas registradas.",
                }[col.key] || col.label;
                return `${t} Clic en el encabezado para ordenar.`;
            },
            cellValue: (row, key) => {
                if (["availability", "performance", "quality", "oee", "ooe", "teep"].includes(key)) return fmtPct(row[key]);
                if (key === "productive_h") return fmt(row[key]);
                return row[key] || "—";
            },
            cellClass: (row, key, w) => {
                if (["oee", "ooe", "teep", "availability", "performance", "quality"].includes(key)) {
                    return w.rateClass(row[key], w.state.oeeGreen, w.state.oeeWarn);
                }
                return "";
            },
            onViewAll: (rows, w) => w._openProductivity(rows.map(r => r.wc_id), "Registros de productividad del período"),
            onViewRow: (row, w) => w._openProductivity([row.wc_id], `Productividad — ${row.name}`),
        };
    }

    // ════════════════ Carga de datos de las nuevas pestañas ════════════════

    async _loadOf() {
        this.state.ofLoading = true; this.state.ofError = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_of_analysis", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_of_trend", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
            ]);
            this.state.ofRows = table.rows || [];
            this.state.ofTrend = trend.trend || [];
            this.state.ofPage = 1; this.state.ofLoaded = true;
            this._ofChartDirty = true; this._renderOfTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.ofError = (e && e.data && e.data.message) || e.message || String(e);
        } finally { this.state.ofLoading = false; }
    }

    async _loadCmp() {
        this.state.cmpLoading = true; this.state.cmpError = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_comparison_analysis", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_comparison_trend", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
            ]);
            this.state.cmpRows = table.rows || [];
            this.state.cmpKpisData = table.kpis || {};
            this.state.cmpGreen = (table.kpis && table.kpis.pct_green) || 90;
            this.state.cmpWarn  = (table.kpis && table.kpis.pct_warn) || 50;
            this.state.cmpTruncated = !!table.truncated; this.state.cmpTotal = table.total || 0;
            this.state.cmpTrend = trend.trend || [];
            this.state.cmpPage = 1; this.state.cmpLoaded = true;
            this._cmpChartDirty = true; this._renderCmpTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.cmpError = (e && e.data && e.data.message) || e.message || String(e);
        } finally { this.state.cmpLoading = false; }
    }

    async _loadEf() {
        this.state.efLoading = true; this.state.efError = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_efficiency_analysis", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_efficiency_trend", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
            ]);
            this.state.efRows = table.rows || [];
            this.state.efTrend = trend.trend || [];
            this.state.efPage = 1; this.state.efLoaded = true;
            this._efChartDirty = true; this._renderEfTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.efError = (e && e.data && e.data.message) || e.message || String(e);
        } finally { this.state.efLoading = false; }
    }

    async _loadOee() {
        this.state.oeeLoading = true; this.state.oeeError = null;
        try {
            const [table, trend] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_oee_analysis", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
                this.orm.call("mrp.planner.dashboard", "get_oee_trend", [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]),
            ]);
            this.state.oeeRows = table.rows || [];
            this.state.oeeHasData = !!table.has_data;
            this.state.oeeGreen = table.oee_green || 85;
            this.state.oeeWarn  = table.oee_warn || 60;
            this.state.oeeTrend = trend.trend || [];
            this.state.oeePage = 1; this.state.oeeLoaded = true;
            this._oeeChartDirty = true; this._renderOeeTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.oeeError = (e && e.data && e.data.message) || e.message || String(e);
        } finally { this.state.oeeLoading = false; }
    }

    async _loadEvol() {
        this.state.evolLoading = true; this.state.evolError = null;
        try {
            const data = await this.orm.call("mrp.planner.dashboard", "get_evolution_analysis",
                                             [this.state.dateFrom, this.state.dateTo, this.state.tagId || null]);
            this.state.evolRows = data.rows || [];
            this.state.evolWarnPct = data.warn_pct || 70;
            this.state.evolCritPct = data.crit_pct || 90;
            this.state.evolGreen   = data.cumpl_green || 90;
            this.state.evolLoaded = true;
            this._evolChartDirty = true; this._renderEvolTrend();
        } catch (e) {
            console.error("[ProdAnalysis]", e);
            this.state.evolError = (e && e.data && e.data.message) || e.message || String(e);
        } finally { this.state.evolLoading = false; }
    }

    // ════════════════ Gráficos de las nuevas pestañas ════════════════

    _renderOfTrend() {
        const el = this.ofTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.ofTrendChart) { this.ofTrendChart.destroy(); this.ofTrendChart = null; }
        this._ofChartDirty = false;
        const t = this.state.ofTrend || [];
        this.ofTrendChart = new Chart(el, {
            type: "line",
            data: {
                labels: this._monthLabels(t),
                datasets: [
                    { label: "OFs", data: t.map(m => m.ofs), borderColor: "#0d6efd",
                      backgroundColor: "rgba(13,110,253,0.10)", fill: true, tension: 0.25, pointRadius: 3 },
                    { label: "Terminadas", data: t.map(m => m.terminadas), borderColor: "#198754",
                      backgroundColor: "rgba(25,135,84,0.10)", fill: true, tension: 0.25, pointRadius: 3 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { min: 0, ticks: { precision: 0 } } },
                plugins: { legend: { display: true, position: "bottom" } },
            },
        });
    }

    _renderCmpTrend() {
        const el = this.cmpTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.cmpTrendChart) { this.cmpTrendChart.destroy(); this.cmpTrendChart = null; }
        this._cmpChartDirty = false;
        const t = this.state.cmpTrend || [];
        this.cmpTrendChart = new Chart(el, {
            type: "line",
            data: {
                labels: this._monthLabels(t),
                datasets: [{
                    label: "Cumplimiento %", data: t.map(m => m.pct),
                    borderColor: "#6610f2", backgroundColor: "rgba(102,16,242,0.10)",
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
                        return m.pct === null ? "Sin plan"
                            : `${m.pct}% — prod ${fmt(m.producido)} / prog ${fmt(m.programado)}`;
                    } } },
                },
            },
        });
    }

    _renderEfTrend() {
        const el = this.efTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.efTrendChart) { this.efTrendChart.destroy(); this.efTrendChart = null; }
        this._efChartDirty = false;
        const t = this.state.efTrend || [];
        this.efTrendChart = new Chart(el, {
            type: "line",
            data: {
                labels: this._monthLabels(t),
                datasets: [{
                    label: "Eficiencia %", data: t.map(m => m.eficiencia),
                    borderColor: "#fd7e14", backgroundColor: "rgba(253,126,20,0.10)",
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
                        return m.eficiencia === null ? "Sin plan"
                            : `${m.eficiencia}% — real ${fmt(m.real_h)} h / plan ${fmt(m.plan_h)} h`;
                    } } },
                },
            },
        });
    }

    _renderOeeTrend() {
        const el = this.oeeTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.oeeTrendChart) { this.oeeTrendChart.destroy(); this.oeeTrendChart = null; }
        this._oeeChartDirty = false;
        const t = this.state.oeeTrend || [];
        this.oeeTrendChart = new Chart(el, {
            type: "line",
            data: {
                labels: this._monthLabels(t),
                datasets: [
                    { label: "OEE %",  data: t.map(m => m.oee),  borderColor: "#198754",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                    { label: "OOE %",  data: t.map(m => m.ooe),  borderColor: "#0d6efd",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                    { label: "TEEP %", data: t.map(m => m.teep), borderColor: "#6c757d",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
                plugins: { legend: { display: true, position: "bottom" } },
            },
        });
    }

    _renderEvolTrend() {
        const el = this.evolTrendRef.el;
        if (!el || typeof Chart === "undefined") return;
        if (this.evolTrendChart) { this.evolTrendChart.destroy(); this.evolTrendChart = null; }
        this._evolChartDirty = false;
        const t = this.state.evolRows || [];
        this.evolTrendChart = new Chart(el, {
            type: "line",
            data: {
                labels: this._monthLabels(t),
                datasets: [
                    { label: "Carga %", data: t.map(m => m.carga_pct), borderColor: "#0d6efd",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                    { label: "Cumplimiento %", data: t.map(m => m.cumpl_pct), borderColor: "#6610f2",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                    { label: "Eficiencia %", data: t.map(m => m.efic_pct), borderColor: "#fd7e14",
                      backgroundColor: "transparent", spanGaps: true, tension: 0.25, pointRadius: 3 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { y: { min: 0, ticks: { callback: v => v + "%" } } },
                plugins: { legend: { display: true, position: "bottom" } },
            },
        });
    }

    // ════════════════ Evolución: tabla mensual (sin TableCtl) ════════════════

    get evolKpiCards() {
        const rows = this.state.evolRows || [];
        let ofs = 0, term = 0, prod = 0, scrap = 0;
        for (const r of rows) { ofs += r.ofs || 0; term += r.terminadas || 0; prod += r.producido || 0; scrap += r.scrap || 0; }
        return [
            { key: "ofs",        label: "OFs (período)", value: fmt(ofs),   cls: "",
              tip: `Total de OFs del período\nSuma de las OFs de cada mes\n→ ${fmt(ofs)}` },
            { key: "terminadas", label: "Terminadas",    value: fmt(term),  cls: "text-success fw-semibold",
              tip: `Total de OFs terminadas del período\nSuma mensual\n→ ${fmt(term)}` },
            { key: "producido",  label: "Producido",     value: fmt(prod),  cls: "",
              tip: `Producido ponderado acumulado del período\nSuma mensual\n→ ${fmt(prod)}` },
            { key: "scrap",      label: "Scrap",         value: fmt(scrap), cls: "text-danger fw-semibold",
              tip: `Cantidad desechada acumulada del período\nSuma mensual\n→ ${fmt(scrap)} u. (unidades mixtas)` },
        ];
    }
    evolColTitle(col) {
        const t = {
            ym: "Mes calendario del período.",
            ofs: "OFs del mes (criterio de fechas de Ajustes).",
            terminadas: "OFs terminadas (estado Hecho) en el mes.",
            producido: "Producido ponderado del mes (comparativo).",
            carga_pct: "Carga de CT del mes: planificado ÷ disponible × 100.",
            cumpl_pct: "Cumplimiento ponderado del mes: producido ÷ programado × 100.",
            efic_pct: "Eficiencia del mes: real ÷ planificado × 100.",
            scrap: "Cantidad desechada del mes (unidades mixtas).",
        }[col.key] || col.label;
        return t;
    }
    evolLabel(ym) {
        const [y, mo] = (ym || "-").split("-");
        return new Date(+y, +mo - 1, 1).toLocaleString("es", { month: "short", year: "2-digit" });
    }
    evolCellValue(row, key) {
        if (key === "ym") return this.evolLabel(row.ym);
        if (["carga_pct", "cumpl_pct", "efic_pct"].includes(key)) return fmtPct(row[key]);
        return fmt(row[key]);
    }
    evolCellClass(row, key) {
        if (key === "carga_pct") return this.cargaClass(row.carga_pct);
        if (key === "cumpl_pct") return this.rateClass(row.cumpl_pct, this.state.evolGreen, 50);
        return "";
    }
    get evolCols() { return EVOL_COLS; }
}

registry.category("view_widgets").add("production_analysis_widget", {
    component: ProductionAnalysisWidget,
});
