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
import { useColManager } from "./column_manager";
import { PlannerSearchBar } from "./planner_search_bar";

// ── Columnas estáticas (producto del menú de columnas) ────────────────────────
const CA_STATIC_COLS = [
    { key: 'partner_name',      label: 'Cliente',          width: 200, fixed: true,  align: 'start'  },
    { key: 'customer_category', label: 'Cat. global',        width:  80, align: 'center' },
    { key: 'abc_segment',       label: 'ABC período',        width:  80, align: 'center' },
    { key: 'salesperson',       label: 'Vendedor',          width: 130, align: 'start'  },
    { key: 'country',           label: 'País',              width: 110, align: 'start'  },
    { key: 'province',          label: 'Provincia',         width: 120, align: 'start'  },
    { key: 'order_count',       label: 'Pedidos',           width:  75, align: 'end'    },
    { key: 'total_amount',      label: 'Monto',             width: 110, align: 'end'    },
    { key: 'avg_ticket',        label: 'Ticket prom.',      width: 110, align: 'end'    },
    { key: 'delivery_pct',      label: '% Entrega',         width:  90, align: 'end'    },
    { key: 'ontime_pct',        label: '% A tiempo',        width:  90, align: 'end'    },
    { key: 'avg_days_between',  label: 'Frecuencia',        width:  95, align: 'end'    },
    { key: 'days_since_last',   label: 'Días sin comprar',  width: 110, align: 'end'    },
    { key: 'last_order_date',   label: 'Última compra',     width: 110, align: 'end'    },
    { key: 'distinct_products', label: 'Productos',         width:  80, align: 'end'    },
    { key: 'top_product',       label: 'Top producto',      width: 160, align: 'start'  },
    { key: 'top_family',        label: 'Familia principal', width: 140, align: 'start'  },
    { key: 'trend_pct',         label: 'Tendencia',         width:  90, align: 'end'    },
    { key: 'frequency_segment', label: 'Segmento freq.',    width: 110, align: 'center' },
];

const CA_SORT_KEYS = {
    partner_name:      'partner_name',
    customer_category: 'customer_category',
    abc_segment:       'abc_segment',
    salesperson:       'salesperson',
    country:           'country',
    province:          'province',
    order_count:       'order_count',
    total_amount:      'total_amount',
    avg_ticket:        'avg_ticket',
    delivery_pct:      'delivery_pct',
    ontime_pct:        'ontime_pct',
    avg_days_between:  'avg_days_between',
    days_since_last:   'days_since_last',
    last_order_date:   'last_order_date',
    distinct_products: 'distinct_products',
    top_product:       'top_product',
    top_family:        'top_family',
    trend_pct:         'trend_pct',
    frequency_segment: 'frequency_segment',
};

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function defaultPeriod() {
    const now = new Date();
    const from = new Date(now);
    from.setDate(from.getDate() - 90);
    return { from: toDateStr(from), to: toDateStr(now) };
}

function monthLabel(ym) {
    const [y, mStr] = ym.split('-');
    return `${MONTHS_ES[parseInt(mStr) - 1]} ${y}`;
}

// Paleta idéntica al panel de ventas — mismos colores por cat. ABC
const CAT_COLORS = {
    A:  'rgba(25, 135, 84,  0.80)',
    B:  'rgba(13, 110, 253, 0.80)',
    C:  'rgba(255, 193, 7,  0.85)',
    D:  'rgba(108, 117, 125, 0.80)',
    E:  'rgba(200, 210, 220, 0.90)',
    '': 'rgba(108, 117, 125, 0.65)',
};

const FREQ_COLORS = {
    frecuente: 'rgba(25, 135, 84,  0.80)',
    ocasional: 'rgba(255, 193, 7,  0.85)',
    en_riesgo: 'rgba(220, 53,  69, 0.75)',
    inactivo:  'rgba(108, 117, 125, 0.80)',
    '':        'rgba(108, 117, 125, 0.65)',
};

