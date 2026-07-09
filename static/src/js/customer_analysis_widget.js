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

// ── Columnas estáticas (producto del menú de columnas) ────────────────────────
const CA_STATIC_COLS = [
    { key: 'partner_name',      label: 'Cliente',          width: 200, fixed: true,  align: 'start'  },
    { key: 'customer_category', label: 'Cat.',              width:  55, align: 'center' },
    { key: 'abc_segment',       label: 'ABC',               width:  55, align: 'center' },
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

function defaultPeriod(cfg) {
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth();
    if ((cfg && cfg.default_period) === 'month') {
        return {
            from: toDateStr(new Date(y, m, 1)),
            to:   toDateStr(new Date(y, m + 1, 0)),
        };
    }
    if ((cfg && cfg.default_period) === 'year') {
        return {
            from: toDateStr(new Date(y, 0, 1)),
            to:   toDateStr(new Date(y, 11, 31)),
        };
    }
    // quarter (default)
    const q = Math.floor(m / 3);
    return {
        from: toDateStr(new Date(y, q * 3, 1)),
        to:   toDateStr(new Date(y, q * 3 + 3, 0)),
    };
}

function monthLabel(ym) {
    const [y, mStr] = ym.split('-');
    return `${MONTHS_ES[parseInt(mStr) - 1]} ${y}`;
}

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

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        // Chart refs para el panel lateral
        this.barRef    = useRef("panelBarCanvas");
        this.donutRef  = useRef("panelDonutCanvas");
        this.lineRef   = useRef("panelLineCanvas");
        this._barChart   = null;
        this._donutChart = null;
        this._lineChart  = null;

        this.cols     = useColManager('customer_analysis', CA_STATIC_COLS);
        this.caSortKeys = CA_SORT_KEYS;

        const period = defaultPeriod(null);
        this.state = useState({
            loading:      true,
            dateFrom:     period.from,
            dateTo:       period.to,
            warehouseId:  null,
            warehouses:   [],
            allRows:      [],
            rows:         [],
            kpis:         { total_customers: 0, avg_ticket: 0, avg_delivery_pct: null, avg_ontime_pct: null, avg_days_between: null },
            config:       {},
            sortCol:      'total_amount',
            sortDir:      'desc',
            page:         1,
            pageSize:     50,
            totalFiltered: 0,
            search:       '',
            groupBy:      null,
            colsDropdownOpen:  false,
            groupDropdownOpen: false,
            // Panel lateral
            panelOpen:    false,
            panelLoading: false,
            panelData:    null,
            panelPartnerId: null,
            // Columnas visibles
            visibleCols: {
                customer_category: true,
                abc_segment:       true,
                salesperson:       false,
                country:           false,
                province:          false,
                order_count:       true,
                total_amount:      true,
                avg_ticket:        true,
                delivery_pct:      true,
                ontime_pct:        true,
                avg_days_between:  true,
                days_since_last:   true,
                last_order_date:   false,
                distinct_products: false,
                top_product:       false,
                top_family:        true,
                trend_pct:         true,
                frequency_segment: true,
            },
        });

        this._closeDropdowns = () => {
            this.state.colsDropdownOpen  = false;
            this.state.groupDropdownOpen = false;
        };

        onMounted(async () => {
            document.addEventListener('click', this._closeDropdowns);
            await this._loadWarehouses();
            await this._load();
        });

        onPatched(() => {
            if (this.state.panelOpen && this.state.panelData && !this.state.panelLoading) {
                this._drawPanelCharts();
            }
        });

        onWillUnmount(() => {
            document.removeEventListener('click', this._closeDropdowns);
            this._destroyCharts();
        });
    }

    // ── Carga de datos ────────────────────────────────────────────────────────

    async _loadWarehouses() {
        try {
            const whs = await this.orm.searchRead(
                'stock.warehouse', [], ['id', 'name'], { order: 'name asc' }
            );
            this.state.warehouses = whs;
        } catch (e) {
            console.error('[CustomerAnalysis] warehouses', e);
        }
    }

    async _load() {
        this.state.loading = true;
        try {
            const whIds = this.state.warehouseId ? [this.state.warehouseId] : null;
            const res = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_analysis_data',
                [this.state.dateFrom, this.state.dateTo, whIds]
            );
            this.state.allRows = res.rows || [];
            this.state.kpis    = res.kpis  || {};
            this.state.config  = res.config || {};
            // Ocultar columna categoría si está deshabilitada en config
            if (!res.config.show_category) {
                this.state.visibleCols.customer_category = false;
            }
            this._applySort();
        } catch (e) {
            console.error('[CustomerAnalysis]', e);
        } finally {
            this.state.loading = false;
        }
    }

    _applySort() {
        let rows = [...this.state.allRows];
        // Búsqueda de texto
        const q = this.state.search.trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                (r.partner_name   || '').toLowerCase().includes(q) ||
                (r.top_product    || '').toLowerCase().includes(q) ||
                (r.top_family     || '').toLowerCase().includes(q) ||
                (r.salesperson    || '').toLowerCase().includes(q)
            );
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

    setGroupBy(gb) {
        this.state.groupBy = this.state.groupBy === gb ? null : gb;
        this.state.page = 1;
        this._applySort();
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

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.state.page   = 1;
        this._applySort();
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

    get groupedRows() {
        return this._groupedRows || [];
    }

    // ── Panel lateral ─────────────────────────────────────────────────────────

    async openPanel(partnerId) {
        this.state.panelOpen      = true;
        this.state.panelPartnerId = partnerId;
        this.state.panelData      = null;
        this.state.panelLoading   = true;
        this._destroyCharts();
        try {
            const whIds = this.state.warehouseId ? [this.state.warehouseId] : null;
            const data  = await this.orm.call(
                'mrp.planner.dashboard',
                'get_customer_detail',
                [partnerId, this.state.dateFrom, this.state.dateTo, whIds]
            );
            this.state.panelData = data;
        } catch (e) {
            console.error('[CustomerAnalysis panel]', e);
        } finally {
            this.state.panelLoading = false;
        }
    }

    closePanel() {
        this.state.panelOpen = false;
        this._destroyCharts();
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
        if (this._barChart)   { this._barChart.destroy();   this._barChart   = null; }
        if (this._donutChart) { this._donutChart.destroy(); this._donutChart = null; }
        if (this._lineChart)  { this._lineChart.destroy();  this._lineChart  = null; }
    }

    _drawPanelCharts() {
        const data = this.state.panelData;
        if (!data) return;
        const Chart = window.Chart;
        if (!Chart) return;

        // ── Barras: evolución mensual de monto ───────────────────────────────
        const barEl = this.barRef.el;
        if (barEl && data.monthly_data && data.monthly_data.length) {
            if (this._barChart) { this._barChart.destroy(); this._barChart = null; }
            this._barChart = new Chart(barEl, {
                type: 'bar',
                data: {
                    labels:   data.monthly_data.map(m => monthLabel(m.month)),
                    datasets: [{
                        label:           'Monto',
                        data:            data.monthly_data.map(m => m.amount),
                        backgroundColor: CHART_COLORS.bar,
                        borderRadius:    4,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { ticks: { callback: v => this.fmtK(v) } },
                    },
                },
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
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'right', labels: { font: { size: 11 } } },
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
        if (lineEl && withDelivery.length) {
            if (this._lineChart) { this._lineChart.destroy(); this._lineChart = null; }
            this._lineChart = new Chart(lineEl, {
                type: 'line',
                data: {
                    labels:   withDelivery.map(m => monthLabel(m.month)),
                    datasets: [{
                        label:       '% Entrega',
                        data:        withDelivery.map(m => m.delivery_pct),
                        borderColor: CHART_COLORS.line,
                        backgroundColor: 'rgba(25, 135, 84, 0.10)',
                        fill:        true,
                        tension:     0.3,
                        pointRadius: 4,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { min: 0, max: 100, ticks: { callback: v => v + '%' } },
                    },
                },
            });
        }
    }

    // ── Formateo y semáforos ──────────────────────────────────────────────────

    fmt(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR').format(n);
    }

    fmtMoney(n) {
        if (n === null || n === undefined) return '—';
        return new Intl.NumberFormat('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n);
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

    abcClass(seg) {
        const map = { A: 'text-success fw-bold', B: 'text-primary fw-bold', C: 'text-muted' };
        return map[seg] || '';
    }

    freqClass(seg) {
        const map = { frecuente: 'text-success', ocasional: 'text-warning', inactivo: 'text-muted', en_riesgo: 'text-danger fw-semibold' };
        return map[seg] || '';
    }

    freqLabel(seg) {
        const map = { frecuente: 'Frecuente', ocasional: 'Ocasional', inactivo: 'Inactivo', en_riesgo: 'En riesgo' };
        return map[seg] || seg;
    }

    catLabel(cat) {
        const map = { A: 'A', B: 'B', C: 'C', D: 'D', E: 'E' };
        return map[cat] || cat || '—';
    }

    catClass(cat) {
        const map = { A: 'text-success fw-bold', B: 'text-primary', C: 'text-warning', D: 'text-secondary', E: 'text-muted' };
        return map[cat] || 'text-muted';
    }

    colTitle(col) {
        const titles = {
            partner_name:      'Nombre del cliente. Clic para ordenar.',
            customer_category: 'Categoría de cliente (A–E) calculada globalmente por el módulo según el método configurado en Ajustes.',
            abc_segment:       'Segmento ABC calculado para el período seleccionado: A = top clientes por monto acumulado, B = siguiente segmento, C = resto. Los umbrales se configuran en Ajustes.',
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

    get groupByOptions() {
        const base = [
            { key: 'salesperson',       label: 'Vendedor'              },
            { key: 'country',           label: 'País'                  },
            { key: 'province',          label: 'Provincia'             },
            { key: 'abc_segment',       label: 'Segmento ABC período'  },
            { key: 'frequency_segment', label: 'Segmento frecuencia'   },
            { key: 'top_family',        label: 'Familia principal'     },
        ];
        if (this.state.config.show_category) {
            base.unshift({ key: 'customer_category', label: 'Categoría de cliente' });
        }
        return base;
    }

    get groupByLabel() {
        const opt = this.groupByOptions.find(o => o.key === this.state.groupBy);
        return opt ? opt.label : 'Agrupar por';
    }
}

registry.category("view_widgets").add("customer_analysis_widget", { component: CustomerAnalysisWidget });
