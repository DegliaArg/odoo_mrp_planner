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
import { destroyPanelCharts, destroyCharts, drawTopChart, drawTopDonut, drawPanelCharts, CHART_COLORS } from "./customer_analysis_charts";

// ── Columnas estáticas (producto del menú de columnas) ────────────────────────
const CA_STATIC_COLS = [
    { key: 'partner_name',      label: 'Cliente',          width: 200, fixed: true,  align: 'start'  },
    { key: 'customer_category', label: 'Cat. global',        width:  80, align: 'center' },
    { key: 'abc_segment',       label: 'ABC período',        width:  80, align: 'center' },
    { key: 'salesperson',       label: 'Vendedor',          width: 130, align: 'start'  },
    { key: 'country',           label: 'País',              width: 110, align: 'start'  },
    { key: 'province',          label: 'Provincia',         width: 120, align: 'start'  },
    { key: 'order_count',       label: 'Pedidos',           width:  75, align: 'end'    },
    { key: 'qty_ordered',       label: 'Piezas',            width:  90, align: 'end'    },
    { key: 'total_amount',      label: 'Monto',             width: 110, align: 'end'    },
    { key: 'avg_price',         label: 'P. prom.',          width: 110, align: 'end'    },
    { key: 'delivery_pct',      label: '% Cumplim.',        width:  90, align: 'end'    },
    { key: 'physical_pct',      label: '% Físico',          width:  90, align: 'end'    },
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
    total_amount:      'total_amount',
    avg_price:         'avg_price',
    delivery_pct:      'delivery_pct',
    physical_pct:      'physical_pct',
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
            kpis:          { total_customers: 0, total_orders: 0, avg_price: 0, avg_delivery_pct: null, avg_physical_pct: null, avg_ontime_pct: null, avg_days_between: null },
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
            tableTotals:   { count: 0, orders: 0, qty: 0, amount: 0 },
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
                total_amount:      true,
                avg_price:         true,
                delivery_pct:      true,
                physical_pct:      true,
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
                this.state.dateFrom,
                this.state.dateTo,
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
            this.state.kpis    = res.kpis  || {};
            this.state.config  = res.config || {};
            if (res.config && !res.config.show_category) {
                this.state.visibleCols.customer_category = false;
            }
            this._applySort();
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
        // Filtros de segmento
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

        // Los KPIs siguen el conjunto filtrado/buscado (sin filtro de pestaña),
        // mismas fórmulas que el backend.
        this.state.kpis = { ...this.state.kpis, ...this._computeKpis(rows) };

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

        this.state.totalFiltered = rows.length;
        this._filteredRows = rows;   // tabla visible y export (incluye pestaña activa)

        // Totales del pie: reflejan exactamente lo que muestra la tabla.
        this.state.tableTotals = {
            count:  rows.length,
            orders: rows.reduce((s, r) => s + (r.order_count || 0), 0),
            qty:    Math.round(rows.reduce((s, r) => s + (r.qty_ordered || 0), 0) * 10) / 10,
            amount: Math.round(rows.reduce((s, r) => s + (r.total_amount || 0), 0) * 100) / 100,
        };

        // Paginación (si la página quedó fuera de rango tras filtrar, volver a la 1)
        if ((Math.max(1, this.state.page) - 1) * this.state.pageSize >= rows.length && rows.length) {
            this.state.page = 1;
        }
        const offset    = (Math.max(1, this.state.page) - 1) * this.state.pageSize;
        this.state.rows = rows.slice(offset, offset + this.state.pageSize);
    }

    /**
     * Pestañas de agrupamiento: un grupo por valor del campo activo, con conteo,
     * calculadas sobre el conjunto filtrado/buscado (sin la pestaña aplicada).
     * @returns {Array<{key: string, label: string, count: number}>|null}
     */
    get allGroupsForTabs() {
        const gb = this.state.groupBy;
        if (!gb) return null;
        const counts = new Map();
        for (const r of this._baseFiltered()) {
            const key = r[gb] || '—';
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        return [...counts.entries()]
            .sort((a, b) => a[0].localeCompare(b[0], 'es', { sensitivity: 'base' }))
            .map(([key, count]) => ({ key, label: key, count }));
    }

    setGroup(key) {
        this.state.selectedGroup = key;
        this.state.page = 1;
        this._applySort();
    }

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
        const avg = (key) => {
            const vals = rows.map(r => r[key]).filter(v => v !== null && v !== undefined);
            return vals.length ? Math.round(vals.reduce((s, v) => s + v, 0) / vals.length * 10) / 10 : null;
        };
        const nOf = (key) => rows.filter(r => r[key] !== null && r[key] !== undefined).length;
        return {
            total_customers:  rows.length,
            total_orders:     totalOrders,
            total_amount:     Math.round(totalAmount * 100) / 100,
            total_qty:        Math.round(totalQty * 10) / 10,
            avg_price:        totalQty ? Math.round(totalAmount / totalQty * 100) / 100 : 0,
            avg_delivery_pct: avg('delivery_pct'),
            avg_physical_pct: avg('physical_pct'),
            avg_ontime_pct:   avg('ontime_pct'),
            avg_days_between: avg('avg_days_between'),
            delivery_n:       nOf('delivery_pct'),
            physical_n:       nOf('physical_pct'),
            ontime_n:         nOf('ontime_pct'),
        };
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
        this._topChartKey = '';
        this._topDonutKey = '';
        if (synced) {
            this._chartAllRows = null;
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
        if (!this._chartAllRows) return this._filteredRows || this.state.allRows;
        return this._baseFiltered(this._chartAllRows);
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

    setFilterCategory(v) { this.state.filterCategory = v; this.state.page = 1; this._topChartKey = ''; this._topDonutKey = ''; this._applySort(); }
    setFilterABC(v)      { this.state.filterABC      = v; this.state.page = 1; this._topChartKey = ''; this._topDonutKey = ''; this._applySort(); }
    setFilterFreq(v)     { this.state.filterFreq     = v; this.state.page = 1; this._topChartKey = ''; this._topDonutKey = ''; this._applySort(); }

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

    nextPage() {
        const maxPage = Math.ceil(this.state.totalFiltered / this.state.pageSize);
        if (this.state.page < maxPage) { this.state.page++; this._applySort(); }
    }

    prevPage() {
        if (this.state.page > 1) { this.state.page--; this._applySort(); }
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.state.totalFiltered / this.state.pageSize));
    }

    get hasPrevPage() { return this.state.page > 1; }
    get hasNextPage()  { return this.state.page < this.totalPages; }

    // ── Panel lateral ─────────────────────────────────────────────────────────

    async toggleDetail(partnerId) {
        if (this.state.panelPartnerId === partnerId) {
            this.state.panelPartnerId = null;
            this.state.panelData      = null;
            this._lastPanelKey        = null;
            this._destroyPanelCharts();
            return;
        }
        this._destroyPanelCharts();
        this._lastPanelKey        = null;
        this.state.panelPartnerId = partnerId;
        this.state.panelData      = null;
        this.state.panelLoading   = true;
        // Si se abre el panel, cerrar la fila expandida del mismo cliente
        if (this.state.expandedRows[partnerId]) {
            this.state.expandedRows[partnerId] = false;
        }
        try {
            // Con "Unificar por CUIT" la fila puede agrupar varios partners:
            // el panel agrega los pedidos de todos ellos.
            const row = this.state.allRows.find(r => r.partner_id === partnerId);
            const partnerIds = (row && row.partner_ids) || [partnerId];
            const data = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_detail',
                [partnerId, this.state.dateFrom, this.state.dateTo, null, partnerIds]
            );
            this.state.panelData = data;
        } catch (e) {
            console.error('[CustomerAnalysis] toggleDetail', e);
        } finally {
            this.state.panelLoading = false;
        }
    }

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

    setPanelMetric(m) {
        if (this.state.panelMetric !== m) {
            this.state.panelMetric   = m;
            this.state.panelProdSort = m === 'qty' ? 'qty_ordered' : 'amount';
            this.state.panelProdDir  = 'desc';
            this._panelDonutsKey     = '';
            this._panelChartKey      = '';
        }
    }
    setPanelChartMode(mode) {
        if (this.state.panelChartMode !== mode) {
            this.state.panelChartMode = mode;
            this._panelChartKey       = '';
        }
    }
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
    setPanelTopN(n) { this.state.panelTopN = n; }

    sortPanelProds(key) {
        if (this.state.panelProdSort === key) {
            this.state.panelProdDir = this.state.panelProdDir === 'desc' ? 'asc' : 'desc';
        } else {
            this.state.panelProdSort = key;
            this.state.panelProdDir  = 'desc';
        }
    }

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

    sortRowOrders(key) {
        if (this.state.rowOrderSort === key) {
            this.state.rowOrderDir = this.state.rowOrderDir === 'desc' ? 'asc' : 'desc';
        } else {
            this.state.rowOrderSort = key;
            this.state.rowOrderDir  = 'desc';
        }
    }

    getSortedOrders(partnerId) {
        const orders = this.state.rowOrders[partnerId] || [];
        const key    = this.state.rowOrderSort;
        const dir    = this.state.rowOrderDir === 'desc' ? -1 : 1;
        return [...orders].sort((a, b) => {
            const va = a[key] ?? -Infinity;
            const vb = b[key] ?? -Infinity;
            if (typeof va === 'string') return dir * va.localeCompare(vb, 'es', { sensitivity: 'base' });
            return dir * (va - vb);
        });
    }

    orderStateBadgeClass(state) {
        return {
            'Confirmado': 'badge text-bg-primary',
            'Hecho':      'badge text-bg-success',
            'Cancelado':  'badge text-bg-danger',
            'Borrador':   'badge text-bg-secondary',
        }[state] || 'badge text-bg-secondary';
    }

    get panelTopProducts() {
        const all = this.state.panelData?.top_products || [];
        const key = this.state.panelProdSort;
        const dir = this.state.panelProdDir === 'desc' ? -1 : 1;
        const sorted = [...all].sort((a, b) => {
            const va = a[key] ?? (typeof a[key] === 'string' ? '' : -Infinity);
            const vb = b[key] ?? (typeof b[key] === 'string' ? '' : -Infinity);
            if (typeof va === 'string') return dir * va.localeCompare(vb, 'es', { sensitivity: 'base' });
            return dir * (va - vb);
        });
        return sorted.slice(0, this.state.panelTopN);
    }

    _drawTopChart() { drawTopChart(this); }

    _drawTopDonut() { drawTopDonut(this); }

    // ── Filas expandibles ─────────────────────────────────────────────────────

    async toggleRow(partnerId) {
        const isOpen = !!this.state.expandedRows[partnerId];
        this.state.expandedRows[partnerId] = !isOpen;
        // Si se abre la fila de pedidos, cerrar el panel de análisis del mismo cliente
        if (!isOpen && this.state.panelPartnerId === partnerId) {
            this.state.panelPartnerId = null;
            this.state.panelData      = null;
            this._destroyPanelCharts();
        }
        if (!isOpen && !this.state.rowOrders[partnerId]) {
            this.state.rowOrdersLoading[partnerId] = true;
            try {
                const row = this.state.allRows.find(r => r.partner_id === partnerId);
                const partnerIds = (row && row.partner_ids) || [partnerId];
                const data = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_customer_detail',
                    [partnerId, this.state.dateFrom, this.state.dateTo, null, partnerIds]
                );
                this.state.rowOrders[partnerId] = data.orders || [];
            } catch (e) {
                console.error('[CustomerAnalysis] toggleRow', e);
                this.state.rowOrders[partnerId] = [];
            } finally {
                this.state.rowOrdersLoading[partnerId] = false;
            }
        }
    }

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
            domain,
            target: 'current',
        });
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
        const rows = this._filteredRows || this.state.allRows;

        const cellVal = (row, key) => {
            const v = row[key];
            if (v === null || v === undefined) return '';
            if (['delivery_pct', 'physical_pct', 'ontime_pct', 'trend_pct'].includes(key))
                return v.toFixed(1) + '%';
            if (['avg_days_between', 'days_since_last'].includes(key) && v !== null)
                return v + ' d';
            return v;
        };

        let xml = `<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
 <Worksheet ss:Name="Clientes">
  <Table>
   <Row>`;
        cols.forEach(c => {
            xml += `<Cell><Data ss:Type="String">${this._escXml(c.label)}</Data></Cell>`;
        });
        xml += '</Row>';
        rows.forEach(row => {
            xml += '<Row>';
            cols.forEach(c => {
                const v = cellVal(row, c.key);
                const type = typeof v === 'number' ? 'Number' : 'String';
                xml += `<Cell><Data ss:Type="${type}">${this._escXml(String(v))}</Data></Cell>`;
            });
            xml += '</Row>';
        });
        xml += `  </Table>
 </Worksheet>
</Workbook>`;

        const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `clientes_${this.state.dateFrom}_${this.state.dateTo}.xls`;
        a.click();
        URL.revokeObjectURL(url);
    }

    _escXml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
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
                return `Suma del importe sin impuestos de todos los pedidos del período.\nTotal: ${m(k.total_amount)} en ${f(k.total_orders)} pedidos`;
            case 'avg_price':
                return `Precio promedio por unidad del período\nMonto total ÷ Piezas pedidas\n→ ${m(k.total_amount)} ÷ ${f(k.total_qty)} = ${m(k.avg_price)}` + this.svcNote();
            case 'avg_delivery_pct':
                return `Tasa de cumplimiento promedio entre ${f(k.delivery_n)} clientes del período\nEntregado de los pedidos del período (cualquier fecha de entrega) ÷ pedido × 100, por cliente y luego promediado\n→ ${p(k.avg_delivery_pct)}`;
            case 'avg_physical_pct':
                return `Tasa física promedio entre ${f(k.physical_n)} clientes del período\nDespachado dentro del período (de cualquier pedido) ÷ pedido en el período × 100, por cliente y luego promediado\nPuede superar 100% si se despacharon pedidos de períodos anteriores\n→ ${p(k.avg_physical_pct)}`;
            case 'avg_ontime_pct':
                return `Promedio de % A tiempo entre ${f(k.ontime_n)} clientes con pickings realizados. Criterio: fecha entrega ≤ fecha compromiso (configurable en Ajustes)\nEntregas a tiempo ÷ Total entregas × 100 (por cliente, luego promediado)\n→ ${p(k.avg_ontime_pct)}`;
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
            case 'total_amount':
                return `Suma del importe sin impuestos de todos sus pedidos en el período\n→ ${m(row.total_amount)} de ${m(k.total_amount)} total${pct(row.total_amount, k.total_amount)}` + this.svcNote();
            case 'delivery_pct':
                return `Tasa de cumplimiento: entregado de los pedidos del período (cualquier fecha de entrega) ÷ pedido\nQty entregada ÷ Qty pedida × 100\n→ ${n(row.qty_delivered)} u ÷ ${n(row.qty_ordered)} u = ${row.delivery_pct != null ? row.delivery_pct + '%' : '—'}`;
            case 'physical_pct':
                return `Tasa física: despachado DENTRO del período (de cualquier pedido) ÷ pedido en el período\n→ ${n(row.qty_delivered_phys)} u ÷ ${n(row.qty_ordered)} u = ${row.physical_pct != null ? row.physical_pct + '%' : '—'}${this._physBreak(row.phys_by_order_month)}\nPuede superar 100% si se despacharon pedidos de períodos anteriores.`;
            case 'ontime_pct':
                return `Entregas realizadas dentro del plazo acordado respecto al total de entregas del cliente\nEntregas a tiempo ÷ Total entregas × 100\n→ ${row.ontime_ok} ÷ ${row.ontime_total} = ${row.ontime_pct != null ? row.ontime_pct + '%' : '—'}`;
            case 'avg_price':
                return `Precio promedio por unidad del cliente en el período\nMonto total ÷ Piezas pedidas\n→ ${m(row.total_amount)} ÷ ${f(row.qty_ordered)} = ${m(row.avg_price)}` + this.svcNote();
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

    prodPhysTooltip(prod) {
        if (!prod || prod.qty_ordered == null) return '';
        const n = v => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
        return `Tasa física: despachado DENTRO del período de este artículo ÷ pedido en el período\n→ ${n(prod.qty_delivered_phys)} u ÷ ${n(prod.qty_ordered)} u = ${prod.physical_pct != null ? prod.physical_pct + '%' : '—'}\nPuede superar 100% si se despacharon pedidos de períodos anteriores.`;
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
            qty_ordered:       'Total de piezas pedidas por el cliente en el período (suma de cantidades de todas las líneas).',
            total_amount:      'Monto total neto (sin impuestos) de pedidos confirmados en el período.',
            avg_price:         'Precio promedio: monto total ÷ piezas pedidas del período.',
            delivery_pct:      'Tasa de cumplimiento: entregado (acumulado a la fecha, cualquier fecha de entrega) de los pedidos confirmados en el período ÷ pedido en el período × 100. Responde "de lo que pidió en el período, ¿cuánto ya le entregué?". Semáforo configurable en Ajustes.',
            physical_pct:      'Tasa física: despachado DENTRO del período (salidas validadas de cualquier pedido, incluso anteriores) ÷ pedido en el período × 100. Responde "¿cuánto le despaché este período?". Puede superar 100% si se despacharon pedidos viejos. El tooltip de cada celda desglosa de qué mes son los pedidos entregados. Mismo semáforo que la tasa de cumplimiento.',
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
        if (['qty_ordered', 'total_amount', 'avg_price'].includes(col.key)) {
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