const CHART_COLORS = {
    bar:    'rgba(13, 110, 253, 0.75)',
    line:   'rgba(25, 135, 84, 0.85)',
    donut: [
        'rgba(13, 110, 253, 0.80)',
        'rgba(25, 135, 84, 0.80)',
        'rgba(255, 193, 7,  0.85)',
        'rgba(220, 53,  69, 0.75)',
        'rgba(108, 117, 125, 0.75)',
        'rgba(102, 16, 242, 0.70)',
        'rgba(253, 126, 20, 0.75)',
        'rgba(32, 201, 151, 0.75)',
        'rgba(214, 51, 132, 0.75)',
        'rgba(13, 202, 240, 0.75)',
    ],
};

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

        this.barRef    = useRef("panelBarCanvas");
        this.donutRef  = useRef("panelDonutCanvas");
        this.lineRef   = useRef("panelLineCanvas");
        this._barChart   = null;
        this._donutChart = null;
        this._lineChart  = null;

        this.cols     = useColManager('customer_analysis', CA_STATIC_COLS);
        this.caSortKeys = CA_SORT_KEYS;

        const period = defaultPeriod();
        this.state = useState({
            loading:       true,
            loadError:     null,
            dateFrom:      period.from,
            dateTo:        period.to,
            allRows:       [],
            rows:          [],
            kpis:          { total_customers: 0, avg_ticket: 0, avg_delivery_pct: null, avg_ontime_pct: null, avg_days_between: null },
            config:        {},
            sortCol:       'total_amount',
            sortDir:       'desc',
            page:          1,
            pageSize:      50,
            totalFiltered: 0,
            productSearch: '',
            activeFilter:  null,
            groupBy:       null,
            colsDropdownOpen: false,
            // Filtros de los gráficos superiores
            chartMetric: 'pxq',
            chartTopN:   10,
            chartDonut:  'abc',
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
            panelTopN:      10,
            // Columnas visibles
            visibleCols: {
                customer_category: false,
                abc_segment:       true,
                salesperson:       false,
                country:           false,
                province:          false,
                order_count:       true,
                total_amount:      true,
                avg_ticket:        true,
                delivery_pct:      true,
                ontime_pct:        false,
                avg_days_between:  false,
                days_since_last:   false,
                last_order_date:   false,
                distinct_products: false,
                top_product:       false,
                top_family:        false,
                trend_pct:         false,
                frequency_segment: true,
            },
        });

        this._closeDropdowns = () => {
            this.state.colsDropdownOpen = false;
        };

        onMounted(async () => {
            document.addEventListener('click', this._closeDropdowns);
            await this._load();
        });

        onPatched(() => {
            setTimeout(() => {
                this._drawTopChart();
                this._drawTopDonut();
                if (this.state.panelPartnerId && this.state.panelData && !this.state.panelLoading) {
                    this._drawPanelCharts();
                }
            }, 0);
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

    _applySort() {
        let rows = [...this.state.allRows];
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

        this.state.totalFiltered = rows.length;
        this._filteredRows = rows;

        // Agrupamiento (sólo afecta la vista, no el orden interno del grupo)
        if (this.state.groupBy) {
            this._groupedRows = this._buildGroups(rows);
            this.state.rows   = [];  // se usa _groupedRows en el template
        } else {
            this._groupedRows = null;
            const offset      = (Math.max(1, this.state.page) - 1) * this.state.pageSize;
            this.state.rows   = rows.slice(offset, offset + this.state.pageSize);
        }
    }

    _buildGroups(rows) {
        const gb = this.state.groupBy;
        const groups = new Map();
        for (const r of rows) {
            const key = r[gb] || '—';
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(r);
        }
        return Array.from(groups.entries())
            .sort((a, b) => a[0].localeCompare(b[0], 'es', { sensitivity: 'base' }))
            .map(([label, items]) => ({
                label,
                items,
                total_amount:  items.reduce((s, r) => s + (r.total_amount || 0), 0),
                order_count:   items.reduce((s, r) => s + (r.order_count  || 0), 0),
            }));
    }

    // ── Handlers de controles ─────────────────────────────────────────────────

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this._load(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this._load(); }

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

    get groupedRows() {
        return this._groupedRows || [];
    }

    // ── Panel lateral ─────────────────────────────────────────────────────────

    async toggleDetail(partnerId) {
        if (this.state.panelPartnerId === partnerId) {
            this.state.panelPartnerId = null;
            this.state.panelData      = null;
            this._destroyPanelCharts();
            return;
        }
        this._destroyPanelCharts();
        this.state.panelPartnerId = partnerId;
        this.state.panelData      = null;
        this.state.panelLoading   = true;
        try {
            const data = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_detail',
                [partnerId, this.state.dateFrom, this.state.dateTo, null]
            );
            this.state.panelData = data;
        } catch (e) {
            console.error('[CustomerAnalysis] toggleDetail', e);
        } finally {
            this.state.panelLoading = false;
        }
    }

    _destroyPanelCharts() {
        if (this._barChart)   { this._barChart.destroy();   this._barChart   = null; }
        if (this._donutChart) { this._donutChart.destroy(); this._donutChart = null; }
        if (this._lineChart)  { this._lineChart.destroy();  this._lineChart  = null; }
        this._panelChartsKey = '';
    }

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

    _destroyCharts() {
        if (this._topChart)      { this._topChart.destroy();      this._topChart      = null; this._topChartKey  = ''; }
        if (this._topDonutChart) { this._topDonutChart.destroy(); this._topDonutChart = null; this._topDonutKey  = ''; }
        if (this._barChart)      { this._barChart.destroy();      this._barChart      = null; }
        if (this._donutChart)    { this._donutChart.destroy();    this._donutChart    = null; }
        if (this._lineChart)     { this._lineChart.destroy();     this._lineChart     = null; }
    }

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
        if (this.state.panelMetric !== m) { this.state.panelMetric = m; this._panelChartsKey = ''; }
    }
    setPanelTopN(n) { this.state.panelTopN = n; }

    get panelTopProducts() {
        return (this.state.panelData?.top_products || []).slice(0, this.state.panelTopN);
    }

    _drawTopChart() {
        const el = this.topChartRef.el;
        if (!el) return;
        const metric      = this.state.chartMetric;
        const topN        = this.state.chartTopN;   // null = todos
        const allFiltered = this._filteredRows || this.state.allRows;
        if (!allFiltered.length) return;

        const key = `${allFiltered.length}_${metric}_${topN}_${this.state.filterCategory}_${this.state.filterABC}_${this.state.filterFreq}`;
        if (key === this._topChartKey) return;
        this._topChartKey = key;

        const ChartJs = globalThis.Chart;
        if (typeof ChartJs === 'undefined') return;
        if (this._topChart) { this._topChart.destroy(); this._topChart = null; }

        const fieldMap = { pxq: 'total_amount', pedidos: 'order_count', ticket: 'avg_ticket' };
        const field    = fieldMap[metric] || 'total_amount';
        const sorted   = [...allFiltered].sort((a, b) => (b[field] ?? 0) - (a[field] ?? 0));
        const rows     = topN !== null ? sorted.slice(0, topN) : sorted;
        const isAmt    = metric !== 'pedidos';
        const fmtTip   = isAmt
            ? v => '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v)
            : v => new Intl.NumberFormat('es-AR').format(v) + ' ped.';

        this._topChart = new ChartJs(el, {
            type: 'bar',
            data: {
                labels: rows.map(r => r.partner_name.length > 18 ? r.partner_name.slice(0, 16) + '…' : r.partner_name),
                datasets: [{
                    label:           metric === 'pxq' ? 'PxQ' : metric === 'pedidos' ? 'Pedidos' : 'Ticket prom.',
                    data:            rows.map(r => r[field]),
                    backgroundColor: rows.map(r => CAT_COLORS[r.abc_segment] ?? CAT_COLORS['']),
                    borderRadius:    3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => rows[items[0].dataIndex].partner_name,
                            label: ctx  => fmtTip(ctx.raw),
                        },
                    },
                },
                scales: {
                    x: {
                        grid:  { display: false },
                        ticks: { font: { size: 11 }, maxRotation: 45 },
                    },
                    y: {
                        beginAtZero: true,
                        grid:  { color: 'rgba(0,0,0,0.06)' },
                        ticks: { callback: v => this.fmtK(v), font: { size: 11 } },
                    },
                },
            },
        });
    }

    _drawTopDonut() {
        const el = this.topDonutRef.el;
        if (!el) return;
        const rows = this._filteredRows || this.state.allRows;
        if (!rows.length) return;

        const donutType = this.state.chartDonut;
        const key = `${rows.length}_${donutType}_${this.state.filterCategory}_${this.state.filterABC}_${this.state.filterFreq}`;
        if (key === this._topDonutKey) return;
        this._topDonutKey = key;

        const ChartJs = globalThis.Chart;
        if (typeof ChartJs === 'undefined') return;
        if (this._topDonutChart) { this._topDonutChart.destroy(); this._topDonutChart = null; }

        let groupField, colorMap, nameMap, order;
        if (donutType === 'abc') {
            groupField = 'abc_segment';
            colorMap   = CAT_COLORS;
            nameMap    = { A: 'Seg. A', B: 'Seg. B', C: 'Seg. C', '': 'Sin seg.' };
            order      = ['A', 'B', 'C', ''];
        } else if (donutType === 'cat') {
            groupField = 'customer_category';
            colorMap   = CAT_COLORS;
            nameMap    = { A: 'Cat. A', B: 'Cat. B', C: 'Cat. C', D: 'Cat. D', E: 'Cat. E', '': 'Sin cat.' };
            order      = ['A', 'B', 'C', 'D', 'E', ''];
        } else {
            groupField = 'frequency_segment';
            colorMap   = FREQ_COLORS;
            nameMap    = { frecuente: 'Frecuente', ocasional: 'Ocasional', en_riesgo: 'En riesgo', inactivo: 'Inactivo', '': 'Sin datos' };
            order      = ['frecuente', 'ocasional', 'en_riesgo', 'inactivo', ''];
        }

        const byGroup = {};
        for (const r of rows) {
            const k = r[groupField] || '';
            if (!byGroup[k]) byGroup[k] = { count: 0, amount: 0 };
            byGroup[k].count++;
            byGroup[k].amount += r.total_amount || 0;
        }
        const cats  = order.filter(c => byGroup[c]);
        const total = cats.reduce((s, c) => s + byGroup[c].count, 0);
        const fmtAmt = v => '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v);

        const pieLabelPlugin = {
            id: 'pieLabelsTop',
            afterDatasetsDraw(chart) {
                const { ctx, data } = chart;
                const ds  = data.datasets[0];
                const ttl = ds.data.reduce((a, b) => a + b, 0);
                chart.getDatasetMeta(0).data.forEach((arc, i) => {
                    const pct = ttl ? Math.round(ds.data[i] / ttl * 100) : 0;
                    if (pct < 5) return;
                    const { x, y } = arc.getCenterPoint();
                    ctx.save();
                    ctx.fillStyle    = '#fff';
                    ctx.font         = 'bold 11px sans-serif';
                    ctx.textAlign    = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.shadowColor  = 'rgba(0,0,0,0.35)';
                    ctx.shadowBlur   = 3;
                    ctx.fillText(`${pct}%`, x, y);
                    ctx.restore();
                });
            },
        };

        this._topDonutChart = new ChartJs(el, {
            type: 'doughnut',
            data: {
                labels:   cats.map(c => nameMap[c] || c),
                datasets: [{
                    data:            cats.map(c => byGroup[c].count),
                    backgroundColor: cats.map(c => colorMap[c] ?? CAT_COLORS['']),
                    borderWidth:  1,
                    borderColor:  '#fff',
                }],
            },
            plugins: [pieLabelPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '48%',
                plugins: {
                    legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 6, boxWidth: 14 } },
                    tooltip: {
                        callbacks: {
                            title: items => nameMap[cats[items[0].dataIndex]] || cats[items[0].dataIndex],
                            label: ctx => {
                                const d   = byGroup[cats[ctx.dataIndex]];
                                const pct = total ? Math.round(d.count / total * 100) : 0;
                                return [
                                    `  ${d.count} clientes (${pct}%)`,
                                    `  Monto: ${fmtAmt(d.amount)}`,
                                ];
                            },
                        },
                    },
                },
            },
        });
    }

    // ── Filas expandibles ─────────────────────────────────────────────────────

    async toggleRow(partnerId) {
        const isOpen = !!this.state.expandedRows[partnerId];
        this.state.expandedRows[partnerId] = !isOpen;
        if (!isOpen && !this.state.rowOrders[partnerId]) {
            this.state.rowOrdersLoading[partnerId] = true;
            try {
                const data = await this.orm.call(
                    'mrp.planner.dashboard',
                    'get_customer_detail',
                    [partnerId, this.state.dateFrom, this.state.dateTo, null]
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

    openCustomerOrders(partnerId) {
        this.action.doAction({
            type:      'ir.actions.act_window',
            name:      'Pedidos del período',
            res_model: 'sale.order',
            views:     [[false, 'list'], [false, 'form']],
            domain: [
                ['partner_id', 'child_of', partnerId],
                ['state', 'in', ['sale', 'done']],
                ['date_order', '>=', this.state.dateFrom + ' 00:00:00'],
                ['date_order', '<=', this.state.dateTo   + ' 23:59:59'],
            ],
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

    _drawPanelCharts() {
        const data = this.state.panelData;
        if (!data) return;
        const Chart = globalThis.Chart;
        if (typeof Chart === 'undefined') return;

        const panelKey = `${this.state.panelPartnerId}_${this.state.panelMetric}`;
        if (this._panelChartsKey === panelKey) return;
        this._panelChartsKey = panelKey;

        const isQty   = this.state.panelMetric === 'qty';
        const fmtTick = isQty
            ? v => (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)))
            : v => this.fmtK(v);
        const fmtLbl  = isQty
            ? v => (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)))
            : v => this.fmtK(v);

        const barLabelPlugin = {
            id: 'barLabel',
            afterDatasetsDraw(chart) {
                const { ctx } = chart;
                chart.data.datasets.forEach((ds, i) => {
                    const meta = chart.getDatasetMeta(i);
                    if (meta.hidden) return;
                    meta.data.forEach((bar, idx) => {
                        const v = ds.data[idx];
                        if (!v) return;
                        const label = ds._fmt ? ds._fmt(v) : String(v);
                        ctx.save();
                        ctx.fillStyle = '#555';
                        ctx.font = 'bold 9px sans-serif';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'bottom';
                        ctx.fillText(label, bar.x, bar.y - 2);
                        ctx.restore();
                    });
                });
            },
        };

        // ── Barras agrupadas: pedido vs entregado ────────────────────────────
        const barEl = this.barRef.el;
        if (barEl && data.monthly_data && data.monthly_data.length) {
            if (this._barChart) { this._barChart.destroy(); this._barChart = null; }
            const labels    = data.monthly_data.map(m => monthLabel(m.month));
            const dsPedido  = {
                label:           isQty ? 'Pedido (u)' : 'Pedido ($)',
                data:            data.monthly_data.map(m => isQty ? m.qty_ordered   : m.amount),
                backgroundColor: 'rgba(13,110,253,0.75)',
                borderRadius:    3,
                _fmt:            fmtLbl,
            };
            const dsEntrega = {
                label:           isQty ? 'Entregado (u)' : 'Entregado ($)',
                data:            data.monthly_data.map(m => isQty ? m.qty_delivered : m.amount_delivered),
                backgroundColor: 'rgba(25,135,84,0.70)',
                borderRadius:    3,
                _fmt:            fmtLbl,
            };
            this._barChart = new Chart(barEl, {
                type: 'bar',
                data: { labels, datasets: [dsPedido, dsEntrega] },
                options: {
                    responsive:          true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: true, labels: { font: { size: 11 }, boxWidth: 12 } },
                        barLabel: {},
                    },
                    scales: {
                        x: { ticks: { font: { size: 10 } } },
                        y: { ticks: { callback: fmtTick, font: { size: 10 } } },
                    },
                },
                plugins: [barLabelPlugin],
            });
        }

        // ── Donut: mix de familias ───────────────────────────────────────────
        const donutEl = this.donutRef.el;
        if (donutEl && data.family_mix && data.family_mix.length) {
            if (this._donutChart) { this._donutChart.destroy(); this._donutChart = null; }
            this._donutChart = new Chart(donutEl, {
                type: 'doughnut',
                data: {
                    labels:   data.family_mix.map(f => f.name),
                    datasets: [{
                        data:            data.family_mix.map(f => f.amount),
                        backgroundColor: CHART_COLORS.donut,
                        borderWidth:     2,
                    }],
                },
                options: {
                    responsive:          true,
                    maintainAspectRatio: false,
                    cutout:              '50%',
                    plugins: {
                        legend: { position: 'right', labels: { font: { size: 10 }, boxWidth: 12 } },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const f = data.family_mix[ctx.dataIndex];
                                    return ` ${f.name}: ${f.pct}%`;
                                },
                            },
                        },
                    },
                },
            });
        }

        // ── Línea: % entrega mensual ─────────────────────────────────────────
        const lineEl = this.lineRef.el;
        const withDelivery = (data.monthly_data || []).filter(m => m.delivery_pct !== null);
        if (lineEl && withDelivery.length > 1) {
            if (this._lineChart) { this._lineChart.destroy(); this._lineChart = null; }
            this._lineChart = new Chart(lineEl, {
                type: 'line',
                data: {
                    labels:   withDelivery.map(m => monthLabel(m.month)),
                    datasets: [{
                        label:           '% Entrega',
                        data:            withDelivery.map(m => m.delivery_pct),
                        borderColor:     CHART_COLORS.line,
                        backgroundColor: 'rgba(25,135,84,0.10)',
                        fill:            true,
                        tension:         0.3,
                        pointRadius:     4,
                        pointHoverRadius: 6,
                    }],
                },
                options: {
                    responsive:          true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: { label: ctx => ` ${ctx.parsed.y}%` },
                        },
                    },
                    scales: {
                        x: { ticks: { font: { size: 10 } } },
                        y: {
                            min: 0, max: 100,
                            ticks: { callback: v => v + '%', font: { size: 10 } },
                        },
                    },
                },
            });
        }
    }

    // ── Exportar Excel ───────────────────────────────────────────────────────

    exportToExcel() {
        const cols = this.staticVisibleCols;
        const rows = this._filteredRows || this.state.allRows;

        const cellVal = (row, key) => {
            const v = row[key];
            if (v === null || v === undefined) return '';
            if (['delivery_pct', 'ontime_pct', 'trend_pct'].includes(key))
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
        const map = { A: 'text-bg-success', B: 'text-bg-primary', C: 'text-bg-secondary' };
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

    colTitle(col) {
        const titles = {
            partner_name:      'Nombre del cliente. Clic para ordenar.',
            customer_category: 'Categoría de cliente (A–E) calculada globalmente por el módulo según el método configurado en Ajustes.',
            abc_segment:       'Clasifica a los clientes del período según cuánto compraron en esa ventana de tiempo. No altera la categoría permanente del contacto. Los umbrales se configuran en Ajustes.',
            salesperson:       'Vendedor más frecuente en los pedidos del período.',
            country:           'País del cliente. Clic para ordenar.',
            province:          'Provincia del cliente. Clic para ordenar.',
            order_count:       'Cantidad de pedidos de venta confirmados en el período.',
            total_amount:      'Monto total neto (sin impuestos) de pedidos confirmados en el período.',
            avg_ticket:        'Monto total ÷ cantidad de pedidos del período.',
            delivery_pct:      'Cantidad entregada ÷ cantidad pedida × 100, acumulado de todas las líneas del período. Semáforo configurable en Ajustes.',
            ontime_pct:        'Porcentaje de entregas realizadas dentro del plazo acordado. El plazo se define según el método configurado en Ajustes (fecha compromiso, fecha programada o SLA en días).',
            avg_days_between:  'Promedio de días entre pedidos consecutivos del cliente en el período.',
            days_since_last:   'Días desde el último pedido hasta hoy. Se resalta en rojo si supera el umbral de riesgo configurado en Ajustes.',
            last_order_date:   'Fecha del último pedido de venta confirmado.',
            distinct_products: 'Cantidad de productos distintos (variantes) comprados en el período.',
            top_product:       'Plantilla de producto con mayor monto en el período.',
            top_family:        'Familia de producto (categ_id) con mayor monto en el período.',
            trend_pct:         'Variación del monto vs el período anterior de igual duración. ▲ crecimiento, ▼ caída.',
            frequency_segment: 'Segmento de frecuencia: Frecuente (< 30 días entre pedidos), Ocasional (30–90 días), Inactivo (> 90 días), En riesgo (sin comprar hace más días que el umbral configurado).',
        };
        return titles[col.key] || '';
    }

    get groupByDefs() {
        const base = [
            { key: 'salesperson',       label: 'Vendedor'             },
            { key: 'country',           label: 'País'                 },
            { key: 'province',          label: 'Provincia'            },
            { key: 'abc_segment',       label: 'Segmento ABC período' },
            { key: 'frequency_segment', label: 'Segmento frecuencia'  },
            { key: 'top_family',        label: 'Familia principal'    },
        ];
        if (this.state.config.show_category) {
            base.unshift({ key: 'customer_category', label: 'Categoría de cliente' });
        }
        return base;
    }
}

registry.category("view_widgets").add("customer_analysis_widget", { component: CustomerAnalysisWidget });
