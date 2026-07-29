/**
 * @widget ForecastWidget
 * @description Widget de dashboard de forecast de producción. Muestra una tabla
 * mensualizada por producto con demanda forecast, cobertura de órdenes de fabricación
 * (OFs), entregas reales, stock actual, rotación y categoría ABC de ventas.
 * Permite filtrar por período, depósito, producto y agrupar por categoría.
 *
 * Métodos RPC que consume:
 *   - get_warehouses_for_forecast([]) → [{ id: Number, name: String }]
 *   - get_forecast_dashboard_data(periodFrom, periodTo, warehouseIds) → {
 *       months: String[],        // array de "YYYY-MM"
 *       rows: Object[],          // una fila por producto
 *       kpis: Object,            // totales globales
 *       warning_pct: Number,     // umbral amarillo de cobertura
 *       acc_formula: String,     // fórmula de precisión activa
 *       rotation_unit: String,   // 'months' | 'days'
 *       mo_states: String[]      // estados de OF considerados activos
 *     }
 *   - get_product_mos_for_forecast(productId, periodFrom, periodTo, warehouseIds)
 *       → [{ id, name, state, date_planned, qty_production, product_uom_qty }]
 *   - get_forecast_export(periodFrom, periodTo, warehouseIds) → { url: String }
 *
 * Props esperados:
 *   - record: Object — registro del dashboard (opcional); se usa para leer `can_edit_forecast`
 *
 * Lógica extraída a módulos hermanos:
 *   - forecast_formatters.js  — funciones puras de formateo y clases CSS
 *   - forecast_tooltips.js    — contenido de tooltips
 *   - forecast_export.js      — exportación Excel
 *   - forecast_drilldown.js   — drill-down de KPIs
 *   - forecast_filters.js     — filtros, ordenamiento y getters computados
 */

/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { PlannerSearchBar } from "./planner_search_bar";
import { useColManager } from "./column_manager";
import {
    moStateBadge, saleCatBadge, moCovPct, moCovPctCell, moCovPctRow,
    cellClassForPct, cellClassMonthly, cellClassTotal, cellClass, svcClass,
    accClass, fmtRotation, rotClass, fmtCoverage, covClass,
    demandGapClass, mosGapClass, fmtGapPct, fmt, fmtPct, fmtDate,
    sortIcon, colTitle,
} from "./forecast_formatters";
import {
    moTooltip, svcTooltip, rotHeaderTitle, rotTooltip,
    covTooltip, covHeaderTitle, accGlobalTooltip, accTooltip,
    fcKpiTooltip, demandGapTooltip, mosGapTooltip, accSecondaryPills,
} from "./forecast_tooltips";
import { downloadForecastExcel } from "./forecast_export";
import {
    openDrillForecast, openDrillMos, openDrillSoDemand, openDrillDelivered,
    openDrillDeliveredByOrderMonth,
    openDrillDemandDelivered, openDrillSoDemandNoFc, openDrillMosNoFc,
    openDrillDemandDeliveredNoFc, openDrillDeliveredNoFc,
} from "./forecast_drilldown";
import {
    baseFilteredRows, filteredRowsAll, filteredKpis, sortedRows, allGroupsForTabs,
    onPeriodFromChange, onPeriodToChange, onProductSearchInput, setSearch,
    toggleWhDropdown, toggleColsDropdown, toggleFilterDropdown, toggleGroupDropdown,
    toggleCol, setFilter, setGroupBy, setGroup,
    toggleWarehouse, clearWhFilter, onColHeaderClick, setSort,
} from "./forecast_filters";

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

const FC_STATIC_COLS = [
    { key: 'product',      label: 'Artículo', width: 200, fixed: true, align: 'start' },
    { key: 'saleCategory', label: 'Cat.',      width:  55, align: 'center' },
    { key: 'productCateg', label: 'Familia',   width: 120, align: 'start' },
    { key: 'productTypes', label: 'Tipo',      width: 120, align: 'start' },
    { key: 'listPrice',    label: 'P. venta',  width:  90, align: 'end' },
    { key: 'stock',        label: 'Stock',     width:  80, align: 'end' },
    { key: 'rotation',     label: 'Rot.',      width:  75, align: 'end' },
    { key: 'coverage',     label: 'Cob.',      width:  75, align: 'end' },
    { key: 'demand',       label: 'Demanda',   width:  90, align: 'end' },
];

