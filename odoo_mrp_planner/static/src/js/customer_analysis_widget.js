/** @odoo-module **/

/**
 * @widget CustomerAnalysisWidget
 * @description Análisis de comportamiento de clientes: métricas de compra,
 * entrega, puntualidad y frecuencia. Carga todo el dataset en el frontend
 * y gestiona sort/filter/paginación/agrupamiento en memoria para respuesta
 * inmediata al usuario.
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry }  from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { useColManager } from "./column_manager";
import { PlannerSearchBar } from "./planner_search_bar";
import { restoreFilters, saveFilters } from "./filter_persistence";
import { destroyPanelCharts, destroyCharts, drawTopChart, drawTopDonut, drawPanelCharts, CHART_COLORS } from "./customer_analysis_charts";
import {
    toggleDetail, toggleRow, getSortedOrders, sortRowOrders, panelTopProducts,
    setPanelMetric, setPanelChartMode, setPanelTopN, sortPanelProds,
} from "./customer_analysis_panel";
import { buildGroupTabs, pageSlice, makePager, applyNumericFilters } from "./planner_table";
import { makeSelection } from "./planner_selection";
import { downloadExcelXml } from "./planner_export";
import { kpiNumClass } from "./forecast_formatters";

// Filtros persistidos por empresa (mismo patrón que los demás paneles).
// Las fechas del período ya se persisten aparte (CA_DATE_KEY).
const CA_PERSIST_KEYS = [
    "sortCol", "sortDir", "productSearch", "activeFilter", "groupBy",
    "selectedGroup", "filterCategory", "filterABC", "filterFreq",
    "visibleCols", "chartMetric", "chartTopN", "chartDonut", "numFilters",
];

// Columnas numéricas filtrables (se pasan a la barra como numericFields).
const CA_NUM_COLS = [
    { key: 'order_count',      label: 'Pedidos' },
    { key: 'qty_ordered',      label: 'Demanda real' },
    { key: 'qty_delivered',    label: 'Cumpl. demanda' },
    { key: 'total_amount',     label: 'Monto' },
    { key: 'avg_price',        label: 'P. prom.' },
    { key: 'delivery_pct',     label: '% Cumplim.' },
    { key: 'lead_time',        label: 'Lead entrega' },
    { key: 'ontime_pct',       label: '% A tiempo' },
    { key: 'days_since_last',  label: 'Días sin comprar' },
    { key: 'distinct_products',label: 'Productos' },
    { key: 'trend_pct',        label: 'Tendencia' },
];

// ── Columnas estáticas (producto del menú de columnas) ────────────────────────
const CA_STATIC_COLS = [
    { key: 'partner_name',      label: 'Cliente',          width: 200, fixed: true,  align: 'start'  },
    { key: 'customer_category', label: 'Cat. global',        width:  80, align: 'center' },
    { key: 'abc_segment',       label: 'ABC período',        width:  80, align: 'center' },
    { key: 'salesperson',       label: 'Vendedor',          width: 130, align: 'start'  },
    { key: 'country',           label: 'País',              width: 110, align: 'start'  },
    { key: 'province',          label: 'Provincia',         width: 120, align: 'start'  },
    { key: 'order_count',       label: 'Pedidos',           width:  75, align: 'end'    },
    { key: 'qty_ordered',       label: 'Demanda real',      width: 100, align: 'end'    },
    { key: 'qty_delivered',     label: 'Cumpl. demanda',    width: 110, align: 'end'    },
    { key: 'total_amount',      label: 'Monto',             width: 110, align: 'end'    },
    { key: 'avg_price',         label: 'P. prom.',          width: 110, align: 'end'    },
    { key: 'delivery_pct',      label: '% Cumplim.',        width:  90, align: 'end'    },
    { key: 'lead_time',         label: 'Lead entrega',      width:  95, align: 'end'    },
    { key: 'ontime_pct',        label: '% A tiempo',        width:  90, align: 'end'    },
    { key: 'avg_days_between',  label: 'Frecuencia',        width:  95, align: 'end'    },
    { key: 'days_since_last',   label: 'Días sin comprar',  width: 110, align: 'end'    },
    { key: 'last_order_date',   label: 'Última compra',     width: 110, align: 'end'    },
    { key: 'distinct_products', label: 'Productos',         width:  80, align: 'end'    },
    { key: 'top_product',       label: 'Top producto',      width: 160, align: 'start'  },
    { key: 'top_family',        label: 'Familia principal', width: 140, align: 'start'  },
    { key: 'trend_pct',         label: 'Tendencia',         width:  90, align: 'end'    },
    { key: 'frequency_segment', label: 'Segmento freq.',    width: 110, align: 'center' },
    { key: 'partner_tag',       label: 'Etiqueta',          width: 130, align: 'center' },
];

const CA_SORT_KEYS = {
    partner_name:      'partner_name',
    customer_category: 'customer_category',
    abc_segment:       'abc_segment',
    salesperson:       'salesperson',
    country:           'country',
    province:          'province',
    order_count:       'order_count',
    qty_ordered:       'qty_ordered',
    qty_delivered:     'qty_delivered',
    total_amount:      'total_amount',
    avg_price:         'avg_price',
    delivery_pct:      'delivery_pct',
    lead_time:         'lead_time',
    ontime_pct:        'ontime_pct',
    avg_days_between:  'avg_days_between',
    days_since_last:   'days_since_last',
    last_order_date:   'last_order_date',
    distinct_products: 'distinct_products',
    top_product:       'top_product',
    top_family:        'top_family',
    trend_pct:         'trend_pct',
    frequency_segment: 'frequency_segment',
    partner_tag:       'partner_tag',
};

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

const CA_DATE_KEY = 'odoo_mrp_planner.ca_period';

function defaultPeriod() {
    try {
        const saved = localStorage.getItem(CA_DATE_KEY);
        if (saved) {
            const { from, to } = JSON.parse(saved);
            if (from && to && from <= to) return { from, to };
        }
    } catch (e) {}
    const now = new Date();
    const from = new Date(now);
    from.setDate(from.getDate() - 90);
    return { from: toDateStr(from), to: toDateStr(now) };
}

function savePeriod(from, to) {
    try { localStorage.setItem(CA_DATE_KEY, JSON.stringify({ from, to })); } catch (e) {}
}

class CustomerAnalysisWidget extends Component {
    static template = "odoo_mrp_planner.CustomerAnalysisWidget";
    static props = { record: { type: Object }, "*": true };
    static components = { PlannerSearchBar };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        // Chart refs — top (donut + bar) + panel lateral
        this.topChartRef  = useRef("topChart");
        this._topChart    = null;
        this._topChartKey = '';

        this.topDonutRef   = useRef("topDonut");
        this._topDonutChart = null;
        this._topDonutKey  = '';

        // Cache key para onPatched — evita redibujar en cada patch menor
        this._lastChartKey  = null;
        this._lastPanelKey  = null;

        this.barRef       = useRef("panelBarCanvas");
        this.donutRef     = useRef("panelDonutCanvas");
        this.lineRef      = useRef("panelLineCanvas");
        this.saleCatRef   = useRef("panelSaleCatCanvas");
        this._barChart    = null;
        this._donutChart  = null;
        this._lineChart   = null;
        this._saleCatChart = null;

        this.cols     = useColManager('customer_analysis', CA_STATIC_COLS);
        this.numColOptions = CA_NUM_COLS;

        const companyId = this.env.services.company?.currentCompany?.id || 0;
        this._persistKey = `customer_analysis.${companyId}`;
        // Dataset propio de los gráficos cuando su rango difiere del de la tabla
        // (null = sincronizado: los gráficos usan el dataset de la tabla).
        this._chartAllRows = null;
        this.caSortKeys = CA_SORT_KEYS;

        const period = defaultPeriod();
        this.state = useState({
            loading:       true,
            loadError:     null,
            dateFrom:      period.from,
            dateTo:        period.to,
            allRows:       [],
            rows:          [],
            kpis:          { total_customers: 0, total_orders: 0, total_amount: 0, total_qty: 0, total_delivered: 0, fulfillment_pct: null, avg_price: 0, lead_weighted: null, lead_first: null, lead_complete: null, lead_time: null },
            config:        {},
            sortCol:       'total_amount',
            sortDir:       'desc',
            page:          1,
            pageSize:      50,
            totalFiltered: 0,
            productSearch: '',
            activeFilter:  null,
            groupBy:       null,
            selectedGroup: null,
            tableTotals:   { count: 0, orders: 0, qty: 0, delivered: 0, amount: 0 },
            selected:      {},
            numFilters:    [],
            colsDropdownOpen: false,
            // Filtros de los gráficos superiores
            chartMetric: 'pxq',
            chartTopN:   10,
            chartDonut:  'abc',
            // Rango de fechas propio de los gráficos (arranca sincronizado con la tabla)
            chartDateFrom: period.from,
            chartDateTo:   period.to,
            chartSynced:   true,
            chartLoading:  false,
            // Filas expandibles
            expandedRows:      {},
            rowOrders:         {},
            rowOrdersLoading:  {},
            // Filtros globales
            filterCategory: null,
            filterABC:      null,
            filterFreq:     null,
            // Panel lateral
            panelLoading:   false,
            panelData:      null,
            panelPartnerId: null,
            panelMetric:    'amount',   // 'amount' | 'qty'
            panelChartMode: 'bar',      // 'bar' | 'line'
            panelTopN:      10,
            panelProdSort:  'amount',   // columna de sort en top artículos
            panelProdDir:   'desc',
            rowOrderSort:   'date',     // columna de sort en tabla de pedidos inline
            rowOrderDir:    'desc',
            // Columnas visibles
            visibleCols: {
                customer_category: false,
                abc_segment:       true,
                salesperson:       false,
                country:           false,
                province:          false,
                order_count:       true,
                qty_ordered:       true,
                qty_delivered:     true,
                total_amount:      true,
                avg_price:         true,
                delivery_pct:      true,
                lead_time:         true,
                ontime_pct:        false,
                avg_days_between:  false,
                days_since_last:   false,
                last_order_date:   false,
                distinct_products: false,
                top_product:       false,
                top_family:        false,
                trend_pct:         false,
                frequency_segment: true,
                partner_tag:       false,
            },
        });

        // Restaurar filtros de la última visita (por empresa) — DESPUÉS de crear
        // el estado: antes se llamaba con this.state todavía undefined, así que
        // con filtros guardados el widget tiraba TypeError al remontarse.
        // Se guardan en _applySort(), el punto único de todo cambio de filtro.
        restoreFilters(this._persistKey, this.state, CA_PERSIST_KEYS);

        // ── Mecánica compartida de los paneles (planner_*): selección de
        //    filas y paginador. onChange = _applySort porque este widget
        //    materializa KPIs, totales y página visible en el estado. ──
        this.sel   = makeSelection(this, {
            key: "partner_id",
            pageRows: () => this.state.rows,
            onChange: () => this._applySort(),
        });
        this.pager = makePager(this, () => this.state.totalFiltered, () => this._applySort());

        this._closeDropdowns = () => {
            this.state.colsDropdownOpen = false;
        };

        onMounted(async () => {
            try {
                document.addEventListener('click', this._closeDropdowns);
                await loadBundle("web.chartjs_lib");
                await this._load();
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });

        onPatched(() => {
            const newChartKey = JSON.stringify([
                this.state.chartMetric,
                this.state.chartTopN,
                this.state.chartDonut,
                this.state.filterCategory,
                this.state.filterABC,
                this.state.filterFreq,
                this.state.chartDateFrom,
                this.state.chartDateTo,
            ]);
            if (this._lastChartKey !== newChartKey) {
                this._lastChartKey = newChartKey;
                this._drawTopChart();
                this._drawTopDonut();
            }

            if (this.state.panelPartnerId && this.state.panelData && !this.state.panelLoading) {
                const newPanelKey = JSON.stringify([
                    this.state.panelPartnerId,
                    this.state.panelMetric,
                    this.state.panelChartMode,
                    this.state.panelTopN,
                ]);
                if (this._lastPanelKey !== newPanelKey) {
                    this._lastPanelKey = newPanelKey;
                    this._drawPanelCharts();
                }
            }
        });

        onWillUnmount(() => {
            document.removeEventListener('click', this._closeDropdowns);
            this._destroyCharts();
        });
    }

    // ── Carga de datos ────────────────────────────────────────────────────────

    async _load() {
        this.state.loading         = true;
        this.state.loadError       = null;
        this.state.expandedRows    = {};
        this.state.rowOrders        = {};
        this.state.rowOrdersLoading = {};
        this.state.panelPartnerId   = null;
        this.state.panelData        = null;
        this._lastChartKey          = null;  // forzar redraw de charts superiores
        this._lastPanelKey          = null;
        this._destroyPanelCharts();
        try {
            const res = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_analysis_data',
                [this.state.dateFrom, this.state.dateTo, null]
            );
            if (res.error) {
                this.state.loadError = res.error;
                console.error('[CustomerAnalysis] backend error:', res.error);
            }
            this.state.allRows = res.rows || [];
            this.state.selected = {};
            this.state.kpis    = res.kpis  || {};
            this.state.config  = res.config || {};
            if (res.config && !res.config.show_category) {
                this.state.visibleCols.customer_category = false;
            }
            this._applySort();
            // Resetear las llaves de redraw DESPUÉS del await: el patch intermedio
            // (mientras carga) las consumía y los gráficos quedaban en blanco.
            this._topChartKey  = '';
            this._topDonutKey  = '';
            this._lastChartKey = null;
        } catch (e) {
            console.error('[CustomerAnalysis]', e);
            this.state.loadError = e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Filas con búsqueda de texto y filtros de segmento aplicados (sin filtro de
     * pestaña ni orden). Base común de la tabla y de las pestañas de agrupamiento.
     * @returns {Array} Filas filtradas
     */
    _baseFiltered(src = null) {
        let rows = [...(src || this.state.allRows)];
        // Búsqueda de texto
        const q = this.state.productSearch.trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                (r.partner_name   || '').toLowerCase().includes(q) ||
                (r.top_product    || '').toLowerCase().includes(q) ||
                (r.top_family     || '').toLowerCase().includes(q) ||
                (r.salesperson    || '').toLowerCase().includes(q)
            );
        }
        // Filtros numéricos (AND): componen con búsqueda, pestañas, KPIs y gráficos
        return applyNumericFilters(rows, this.state.numFilters, (r, k) => this._numVal(r, k));
    }

    /** Valor numérico de una columna filtrable (null si no hay dato). */
    _numVal(row, key) {
        const v = row[key];
        return (v === null || v === undefined) ? null : v;
    }

    // Callbacks del filtro numérico de la barra de búsqueda
    addNumFilter(cond) {
        this.state.numFilters = [...this.state.numFilters, cond];
        this.state.page = 1;
        this._applySort();
    }
    removeNumFilter(idx) {
        this.state.numFilters = this.state.numFilters.filter((_, i) => i !== idx);
        this.state.page = 1;
        this._applySort();
    }

    /**
     * Filtros de segmento (Categoría / ABC / Frecuencia). Afectan SOLO a los
     * gráficos superiores: la tabla, sus KPIs y el pie de totales no cambian.
     */
    _segmentFiltered(rows) {
        if (this.state.filterCategory !== null) {
            rows = rows.filter(r => r.customer_category === this.state.filterCategory);
        }
        if (this.state.filterABC !== null) {
            rows = rows.filter(r => r.abc_segment === this.state.filterABC);
        }
        if (this.state.filterFreq !== null) {
            rows = rows.filter(r => r.frequency_segment === this.state.filterFreq);
        }
        return rows;
    }

    _applySort() {
        let rows = this._baseFiltered();
        // Ordenamiento
        const col = this.state.sortCol;
        const dir = this.state.sortDir === 'asc' ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === 'string') {
                if (!va && vb) return dir;
                if (va && !vb) return -dir;
                return dir * (va || '').localeCompare(vb || '', 'es', { sensitivity: 'base' });
            }
            va = va ?? -Infinity;
            vb = vb ?? -Infinity;
            return dir * (va - vb);
        });

        // Pestaña activa del agrupamiento: la tabla muestra solo el grupo activo,
        // mismo patrón que quiebres de stock y forecast.
        if (this.state.groupBy) {
            const groups = this.allGroupsForTabs;
            if (groups.length && !groups.some(g => g.key === this.state.selectedGroup)) {
                this.state.selectedGroup = groups[0].key;
            }
            const gb = this.state.groupBy;
            rows = rows.filter(r => (r[gb] || '—') === this.state.selectedGroup);
        }

        // Los KPIs describen exactamente lo que la tabla muestra: filtros, búsqueda
        // Y pestaña activa — y, con filas seleccionadas, SOLO la selección
        // (mismo criterio que el Panel de Inventario).
        const selRows = rows.filter(r => this.state.selected[r.partner_id]);
        const kpiRows = selRows.length ? selRows : rows;
        this.state.kpis = { ...this.state.kpis, ...this._computeKpis(kpiRows) };

        this.state.totalFiltered = rows.length;
        this._filteredRows = rows;   // tabla visible y export (incluye pestaña activa)

        // Totales del pie: reflejan la tabla (o la selección si la hay).
        this.state.tableTotals = {
            count:  kpiRows.length,
            orders: kpiRows.reduce((s, r) => s + (r.order_count || 0), 0),
            qty:    Math.round(kpiRows.reduce((s, r) => s + (r.qty_ordered || 0), 0) * 10) / 10,
            delivered: Math.round(kpiRows.reduce((s, r) => s + (r.qty_delivered || 0), 0) * 10) / 10,
            amount: Math.round(kpiRows.reduce((s, r) => s + (r.total_amount || 0), 0) * 100) / 100,
        };

        saveFilters(this._persistKey, this.state, CA_PERSIST_KEYS);

        // Paginación (si la página quedó fuera de rango tras filtrar, volver a la 1)
        if ((Math.max(1, this.state.page) - 1) * this.state.pageSize >= rows.length && rows.length) {
            this.state.page = 1;
        }
        this.state.rows = pageSlice(rows, this.state.page, this.state.pageSize);
    }

    /**
     * Pestañas de agrupamiento: un grupo por valor del campo activo, con conteo,
     * calculadas sobre el conjunto filtrado/buscado (sin la pestaña aplicada).
     * @returns {Array<{key: string, label: string, count: number}>|null}
     */
    get allGroupsForTabs() {
        const gb = this.state.groupBy;
        if (!gb) return null;
        return buildGroupTabs(this._baseFiltered(), r => r[gb] || '—');
    }

    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
        this._applySort();
    }

    // ── Selección: recalcula KPIs y totales, igual que el Panel de Inventario
    //    (mecánica compartida en planner_selection) ──

    toggleSelect(row) { this.sel.toggle(row); }
    toggleSelectAll() { this.sel.toggleAll(); }
    clearSelection()  { this.sel.clear(); }
    get allSelected()   { return this.sel.allSelected; }
    get selectedCount() { return this.sel.pick(this._filteredRows || []).length; }


    /**
     * Recalcula los KPIs de la parte superior sobre el conjunto de filas dado
     * (filtrado/buscado), replicando las fórmulas del backend para que las cards
     * reflejen exactamente lo que se ve en la tabla.
     * @param {Array} rows - filas filtradas
     * @returns {Object} dict de KPIs
     */
    _computeKpis(rows) {
        const totalOrders = rows.reduce((s, r) => s + (r.order_count || 0), 0);
        const totalAmount = rows.reduce((s, r) => s + (r.total_amount || 0), 0);
        const totalQty    = rows.reduce((s, r) => s + (r.qty_ordered  || 0), 0);
        const totalDelivered = rows.reduce((s, r) => s + (r.qty_delivered || 0), 0);
        return {
            total_customers: rows.length,
            total_orders:    totalOrders,
            total_amount:    Math.round(totalAmount * 100) / 100,
            total_qty:       Math.round(totalQty * 10) / 10,
            total_delivered: Math.round(totalDelivered * 10) / 10,
            fulfillment_pct: totalQty > 0 ? Math.round(totalDelivered / totalQty * 1000) / 10 : null,
            avg_price:       totalQty ? Math.round(totalAmount / totalQty * 100) / 100 : 0,
            ...this._computeLeadKpis(rows),
        };
    }

    /** Agregados de lead time de entrega sobre las filas visibles (3 métodos). */
    _computeLeadKpis(rows) {
        const wNum   = rows.reduce((a, r) => a + (r.lt_w_num     || 0), 0);
        const wDen   = rows.reduce((a, r) => a + (r.lt_w_den     || 0), 0);
        const fSum   = rows.reduce((a, r) => a + (r.lt_first_sum || 0), 0);
        const fN     = rows.reduce((a, r) => a + (r.lt_first_n   || 0), 0);
        const cSum   = rows.reduce((a, r) => a + (r.lt_comp_sum  || 0), 0);
        const cN     = rows.reduce((a, r) => a + (r.lt_comp_n    || 0), 0);
        const k = {
            lead_weighted: wDen > 0 ? Math.round(wNum / wDen * 10) / 10 : null,
            lead_first:    fN   > 0 ? Math.round(fSum / fN   * 10) / 10 : null,
            lead_complete: cN   > 0 ? Math.round(cSum / cN   * 10) / 10 : null,
        };
        const key = { weighted: 'lead_weighted', first: 'lead_first', complete: 'lead_complete' }[
            this.state.config.leadtime_method || 'weighted'];
        k.lead_time = k[key];
        return k;
    }

    /** Etiqueta corta del método de lead time configurado en Ajustes. */
    leadMethodLabel(method) {
        const m = method || this.state.config.leadtime_method || 'weighted';
        return { weighted: 'ponderado', first: '1ª entrega', complete: 'pedido completo' }[m] || m;
    }

    /** Pills secundarias del KPI de lead time: los métodos NO elegidos en Ajustes. */
    leadPills() {
        const main = this.state.config.leadtime_method || 'weighted';
        const k = this.state.kpis;
        return [
            { key: 'weighted', label: 'Pond.',    value: k.lead_weighted },
            { key: 'first',    label: '1ª',       value: k.lead_first },
            { key: 'complete', label: 'Completo', value: k.lead_complete },
        ].filter(p => p.key !== main);
    }

    fmtDays(v) {
        return v !== null && v !== undefined ? this.fmt(v) + ' d' : '—';
    }

    /** Clase de tamaño de los números de las cards KPI (compartida). */
    kpiNumClass(text) { return kpiNumClass(text); }

    /** Tooltip del lead time de un pedido de la tabla inline: los 3 métodos. */
    orderLeadTooltip(ord) {
        return `Lead time del pedido (método principal: ${this.leadMethodLabel()}). Días desde la confirmación hasta la fecha efectiva de cada remito.\nPonderado por cantidad: ${this.fmtDays(ord.lead_weighted)}\nPrimera entrega: ${this.fmtDays(ord.lead_first)}\nPedido completo: ${this.fmtDays(ord.lead_complete)}${ord.lead_complete == null ? ' (aún sin entregar por completo)' : ''}`;
    }

    // ── Handlers de controles ─────────────────────────────────────────────────

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) this.state.dateTo = this.state.dateFrom;
        savePeriod(this.state.dateFrom, this.state.dateTo);
        if (this.state.chartSynced) { this.state.chartDateFrom = this.state.dateFrom; this.state.chartDateTo = this.state.dateTo; }
        this._load();
    }
    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) this.state.dateFrom = this.state.dateTo;
        savePeriod(this.state.dateFrom, this.state.dateTo);
        if (this.state.chartSynced) { this.state.chartDateFrom = this.state.dateFrom; this.state.chartDateTo = this.state.dateTo; }
        this._load();
    }

    // ── Rango propio de los gráficos ──────────────────────────────────────────

    onChartDateFromChange(ev) {
        this.state.chartDateFrom = ev.target.value;
        if (this.state.chartDateFrom > this.state.chartDateTo) this.state.chartDateTo = this.state.chartDateFrom;
        this._onChartRangeChange();
    }

    onChartDateToChange(ev) {
        this.state.chartDateTo = ev.target.value;
        if (this.state.chartDateTo < this.state.chartDateFrom) this.state.chartDateFrom = this.state.chartDateTo;
        this._onChartRangeChange();
    }

    /**
     * Al cambiar el rango del gráfico: si coincide con el de la tabla vuelve al
     * modo sincronizado (sin dataset propio); si difiere, pide al backend el
     * dataset del rango del gráfico y lo guarda aparte.
     */
    async _onChartRangeChange() {
        const synced = this.state.chartDateFrom === this.state.dateFrom
                    && this.state.chartDateTo   === this.state.dateTo;
        this.state.chartSynced = synced;
        if (synced) {
            this._chartAllRows = null;
            this._topChartKey  = '';
            this._topDonutKey  = '';
            this._lastChartKey = null;
            return;
        }
        this.state.chartLoading = true;
        try {
            const res = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_analysis_data',
                [this.state.chartDateFrom, this.state.chartDateTo, null]
            );
            this._chartAllRows = res.rows || [];
        } catch (e) {
            console.error('[CustomerAnalysis] rango del gráfico', e);
            this._chartAllRows = null;
        } finally {
            // Resetear las llaves DESPUÉS del await para que el redraw ocurra
            // con los datos nuevos y no lo consuma el patch del spinner.
            this._topChartKey  = '';
            this._topDonutKey  = '';
            this._lastChartKey = null;
            this.state.chartLoading = false;
        }
    }

    /**
     * Filas que alimentan los gráficos superiores. Sincronizado: las mismas de la
     * tabla (con todos sus filtros). Con rango propio: el dataset del rango del
     * gráfico con la misma búsqueda y filtros de segmento aplicados.
     * @returns {Array}
     */
    get chartSourceRows() {
        if (!this._chartAllRows) return this._segmentFiltered(this._filteredRows || this.state.allRows);
        return this._segmentFiltered(this._baseFiltered(this._chartAllRows));
    }

    toggleColsDropdown(ev) {
        ev.stopPropagation();
        this.state.colsDropdownOpen = !this.state.colsDropdownOpen;
    }

    // PlannerSearchBar callbacks
    setSearch(text) {
        this.state.productSearch = text;
        this.state.page = 1;
        this._applySort();
    }

    // Solo redibujan los gráficos: la tabla no se refiltra ni se resetea la página.
    setFilterCategory(v) { this.state.filterCategory = v; this._topChartKey = ''; this._topDonutKey = ''; }
    setFilterABC(v)      { this.state.filterABC      = v; this._topChartKey = ''; this._topDonutKey = ''; }
    setFilterFreq(v)     { this.state.filterFreq     = v; this._topChartKey = ''; this._topDonutKey = ''; }

    get availableCategories() {
        const seen = new Set();
        for (const r of this.state.allRows) {
            if (r.customer_category) seen.add(r.customer_category);
        }
        return [...seen].sort();
    }

    setGroupBy(key) {
        this.state.groupBy = key;
        this.state.selectedGroup = null;   // _applySort selecciona la primera pestaña
        this.state.page = 1;
        this._applySort();
    }

    // ── Interacciones UI ─────────────────────────────────────────────────────

    setSort(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.sortCol = col;
            this.state.sortDir = 'desc';
        }
        this.state.page = 1;
        this._applySort();
    }

    onColHeaderClick(col) {
        const sk = CA_SORT_KEYS[col.key];
        if (sk) this.setSort(sk);
    }

    toggleCol(key) {
        this.state.visibleCols[key] = !this.state.visibleCols[key];
    }

    get staticVisibleCols() {
        return this.cols.visibleCols().filter(col => {
            if (col.key === 'partner_name') return true;
            if (col.key === 'customer_category' && !this.state.config.show_category) return false;
            return !!this.state.visibleCols[col.key];
        });
    }

    sortIcon(col) {
        if (this.state.sortCol !== col) return 'fa fa-sort text-muted ms-1';
        return this.state.sortDir === 'asc'
            ? 'fa fa-sort-asc text-primary ms-1'
            : 'fa fa-sort-desc text-primary ms-1';
    }

    // Paginación: mecánica compartida (makePager rematerializa la página
    // visible vía _applySort)
    nextPage() { this.pager.next(); }
    prevPage() { this.pager.prev(); }
    get totalPages()  { return this.pager.totalPages; }
    get hasPrevPage() { return this.pager.hasPrev; }
    get hasNextPage() { return this.pager.hasNext; }

    // ── Panel lateral y filas expandibles (customer_analysis_panel.js) ────────

    async toggleDetail(partnerId) { return toggleDetail(this, partnerId); }

    _destroyPanelCharts() { destroyPanelCharts(this); }

    openOrder(orderId) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'sale.order',
            res_id:    orderId,
            view_mode: 'form',
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    // ── Charts del panel ──────────────────────────────────────────────────────

    _destroyCharts() { destroyCharts(this); }

    // ── Gráficos superiores ───────────────────────────────────────────────────

    setChartMetric(m) {
        if (this.state.chartMetric !== m) { this.state.chartMetric = m; this._topChartKey = ''; }
    }
    setChartTopN(n) {
        if (this.state.chartTopN !== n)   { this.state.chartTopN   = n; this._topChartKey = ''; }
    }
    setChartDonut(d) {
        if (this.state.chartDonut !== d)  { this.state.chartDonut  = d; this._topDonutKey = ''; }
    }

    setPanelMetric(m)       { setPanelMetric(this, m); }
    setPanelChartMode(mode) { setPanelChartMode(this, mode); }
    partnerTagColor(colorIdx) {
        const palette = [
            '#aaaaaa', '#e06c75', '#e09b49', '#e8d04a',
            '#56b4d3', '#7b65be', '#73c7ae', '#a8a8a8',
            '#71bb63', '#de9898', '#e0734b', '#b9699b',
        ];
        return palette[colorIdx] ?? '#aaaaaa';
    }

    saleCatColor(name) {
        const map = { A: '#198754', B: '#0d6efd', C: '#ffc107', D: '#6c757d', E: '#c8d2dc' };
        return map[name] || '#6c757d';
    }
    setPanelTopN(n)     { setPanelTopN(this, n); }
    sortPanelProds(key) { sortPanelProds(this, key); }

    openProduct(tmplId) {
        if (!tmplId) return;
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'product.template',
            res_id:    tmplId,
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    sortRowOrders(key)         { sortRowOrders(this, key); }
    getSortedOrders(partnerId) { return getSortedOrders(this, partnerId); }

    orderStateBadgeClass(state) {
        return {
            'Confirmado': 'badge text-bg-primary',
            'Hecho':      'badge text-bg-success',
            'Cancelado':  'badge text-bg-danger',
            'Borrador':   'badge text-bg-secondary',
        }[state] || 'badge text-bg-secondary';
    }

    get panelTopProducts() { return panelTopProducts(this); }

    _drawTopChart() { drawTopChart(this); }

    _drawTopDonut() { drawTopDonut(this); }

    // ── Filas expandibles (customer_analysis_panel.js) ────────────────────────

    async toggleRow(partnerId) { return toggleRow(this, partnerId); }

    openCustomer(partnerId) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            res_model: 'res.partner',
            res_id:    partnerId,
            view_mode: 'form',
            views:     [[false, 'form']],
            target:    'current',
        });
    }

    /**
     * Abre las líneas de pedido (piezas) del cliente en el período. Usado por el
     * "Ver →" de la card Piezas del detalle: muestra qué pidió línea por línea,
     * no los pedidos. Respeta la exclusión de servicios de Ajustes.
     * @param {number} partnerId - Partner de la fila (representativo si está unificado).
     */
    openCustomerOrderLines(partnerId) {
        const row = this.state.allRows.find(r => r.partner_id === partnerId);
        const partnerIds = (row && row.partner_ids) || [partnerId];
        const domain = [
            ['order_id.partner_id', 'child_of', partnerIds],
            ['order_id.state', 'in', ['sale', 'done']],
            ['order_id.date_order', '>=', this.state.dateFrom + ' 00:00:00'],
            ['order_id.date_order', '<=', this.state.dateTo   + ' 23:59:59'],
        ];
        if (this.state.config && this.state.config.exclude_services) {
            domain.push(['product_id.type', '!=', 'service']);
        }
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Piezas pedidas del período',
            res_model: 'sale.order.line',
            views:     [[false, 'list']],
            context:   { list_view_ref: 'odoo_mrp_planner.view_sale_order_line_planner_list' },
            domain,
            target: 'current',
        });
    }

    /**
     * Clase de tamaño para números de KPI según su longitud, para que nunca
     * ocupen dos renglones (el signo $ suele empujar el ancho).
     * @param {string} text - Número ya formateado.
     * @returns {string} '' | 'o_planner_num_md' | 'o_planner_num_sm'
     */
    numSizeClass(text, narrow = false) {
        const len = String(text ?? '').length;
        // Cards anchas (4 por fila): recién achicar con números muy largos.
        // Cards angostas (5 por fila, detalle): umbral agresivo porque ahí
        // los montos con $ se partían en dos renglones.
        const md = narrow ? 10 : 17;
        const sm = narrow ? 14 : 21;
        if (len > sm) return 'o_planner_num_sm';
        if (len > md) return 'o_planner_num_md';
        return '';
    }

    /**
     * Abre las líneas de pedido (piezas) del período de todos los clientes.
     * Usado por el "Ver →" del KPI Piezas pedidas. Respeta la exclusión de
     * servicios de Ajustes.
     */
    openPeriodOrderLines() {
        const domain = [
            ['order_id.state', 'in', ['sale', 'done']],
            ['order_id.date_order', '>=', this.state.dateFrom + ' 00:00:00'],
            ['order_id.date_order', '<=', this.state.dateTo   + ' 23:59:59'],
        ];
        if (this.state.config && this.state.config.exclude_services) {
            domain.push(['product_id.type', '!=', 'service']);
        }
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Piezas pedidas del período',
            res_model: 'sale.order.line',
            views:     [[false, 'list']],
            context:   { list_view_ref: 'odoo_mrp_planner.view_sale_order_line_planner_list' },
            domain,
            target: 'current',
        });
    }

    /**
     * Remitos de salida de los pedidos del período del cliente (cualquier fecha
     * de entrega). Es lo que respalda la card "Cumplimiento de demanda".
     * @param {number} partnerId - Partner de la fila (representativo si está unificado).
     */
    openCustomerDemandPickings(partnerId) {
        const row = this.state.allRows.find(r => r.partner_id === partnerId);
        const partnerIds = (row && row.partner_ids) || [partnerId];
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Entregas de pedidos del período (líneas)',
            res_model: 'stock.move.line',
            views:     [[false, 'list']],
            domain: [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['picking_id.sale_id.partner_id', 'child_of', partnerIds],
                ['picking_id.sale_id.state', 'in', ['sale', 'done']],
                ['picking_id.sale_id.date_order', '>=', this.state.dateFrom + ' 00:00:00'],
                ['picking_id.sale_id.date_order', '<=', this.state.dateTo   + ' 23:59:59'],
            ],
            target: 'current',
        });
    }




    /** Entregas (líneas) de los pedidos del período de TODOS los clientes visibles.
     *  Mismo criterio que el KPI "Cumpl. de demanda": pedidos confirmados en el
     *  período, entregas efectivizadas a cualquier fecha. */
    openKpiDemandDeliveries() {
        const pids = [...new Set(
            (this._filteredRows || []).flatMap(r => r.partner_ids || [r.partner_id])
        )];
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Entregas de pedidos del período (líneas)',
            res_model: 'stock.move.line',
            views:     [[false, 'list']],
            domain: [
                ['state', '=', 'done'],
                ['picking_id.picking_type_id.code', '=', 'outgoing'],
                ['picking_id.sale_id.partner_id', 'child_of', pids],
                ['picking_id.sale_id.state', 'in', ['sale', 'done']],
                ['picking_id.sale_id.date_order', '>=', this.state.dateFrom + ' 00:00:00'],
                ['picking_id.sale_id.date_order', '<=', this.state.dateTo   + ' 23:59:59'],
            ],
            target: 'current',
        });
    }

    /** Preset del gráfico: fija su rango al mes calendario en curso. */
    setChartCurrentMonth() {
        const now = new Date();
        this.state.chartDateFrom = toDateStr(new Date(now.getFullYear(), now.getMonth(), 1));
        this.state.chartDateTo   = toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));
        this._onChartRangeChange();
    }

    /** True si el rango del gráfico coincide con el mes en curso (para pintar el preset). */
    get isChartCurrentMonth() {
        const now = new Date();
        return this.state.chartDateFrom === toDateStr(new Date(now.getFullYear(), now.getMonth(), 1))
            && this.state.chartDateTo   === toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));
    }

    /**
     * Nota del método de valorización activo para los tooltips de montos.
     * En PxQ incluye el aviso de que no considera precios históricos.
     */
    amountNote() {
        const m = this.state.config && this.state.config.amount_method;
        if (m === 'real') {
            return '\nValorización: importe real de pedidos (con descuentos, sin impuestos) — configurable en Ajustes → Ventas.';
        }
        return '\nValorización: PxQ a precio de lista ACTUAL de la ficha (cantidad × precio de venta).'
             + '\n⚠ No considera precios históricos: si cambia la lista, el pasado se revaloriza. No cuadra con la facturación. Configurable en Ajustes → Ventas.';
    }

    /** Sufijo del label de los montos según el método activo. */
    get amountLabelSuffix() {
        return (this.state.config && this.state.config.amount_method) === 'real' ? '' : ' (PxQ)';
    }

    /** Nota para tooltips de montos/piezas cuando los servicios están excluidos en Ajustes. */
    svcNote() {
        return this.state.config && this.state.config.exclude_services
            ? '\n(Líneas de servicios excluidas según Ajustes → Ventas)' : '';
    }

    openCustomerOrders(partnerId) {
        // Con "Unificar por CUIT" la fila puede agrupar varios partners.
        const row = this.state.allRows.find(r => r.partner_id === partnerId);
        const partnerIds = (row && row.partner_ids) || [partnerId];
        // Cliente simple: viaja como faceta de búsqueda removible (se puede sacar
        // para ver todos los pedidos del período). Cliente unificado por CUIT:
        // queda en el dominio porque la faceta no soporta varios partners.
        const domain = [
            ['state', 'in', ['sale', 'done']],
            ['date_order', '>=', this.state.dateFrom + ' 00:00:00'],
            ['date_order', '<=', this.state.dateTo   + ' 23:59:59'],
        ];
        const context = {};
        if (partnerIds.length === 1) {
            context.search_default_partner_id = partnerIds[0];
        } else {
            domain.unshift(['partner_id', 'child_of', partnerIds]);
        }
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Pedidos del período',
            res_model: 'sale.order',
            views:     [[false, 'list'], [false, 'form']],
            domain,
            context,
            target: 'current',
        });
    }

    openKpiDrilldown(type) {
        const baseDomain = [
            ['state', 'in', ['sale', 'done']],
            ['date_order', '>=', this.state.dateFrom + ' 00:00:00'],
            ['date_order', '<=', this.state.dateTo   + ' 23:59:59'],
        ];
        const cfg = {
            customers: { name: 'Clientes del período',     context: { group_by: ['partner_id'] } },
            ticket:    { name: 'Pedidos por monto',         context: {} },
            delivery:  { name: 'Entregas del período',      context: {} },
            ontime:    { name: 'Cumplimiento de plazos',    context: {} },
        }[type] || { name: 'Pedidos del período', context: {} };
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      cfg.name,
            res_model: 'sale.order',
            views:     [[false, 'list'], [false, 'form']],
            domain:    baseDomain,
            context:   cfg.context,
            target:    'current',
        });
    }

    _drawPanelCharts() { drawPanelCharts(this); }

    // ── Exportar Excel ───────────────────────────────────────────────────────

    exportToExcel() {
        const cols = this.staticVisibleCols;
        const cellVal = (row, key) => {
            const v = row[key];
            if (v === null || v === undefined) return '';
            if (['delivery_pct', 'ontime_pct', 'trend_pct'].includes(key))
                return v.toFixed(1) + '%';
            if (['avg_days_between', 'days_since_last'].includes(key) && v !== null)
                return v + ' d';
            return v;
        };
        downloadExcelXml({
            filename: `clientes_${this.state.dateFrom}_${this.state.dateTo}.xls`,
            sheet:    'Clientes',
            headers:  cols.map(c => c.label),
            rows:     this._filteredRows || this.state.allRows,
            cell:     row => cols.map(c => cellVal(row, c.key)),
        });
    }

    donutColor(idx) { return CHART_COLORS.donut[idx % CHART_COLORS.donut.length]; }

    fmtQty(v) {
        if (v == null) return '—';
        return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
    }

    // ── Formateo y semáforos ──────────────────────────────────────────────────

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR').format(n);
    }

    fmtMoney(n) {
        if (n === null || n === undefined) return '—';
        return '$ ' + new Intl.NumberFormat('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
    }

    fmtK(n) {
        if (!n && n !== 0) return '—';
        if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
        if (Math.abs(n) >= 1_000)     return (n / 1_000).toFixed(0) + 'k';
        return String(n);
    }

    fmtPct(n) {
        if (n === null || n === undefined) return '—';
        return n.toFixed(1) + '%';
    }

    fmtTrend(n) {
        if (n === null || n === undefined) return '—';
        return (n >= 0 ? '▲ ' : '▼ ') + Math.abs(n).toFixed(1) + '%';
    }

    /**
     * Convierte una fecha ISO 'YYYY-MM-DD' a 'DD/MM/YYYY' para el render.
     * Solo formateo visual: los valores del backend siguen en ISO (el sort
     * client-side depende de ese formato).
     * @param {string|null} iso - Fecha en formato ISO
     * @returns {string} Fecha formateada o '—'
     */
    fmtDate(iso) {
        if (!iso) return '—';
        const [y, m, d] = String(iso).split('-');
        if (!y || !m || !d) return String(iso);
        return `${d}/${m}/${y}`;
    }

    deliveryClass(pct) {
        if (pct === null || pct === undefined) return 'text-muted';
        const cfg = this.state.config;
        if (pct < (cfg.delivery_crit || 60)) return 'text-danger';
        if (pct < (cfg.delivery_warn || 80)) return 'text-warning';
        return 'text-success';
    }

    ontimeClass(pct) {
        if (pct === null || pct === undefined) return 'text-muted';
        const cfg = this.state.config;
        if (pct < (cfg.ontime_crit || 60)) return 'text-danger';
        if (pct < (cfg.ontime_warn || 80)) return 'text-warning';
        return 'text-success';
    }

    riskClass(days) {
        if (days === null || days === undefined) return '';
        const risk = this.state.config.risk_days || 90;
        if (days > risk) return 'text-danger fw-semibold';
        if (days > risk * 0.7) return 'text-warning';
        return '';
    }

    trendClass(pct) {
        if (pct === null || pct === undefined) return 'text-muted';
        return pct >= 0 ? 'text-success' : 'text-danger';
    }

    catBadgeClass(cat) {
        const map = { A: 'text-bg-success', B: 'text-bg-primary', C: 'text-bg-warning text-dark', D: 'text-bg-secondary', E: 'text-bg-danger' };
        return map[cat] || 'text-bg-secondary';
    }

    abcBadgeClass(seg) {
        const map = { A: 'text-bg-success', B: 'text-bg-primary', C: 'text-bg-warning text-dark' };
        return map[seg] || 'text-bg-secondary';
    }

    freqBadgeClass(seg) {
        const map = { frecuente: 'text-bg-success', ocasional: 'text-bg-warning text-dark', inactivo: 'text-bg-secondary', en_riesgo: 'text-bg-danger' };
        return map[seg] || 'text-bg-secondary';
    }

    freqLabel(seg) {
        const map = { frecuente: 'Frecuente', ocasional: 'Ocasional', inactivo: 'Inactivo', en_riesgo: 'En riesgo' };
        return map[seg] || seg;
    }

    kpiTooltip(key) {
        const k  = this.state.kpis;
        const m  = v => this.fmtMoney(v);
        const f  = v => this.fmt(v);
        const p  = v => this.fmtPct(v);
        switch (key) {
            case 'total_customers':
                return `Clientes únicos con al menos 1 pedido confirmado en el período.\nTotal: ${f(k.total_customers)} clientes`;
            case 'total_orders':
                return `Pedidos confirmados (estado: Confirmado o Hecho) en el período.\nTotal: ${f(k.total_orders)} pedidos`;
            case 'total_amount':
                return `Monto total de ventas del período (suma dinámica de la tabla visible).\nTotal: ${m(k.total_amount)} en ${f(k.total_orders)} pedidos` + this.amountNote() + this.svcNote();
            case 'total_qty':
                return `Demanda real: piezas pedidas en el período (suma de cantidades de todas las líneas de los clientes visibles). Mismo concepto que "Demanda real" del panel de ventas.\nTotal: ${f(k.total_qty)} Pz en ${f(k.total_orders)} pedidos` + this.svcNote();
            case 'total_delivered':
                return `Cumplimiento de demanda: piezas ya entregadas de los pedidos del período (acumulado a la fecha, cualquier fecha de entrega). Suma dinámica de la tabla visible — mismo criterio que la columna "Cumpl. demanda".\nTotal: ${f(k.total_delivered)} Pz entregadas de ${f(k.total_qty)} pedidas` + this.svcNote();
            case 'fulfillment_pct':
                return `Tasa de cumplimiento del período: de lo pedido en el período, cuánto ya se entregó\nCumplimiento de demanda ÷ Demanda real × 100\n→ ${f(k.total_delivered)} ÷ ${f(k.total_qty)} = ${k.fulfillment_pct != null ? k.fulfillment_pct + '%' : '—'}\nVerde ≥ ${this.state.config.delivery_warn || 80}% | Amarillo ≥ ${this.state.config.delivery_crit || 60}% (umbrales configurables en Ajustes)` + this.svcNote();
            case 'avg_price':
                return `Precio promedio por unidad del período\nMonto total ÷ Demanda real\n→ ${m(k.total_amount)} ÷ ${f(k.total_qty)} = ${m(k.avg_price)}` + this.amountNote() + this.svcNote();
            case 'lead_time':
                return `Lead time de entrega de los pedidos del período (clientes visibles). Días desde la confirmación hasta la fecha efectiva de cada remito de salida.\nMétodo principal (${this.leadMethodLabel()}, configurable en Ajustes): ${this.fmtDays(k.lead_time)}\n• Ponderado por cantidad: ${this.fmtDays(k.lead_weighted)} — promedia cada entrega parcial pesada por sus piezas; es lo que esperó la pieza promedio\n• Primera entrega: ${this.fmtDays(k.lead_first)} — promedio de días hasta el primer remito de cada pedido (velocidad de reacción)\n• Pedido completo: ${this.fmtDays(k.lead_complete)} — promedio de punta a punta, solo pedidos totalmente entregados`;
            case 'avg_days_between':
                return `Promedio de días entre pedidos consecutivos, calculado entre todos los clientes con más de 1 pedido\n→ ${k.avg_days_between != null ? k.avg_days_between + ' días promedio' : '—'}`;
            default:
                return '';
        }
    }

    cellTooltip(key, row) {
        if (!row) return '';
        const m  = v => this.fmtMoney(v);
        const f  = v => this.fmt(v);
        const n  = v => v != null ? new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v) : '—';
        const k  = this.state.kpis;
        const pct = (a, b) => b > 0 ? ` (${((a / b) * 100).toFixed(1)}% del total)` : '';
        switch (key) {
            case 'order_count':
                return `Pedidos confirmados del cliente en el período\n→ ${f(row.order_count)} pedidos de ${f(k.total_orders)} totales${pct(row.order_count, k.total_orders)}`;
            case 'qty_ordered':
                return `Piezas pedidas por el cliente en el período (suma de cantidades de todas las líneas)\n→ ${f(row.qty_ordered)} piezas de ${f(k.total_qty)} totales${pct(row.qty_ordered, k.total_qty)}` + this.svcNote();
            case 'qty_delivered':
                return `Cumplimiento de demanda: piezas ya entregadas de los pedidos del período del cliente (acumulado a la fecha, cualquier fecha de entrega). Mismo concepto que "Cumplimiento de demanda" del panel del cliente.\nQty entregada de las líneas de sus pedidos del período\n→ ${n(row.qty_delivered)} Pz entregadas de ${n(row.qty_ordered)} pedidas${row.delivery_pct != null ? ' (' + row.delivery_pct + '%)' : ''}` + this.svcNote();
            case 'total_amount':
                return `Monto de ventas del cliente en el período\n→ ${m(row.total_amount)} de ${m(k.total_amount)} total${pct(row.total_amount, k.total_amount)}` + this.amountNote() + this.svcNote();
            case 'delivery_pct':
                return `Tasa de cumplimiento: entregado de los pedidos del período (cualquier fecha de entrega) ÷ pedido\nQty entregada ÷ Qty pedida × 100\n→ ${n(row.qty_delivered)} u ÷ ${n(row.qty_ordered)} u = ${row.delivery_pct != null ? row.delivery_pct + '%' : '—'}`;
            case 'lead_time':
                return `Lead time de entrega (método principal: ${this.leadMethodLabel()}, configurable en Ajustes). Días desde la confirmación del pedido hasta la fecha efectiva de cada remito.\nPonderado por cantidad: ${this.fmtDays(row.lead_weighted)} (cuántos días esperó la pieza promedio)\nPrimera entrega: ${this.fmtDays(row.lead_first)} (promedio de días hasta el primer remito)\nPedido completo: ${this.fmtDays(row.lead_complete)} (solo pedidos 100% entregados: ${row.lt_comp_n || 0} de ${row.order_count})`;
            case 'ontime_pct':
                return `Entregas realizadas dentro del plazo acordado respecto al total de entregas del cliente\nEntregas a tiempo ÷ Total entregas × 100\n→ ${row.ontime_ok} ÷ ${row.ontime_total} = ${row.ontime_pct != null ? row.ontime_pct + '%' : '—'}`;
            case 'avg_price':
                return `Precio promedio por unidad del cliente en el período\nMonto total ÷ Demanda real\n→ ${m(row.total_amount)} ÷ ${f(row.qty_ordered)} = ${m(row.avg_price)}` + this.amountNote() + this.svcNote();
            case 'trend_pct':
                return `Variación del monto vs período anterior de igual duración\n((Actual - Anterior) ÷ Anterior) × 100\n→ ((${m(row.total_amount)} - ${m(row.prev_amount)}) ÷ ${m(row.prev_amount)}) × 100 = ${row.trend_pct != null ? row.trend_pct + '%' : '—'}`;
            case 'days_since_last':
                return `Días transcurridos desde el último pedido hasta hoy\n→ Último pedido: ${row.last_order_date || '?'} (${row.days_since_last} días)\nUmbral de riesgo: ${this.state.config.risk_days || 90} días`;
            case 'avg_days_between':
                return `Promedio de días entre pedidos consecutivos del cliente en el período\n→ ${row.order_count} pedido${row.order_count !== 1 ? 's' : ''} → ${Math.max(0, row.order_count - 1)} intervalo${row.order_count > 2 ? 's' : ''} = ${row.avg_days_between != null ? row.avg_days_between + ' días promedio' : 'sin datos (1 solo pedido)'}`;
            case 'last_order_date':
                return `Fecha del último pedido confirmado del cliente en el período\n→ ${row.last_order_date || '—'} (hace ${row.days_since_last} días)`;
            case 'distinct_products':
                return `Artículos distintos (variantes de producto) comprados en el período\n→ ${f(row.distinct_products)} artículo${row.distinct_products !== 1 ? 's' : ''} distintos en ${row.order_count} pedido${row.order_count !== 1 ? 's' : ''}`;
            case 'frequency_segment':
                return `Segmento de frecuencia basado en días entre pedidos y días sin comprar\nFrecuente: días_entre ≤ 30 | Ocasional: 31–90 d | Inactivo: > 90 d | En riesgo: sin comprar > ${this.state.config.risk_days || 90} días\n→ Días entre pedidos: ${row.avg_days_between != null ? row.avg_days_between + ' d' : '—'}  |  Sin comprar: ${row.days_since_last} d  →  ${row.frequency_segment}`;
            default:
                return '';
        }
    }

    prodCellTooltip(prod) {
        if (!prod || prod.qty_ordered == null) return '';
        const n = v => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
        return `Tasa de cumplimiento: entregado de los pedidos del período respecto a lo pedido de este artículo\nQty entregada ÷ Qty pedida × 100\n→ ${n(prod.qty_delivered)} u ÷ ${n(prod.qty_ordered)} u = ${prod.delivery_pct != null ? prod.delivery_pct + '%' : '—'}`;
    }


    /**
     * Desglose "por mes de confirmación del pedido" para los tooltips de la tasa
     * física: indica de qué mes son los pedidos que originaron las entregas.
     * @param {Object} byMonth - {'YYYY-MM': qty}
     * @returns {string} Bloque de texto (vacío si no hay datos)
     */
    _physBreak(byMonth) {
        const months = Object.keys(byMonth || {}).sort();
        if (!months.length) return '';
        const n = v => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
        const lines = months.map(ym => {
            const [y, m] = ym.split('-');
            const label = new Date(+y, +m - 1, 1).toLocaleString('es', { month: 'long', year: 'numeric' });
            return `  ${label}: ${n(byMonth[ym])} u`;
        });
        return '\nPor mes de confirmación del pedido:\n' + lines.join('\n');
    }

    colTitle(col) {
        const titles = {
            partner_name:      'Nombre del cliente. Clic para ordenar.',
            customer_category: 'Categoría de cliente (A–E) calculada globalmente por el módulo según el método configurado en Ajustes.',
            abc_segment:       'ABC del período — calculado al vuelo con las compras del rango de fechas visible.\nSe ordenan los clientes de mayor a menor facturación del período y se acumula su participación sobre el total: el primer tramo acumulado (A%, def. 20%) = A; hasta A%+B% (def. 20%+50% = 70%) = B; el resto = C. El cliente de mayor facturación siempre es A.\nEs independiente de la categoría permanente del contacto (columna "Cat. global", que se calcula aparte) y cambia al cambiar el rango de fechas.\nUmbrales configurables en Ajustes → Análisis de clientes.',
            salesperson:       'Vendedor más frecuente en los pedidos del período.',
            country:           'País del cliente. Clic para ordenar.',
            province:          'Provincia del cliente. Clic para ordenar.',
            order_count:       'Cantidad de pedidos de venta confirmados en el período.',
            qty_ordered:       'Demanda real: total de piezas pedidas por el cliente en el período (suma de cantidades de todas las líneas).',
            qty_delivered:     'Cumplimiento de demanda: piezas ya entregadas de los pedidos del período (acumulado a la fecha, cualquier fecha de entrega). Es el numerador de la tasa de cumplimiento.',
            total_amount:      'Monto total neto (sin impuestos) de pedidos confirmados en el período.',
            avg_price:         'Precio promedio: monto total ÷ piezas pedidas del período.',
            delivery_pct:      'Tasa de cumplimiento: entregado (acumulado a la fecha, cualquier fecha de entrega) de los pedidos confirmados en el período ÷ pedido en el período × 100. Responde "de lo que pidió en el período, ¿cuánto ya le entregué?". Semáforo configurable en Ajustes.',
            lead_time:         'Lead time de entrega (' + this.leadMethodLabel() + '): días desde la confirmación del pedido hasta la fecha efectiva de entrega. Método principal configurable en Ajustes; el tooltip de cada celda muestra los tres métodos.',
            ontime_pct:        'Porcentaje de entregas realizadas dentro del plazo acordado. El plazo se define según el método configurado en Ajustes (fecha compromiso, fecha programada o SLA en días).',
            avg_days_between:  'Promedio de días entre pedidos consecutivos del cliente en el período.',
            days_since_last:   'Días desde el último pedido hasta hoy. Se resalta en rojo si supera el umbral de riesgo configurado en Ajustes.',
            last_order_date:   'Fecha del último pedido de venta confirmado.',
            distinct_products: 'Cantidad de productos distintos (variantes) comprados en el período.',
            top_product:       'Plantilla de producto con mayor monto en el período.',
            top_family:        'Familia de producto (categ_id) con mayor monto en el período.',
            trend_pct:         'Variación del monto vs el período anterior de igual duración. ▲ crecimiento, ▼ caída.',
            frequency_segment: 'Segmento de frecuencia: Frecuente (< 30 días entre pedidos), Ocasional (30–90 días), Inactivo (> 90 días), En riesgo (sin comprar hace más días que el umbral configurado).',
            partner_tag:       'Primera etiqueta de contacto asignada al cliente en Odoo (res.partner.category_id). Clic para ordenar.',
        };
        const base = titles[col.key] || '';
        if (['total_amount', 'avg_price', 'trend_pct'].includes(col.key)) {
            return base + this.amountNote() + this.svcNote();
        }
        if (['qty_ordered', 'qty_delivered'].includes(col.key)) {
            return base + this.svcNote();
        }
        return base;
    }

    get groupByDefs() {
        const base = [
            { key: 'salesperson',       label: 'Vendedor'             },
            { key: 'country',           label: 'País'                 },
            { key: 'province',          label: 'Provincia'            },
            { key: 'abc_segment',       label: 'Segmento ABC período' },
            { key: 'frequency_segment', label: 'Segmento frecuencia'  },
            { key: 'top_family',        label: 'Familia principal'    },
            { key: 'partner_tag',       label: 'Etiqueta'             },
        ];
        if (this.state.config.show_category) {
            base.unshift({ key: 'customer_category', label: 'Cat. global' });
        }
        return base;
    }
}

registry.category("view_widgets").add("customer_analysis_widget", { component: CustomerAnalysisWidget });
