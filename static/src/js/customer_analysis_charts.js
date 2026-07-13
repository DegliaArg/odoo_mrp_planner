/** @odoo-module **/

/**
 * Funciones de renderizado de gráficos para el widget de análisis de clientes.
 * Reciben el widget como parámetro para poder mutar las referencias a instancias
 * de Chart y leer el estado reactivo sin acoplar esta lógica al componente OWL.
 */

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

/**
 * Destruye los gráficos del panel lateral (bar, donut, line).
 * @param {Object} widget - Instancia del CustomerAnalysisWidget
 */
export function destroyPanelCharts(widget) {
    if (widget._barChart)   { widget._barChart.destroy();   widget._barChart   = null; }
    if (widget._donutChart) { widget._donutChart.destroy(); widget._donutChart = null; }
    if (widget._lineChart)  { widget._lineChart.destroy();  widget._lineChart  = null; }
    widget._panelChartsKey = '';
}

/**
 * Destruye todos los gráficos del widget (superiores + panel lateral).
 * @param {Object} widget - Instancia del CustomerAnalysisWidget
 */
export function destroyCharts(widget) {
    if (widget._topChart)      { widget._topChart.destroy();      widget._topChart      = null; widget._topChartKey  = ''; }
    if (widget._topDonutChart) { widget._topDonutChart.destroy(); widget._topDonutChart = null; widget._topDonutKey  = ''; }
    if (widget._barChart)      { widget._barChart.destroy();      widget._barChart      = null; }
    if (widget._donutChart)    { widget._donutChart.destroy();    widget._donutChart    = null; }
    if (widget._lineChart)     { widget._lineChart.destroy();     widget._lineChart     = null; }
}

/**
 * Dibuja el gráfico de barras superior (top clientes por métrica).
 * @param {Object} widget - Instancia del CustomerAnalysisWidget
 */
export function drawTopChart(widget) {
    const el = widget.topChartRef.el;
    if (!el) return;
    const metric      = widget.state.chartMetric;
    const topN        = widget.state.chartTopN;   // null = todos
    const allFiltered = widget._filteredRows || widget.state.allRows;
    if (!allFiltered.length) return;

    const key = `${widget.state.dateFrom}_${widget.state.dateTo}_${allFiltered.length}_${metric}_${topN}_${widget.state.filterCategory}_${widget.state.filterABC}_${widget.state.filterFreq}`;
    if (key === widget._topChartKey) return;
    widget._topChartKey = key;

    const ChartJs = globalThis.Chart;
    if (typeof ChartJs === 'undefined') return;
    if (widget._topChart) { widget._topChart.destroy(); widget._topChart = null; }

    const fieldMap = { pxq: 'total_amount', pedidos: 'order_count', ticket: 'avg_ticket' };
    const field    = fieldMap[metric] || 'total_amount';
    const sorted   = [...allFiltered].sort((a, b) => (b[field] ?? 0) - (a[field] ?? 0));
    const rows     = topN !== null ? sorted.slice(0, topN) : sorted;
    const isAmt    = metric !== 'pedidos';
    const fmtTip   = isAmt
        ? v => '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v)
        : v => new Intl.NumberFormat('es-AR').format(v) + ' ped.';

    widget._topChart = new ChartJs(el, {
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
                    ticks: { callback: v => widget.fmtK(v), font: { size: 11 } },
                },
            },
        },
    });
}

/**
 * Dibuja el gráfico de donut superior (distribución por segmento/categoría/frecuencia).
 * @param {Object} widget - Instancia del CustomerAnalysisWidget
 */
export function drawTopDonut(widget) {
    const el = widget.topDonutRef.el;
    if (!el) return;
    const rows = widget._filteredRows || widget.state.allRows;
    if (!rows.length) return;

    const donutType = widget.state.chartDonut;
    const key = `${widget.state.dateFrom}_${widget.state.dateTo}_${rows.length}_${donutType}_${widget.state.filterCategory}_${widget.state.filterABC}_${widget.state.filterFreq}`;
    if (key === widget._topDonutKey) return;
    widget._topDonutKey = key;

    const ChartJs = globalThis.Chart;
    if (typeof ChartJs === 'undefined') return;
    if (widget._topDonutChart) { widget._topDonutChart.destroy(); widget._topDonutChart = null; }

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

    widget._topDonutChart = new ChartJs(el, {
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