const FC_SORT_KEYS = {
    product:      'product',
    saleCategory: 'sale_category',
    productCateg: 'product_categ',
    productTypes: 'product_types',
    listPrice:    'list_price',
    stock:        'stock_qty',
    rotation:     'rotation_days',
    coverage:     'coverage_days',
    demand:       'total_so_demand',
};

function monthLabel(ym) {
    const [y, m] = ym.split('-');
    return `${MONTHS_ES[parseInt(m) - 1]} ${y}`;
}

function todayYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function addMonthsLastDayYMD(ymd, n) {
    const [y, m] = ymd.split('-').map(Number);
    // new Date(y, m-1+n+1, 0) → último día del mes destino
    const last = new Date(y, m - 1 + n + 1, 0);
    return `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
}

function firstOfMonthYMD() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

function lastOfMonthYMD() {
    const d = new Date();
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
}

class ForecastWidget extends Component {
    static template = "odoo_mrp_planner.ForecastWidget";
    static components = { PlannerSearchBar };
    static props = { record: { type: Object, optional: true }, "*": true };

    setup() {
        this.orm       = useService("orm");
        this.action    = useService("action");
        this.cols      = useColManager('forecast_static', FC_STATIC_COLS);
        this.fcSortKeys = FC_SORT_KEYS;

        this.state = useState({
            loading:            true,
            loadError:          null,
            periodFrom:         firstOfMonthYMD(),
            periodTo:           lastOfMonthYMD(),
            warehouseIds:       [],
            warehouses:         [],
            whDropdownOpen:     false,
            whSearch:           "",
            productSearch:      "",
            colsDropdownOpen:   false,
            filterDropdownOpen: false,
            groupDropdownOpen:  false,
            activeFilter:       null,
            groupBy:            null,
            selectedGroup:      null,
            visibleCols: {
                forecast:         true,
                mos:              true,
                delivered:        true,
                demand_delivered: true,
                stock:            true,
                rotation:      true,
                coverage:      true,
                total:         true,
                saleCategory:  false,
                productCateg:  false,
                productTypes:  false,
                listPrice:     true,
                demand:        false,
            },
            sortCol:          'product',
            sortDir:          'asc',
            page:             1,
            pageSize:         50,
            data:             null,
            canEdit:          true,
            expandedProducts: {},
            mosByProduct:     {},
            mosLoading:       {},
            delBreakdownOpen: false,   // "Ver →" de Entregas físicas reemplaza los KPIs por el desglose
            kpiZoneMinHeight: 0,       // alto del bloque de KPIs, para que el desglose no achique el contenedor
        });

        this._closeAll = () => {
            this.state.whDropdownOpen     = false;
            this.state.whSearch           = "";
            this.state.colsDropdownOpen   = false;
            this.state.filterDropdownOpen = false;
            this.state.groupDropdownOpen  = false;
        };

        this._loadDebounceTimer = null;
        this._loadDebounced = () => {
            clearTimeout(this._loadDebounceTimer);
            this._loadDebounceTimer = setTimeout(() => this._load(), 400);
        };

        onMounted(() => {
            this._init();
            document.addEventListener('click', this._closeAll);
        });
        onWillUnmount(() => {
            document.removeEventListener('click', this._closeAll);
            clearTimeout(this._loadDebounceTimer);
        });
    }

    async _init() {
        try {
            const [whs] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_warehouses_for_forecast", []),
                this._load(),
            ]);
            this.state.warehouses = whs;
            const rec = this.props.record;
            if (rec && rec.data) {
                this.state.canEdit = rec.data.can_edit_forecast;
            }
        } catch (e) {
            if (e.message !== "Component is destroyed") throw e;
        }
    }

    async _load() {
        this.state.loading      = true;
        this.state.loadError    = null;
        this.state.page         = 1;
        this.state.mosByProduct = {};
        this.state.expandedProducts = {};
        try {
            const d = await this.orm.call(
                "mrp.planner.dashboard",
                "get_forecast_dashboard_data",
                [this.state.periodFrom, this.state.periodTo, this.state.warehouseIds],
            );
            this.state.data = d;
        } catch (e) {
            console.error("[ForecastWidget]", e);
            this.state.loadError = (e && e.data && e.data.message) || e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filtros / sort — delegates a forecast_filters.js ─────────────────────
    onPeriodFromChange(ev)   { return onPeriodFromChange(this, ev); }
    onPeriodToChange(ev)     { return onPeriodToChange(this, ev); }
    onProductSearchInput(ev) { return onProductSearchInput(this, ev); }
    setSearch(text)          { return setSearch(this, text); }
    toggleWhDropdown(ev)     { return toggleWhDropdown(this, ev); }
    toggleColsDropdown(ev)   { return toggleColsDropdown(this, ev); }
    toggleFilterDropdown(ev) { return toggleFilterDropdown(this, ev); }
    toggleGroupDropdown(ev)  { return toggleGroupDropdown(this, ev); }
    toggleCol(colKey)        { return toggleCol(this, colKey); }
    setFilter(key)           { return setFilter(this, key); }
    setGroupBy(key)          { return setGroupBy(this, key); }
    setGroup(key)            { return setGroup(this, key); }
    toggleWarehouse(ev)      { return toggleWarehouse(this, ev); }
    clearWhFilter()          { return clearWhFilter(this); }
    onColHeaderClick(col)    { return onColHeaderClick(this, col); }
    setSort(col)             { return setSort(this, col); }

    // ── Colspan getters ───────────────────────────────────────────────────────
    get monthColspan() {
        let n = 0;
        if (this.state.visibleCols.forecast)         n++;
        if (this.state.visibleCols.mos)              n++;
        if (this.state.visibleCols.delivered)        n++;
        if (this.state.visibleCols.demand_delivered) n++;
        return n || 1;
    }
    get showForecastAcc() {
        return this.state.visibleCols.total &&
               this.state.visibleCols.forecast &&
               this.state.visibleCols.delivered;
    }
    get totalColspan()  { return this.monthColspan + (this.showForecastAcc ? 1 : 0); }
    get showTotal() {
        return this.state.visibleCols.total &&
               (this.state.visibleCols.forecast         ||
                this.state.visibleCols.mos              ||
                this.state.visibleCols.delivered        ||
                this.state.visibleCols.demand_delivered);
    }
    get tableColspan() {
        const n = this.state.data ? this.state.data.months.length : 0;
        let cols = this.staticVisibleCols.length;
        cols += n * this.monthColspan;
        if (this.showTotal) cols += this.totalColspan;
        return cols;
    }

    get staticVisibleCols() {
        return this.cols.visibleCols().filter(col => {
            if (col.key === 'product') return true;
            return !!this.state.visibleCols[col.key];
        });
    }
    colTitle(col) { return colTitle(col, this.rotHeaderTitle, this.covHeaderTitle); }
    sortIcon(col) { return sortIcon(col, this.state.sortCol, this.state.sortDir); }

    // ── Computed getters — delegates a forecast_filters.js ───────────────────
    get sortedRows()       { return sortedRows(this); }
    get baseFilteredRows() { return baseFilteredRows(this); }
    get filteredRowsAll()  { return filteredRowsAll(this); }
    get filteredKpis()     { return filteredKpis(this); }

    /** Abre el desglose de entregas fijando el alto actual del bloque de KPIs
     *  para que el contenedor no se achique al reemplazarlos. */
    openDelBreakdown() {
        const el = this.kpiZoneRef && this.kpiZoneRef.el;
        if (el) this.state.kpiZoneMinHeight = el.offsetHeight;
        this.state.delBreakdownOpen = true;
    }

    /**
     * Filas del resumen "Entregas físicas por mes de pedido": una por mes de
     * confirmación del pedido de origen (ordenadas cronológicamente) más la
     * cubeta '' de salidas sin pedido asociado al final. Mismo dato agregado
     * que el tooltip del KPI Entregas físicas.
     * @returns {Array<{key: string, label: string, qty: number}>}
     */
    get delByOrderMonthRows() {
        const byMonth = this.filteredKpis.del_by_order_month || {};
        const rows = Object.keys(byMonth).filter(k => k).sort().map(ym => {
            const [y, m] = ym.split('-');
            const label = new Date(+y, +m - 1, 1).toLocaleString('es', { month: 'long', year: 'numeric' });
            return { key: ym, label: label.charAt(0).toUpperCase() + label.slice(1), qty: byMonth[ym] };
        });
        if (byMonth['']) {
            rows.push({ key: '', label: 'Sin pedido asociado', qty: byMonth[''] });
        }
        return rows;
    }
    get allGroupsForTabs() { return allGroupsForTabs(this); }

    // ── Paginación ────────────────────────────────────────────────────────────
    get filteredRows() {
        const all   = this.sortedRows;
        const start = (this.state.page - 1) * this.state.pageSize;
        return all.slice(start, start + this.state.pageSize);
    }
    get totalPages()  { return Math.max(1, Math.ceil(this.filteredRowsAll.length / this.state.pageSize)); }
    get hasNextPage() { return this.state.page < this.totalPages; }
    get hasPrevPage() { return this.state.page > 1; }
    nextPage() { if (this.hasNextPage) this.state.page++; }
    prevPage() { if (this.hasPrevPage) this.state.page--; }
    get tableItems() { return this.filteredRows.map(r => ({ ...r, _type: 'row' })); }

    // ── Depósito ──────────────────────────────────────────────────────────────
    get filteredWarehouses() {
        const q = this.state.whSearch.toLowerCase();
        if (!q) return this.state.warehouses;
        return this.state.warehouses.filter(w => w.name.toLowerCase().includes(q));
    }
    get selectedWhLabel() {
        const ids = this.state.warehouseIds;
        if (!ids.length) return 'Todos los depósitos';
        if (ids.length === 1) {
            const wh = this.state.warehouses.find(w => w.id === ids[0]);
            return wh ? wh.name : '1 seleccionado';
        }
        return `${ids.length} depósitos`;
    }

    // ── Navegación ────────────────────────────────────────────────────────────
    openProduct(row) {
        this.action.doAction({
            type:    'ir.actions.act_window',
            res_model: 'product.template',
            res_id:  row.product_tmpl_id,
            views:   [[false, 'form']],
            target:  'current',
        });
    }
    openMo(moId) {
        this.action.doAction({
            type:    'ir.actions.act_window',
            res_model: 'mrp.production',
            res_id:  moId,
            views:   [[false, 'form']],
            target:  'current',
        });
    }

    // ── Acordeón de OFs ───────────────────────────────────────────────────────
    async toggleAccordion(row) {
        if (!row.total_mos) return;
        const pid = row.product_id;
        const wasOpen = !!this.state.expandedProducts[pid];
        this.state.expandedProducts[pid] = !wasOpen;
        if (!wasOpen && !this.state.mosByProduct[pid]) {
            this.state.mosLoading[pid] = true;
            try {
                const mos = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_product_mos_for_forecast',
                    [pid, this.state.periodFrom, this.state.periodTo, this.state.warehouseIds],
                );
                this.state.mosByProduct[pid] = mos;
            } catch (e) {
                console.error('[ForecastWidget] accordion error', e);
                this.state.mosByProduct[pid] = [];
            } finally {
                this.state.mosLoading[pid] = false;
            }
        }
    }

    // ── Formateo / clases — delegates a forecast_formatters.js ───────────────
    moStateBadge(state)    { return moStateBadge(state); }
    saleCatBadge(cat)      { return saleCatBadge(cat); }
    get monthLabels() {
        if (!this.state.data) return [];
        return this.state.data.months.map(monthLabel);
    }
    moCovPct(mos, forecast, so_demand) {
        return moCovPct(mos, forecast, so_demand, this.state.data && this.state.data.mo_coverage_denominator);
    }
    moCovPctCell(cell) { return moCovPctCell(cell, this.state.data && this.state.data.mo_coverage_denominator); }
    moCovPctRow(row)   { return moCovPctRow(row,  this.state.data && this.state.data.mo_coverage_denominator); }
    cellClassForPct(forecast, pct) {
        const d = this.state.data;
        return d ? cellClassForPct(forecast, pct, d.warning_pct) : '';
    }
    cellClassMonthly(cell) {
        const d = this.state.data;
        return d ? cellClassMonthly(cell, d.mo_coverage_color_scope, d.warning_pct, d.mo_coverage_denominator) : '';
    }
    cellClassTotal(row) {
        const d = this.state.data;
        return d ? cellClassTotal(row, d.warning_pct, d.mo_coverage_denominator) : '';
    }
    cellClass(cell) {
        const d = this.state.data;
        return d ? cellClass(cell, d.warning_pct, d.mo_coverage_denominator) : '';
    }
    svcClass(rate)      { return svcClass(rate); }
    accClass(acc)       { return accClass(acc, this.state.data && this.state.data.acc_formula); }
    fmtRotation(row)    { return fmtRotation(row, this.state.data && this.state.data.rotation_unit); }
    rotClass(row)       { return rotClass(row, this.state.data && this.state.data.rotation_unit); }
    fmtCoverage(row)    { return fmtCoverage(row, this.state.data && this.state.data.coverage_unit); }
    covClass(row)       { return covClass(row, this.state.data); }
    demandGapClass(pct) { return demandGapClass(pct); }
    mosGapClass(pct)    { return mosGapClass(pct); }
    fmtGapPct(n)        { return fmtGapPct(n); }
    fmt(n)              { return fmt(n); }

    /** Formato monetario es-AR con símbolo, ej. "$ 1.234,56". */
    fmtMoney(n) {
        if (n === null || n === undefined) return '—';
        return '$ ' + new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
    }
    fmtPct(n)           { return fmtPct(n); }
    fmtDate(d)          { return fmtDate(d); }

    // ── Tooltips — delegates a forecast_tooltips.js ───────────────────────────
    moTooltip(cell)          { return moTooltip(this, cell); }
    svcTooltip(cell)         { return svcTooltip(this, cell); }
    get rotHeaderTitle()     { return rotHeaderTitle(this); }
    rotTooltip(row)          { return rotTooltip(this, row); }
    covTooltip(row)          { return covTooltip(this, row); }
    get covHeaderTitle()     { return covHeaderTitle(this); }
    accGlobalTooltip()       { return accGlobalTooltip(this); }
    accTooltip(row)          { return accTooltip(this, row); }
    fcKpiTooltip(key)        { return fcKpiTooltip(this, key); }
    demandGapTooltip()       { return demandGapTooltip(this); }
    mosGapTooltip()          { return mosGapTooltip(this); }
    accSecondaryPills()      { return accSecondaryPills(this); }

    // ── Acciones ──────────────────────────────────────────────────────────────
    async openImport() {
        await this.action.doAction('odoo_mrp_planner.action_mrp_forecast_line');
    }
    openForecastList() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "mrp.forecast.line",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            target:    "current",
        });
    }

    // ── Drill-down — delegates a forecast_drilldown.js ───────────────────────
    openDrillForecast()            { return openDrillForecast(this); }
    openDrillMos()                 { return openDrillMos(this); }
    openDrillSoDemand()            { return openDrillSoDemand(this); }
    openDrillDelivered()           { return openDrillDelivered(this); }
    openDrillDeliveredByOrderMonth(r) { return openDrillDeliveredByOrderMonth(this, r.key, r.label); }
    openDrillDemandDelivered()     { return openDrillDemandDelivered(this); }
    openDrillSoDemandNoFc()        { return openDrillSoDemandNoFc(this); }
    openDrillMosNoFc()             { return openDrillMosNoFc(this); }
    openDrillDemandDeliveredNoFc() { return openDrillDemandDeliveredNoFc(this); }
    openDrillDeliveredNoFc()       { return openDrillDeliveredNoFc(this); }

    downloadExport() {
        const d = this.state.data;
        if (!d || !d.rows || !d.months) return;
        downloadForecastExcel(this.baseFilteredRows, d.months, this.state.periodFrom, this.state.periodTo, d);
    }
}

registry.category("view_widgets").add("forecast_widget", {
    component: ForecastWidget,
});
