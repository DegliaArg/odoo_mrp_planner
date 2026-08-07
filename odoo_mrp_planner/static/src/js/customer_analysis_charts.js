/** @odoo-module **/

/**
 * Funciones de renderizado de gráficos para el widget de análisis de clientes.
 * Reciben el widget como parámetro para poder mutar las referencias a instancias
 * de Chart y leer el estado reactivo sin acoplar esta lógica al componente OWL.
 */

const MONTHS_ES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function monthLabel(ym) {
    const [y, mStr] = ym.split('-');
    return `${MONTHS_ES[parseInt(mStr) - 1]} ${y}`;
}

// Paleta de colores del panel lateral — exportada para que el widget pueda usar donutColor()
export const CHART_COLORS = {
    bar:   'rgba(13, 110, 253, 0.75)',
    line:  'rgba(25, 135, 84, 0.85)',
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
    if (widget._barChart)     { widget._barChart.destroy();     widget._barChart     = null; }
    if (widget._donutChart)   { widget._donutChart.destroy();   widget._donutChart   = null; }
    if (widget._lineChart)    { widget._lineChart.destroy();    widget._lineChart    = null; }
    if (widget._saleCatChart) { widget._saleCatChart.destroy(); widget._saleCatChart = null; }
    widget._panelDonutsKey = '';
    widget._panelChartKey  = '';
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
    if (widget._saleCatChart)  { widget._saleCatChart.destroy();  widget._saleCatChart  = null; }
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
    const allFiltered = widget.chartSourceRows;
    if (!allFiltered.length) return;

    const key = `${widget.state.chartDateFrom}_${widget.state.chartDateTo}_${allFiltered.length}_${metric}_${topN}_${widget.state.filterCategory}_${widget.state.filterABC}_${widget.state.filterFreq}`;
    if (key === widget._topChartKey) return;
    widget._topChartKey = key;

    const ChartJs = globalThis.Chart;
    if (typeof ChartJs === 'undefined') return;
    if (widget._topChart) { widget._topChart.destroy(); widget._topChart = null; }

    const fieldMap = { pxq: 'total_amount', pedidos: 'order_count', ticket: 'avg_price' };
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
                label:           metric === 'pxq' ? 'Importe' : metric === 'pedidos' ? 'Pedidos' : 'P. prom.',
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
    const rows = widget.chartSourceRows;
    if (!rows.length) return;

    const donutType = widget.state.chartDonut;
    const key = `${widget.state.chartDateFrom}_${widget.state.chartDateTo}_${rows.length}_${donutType}_${widget.state.filterCategory}_${widget.state.filterABC}_${widget.state.filterFreq}`;
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

/**
 * Dibuja los gráficos del panel lateral de detalle de cliente:
 * barras agrupadas (pedido vs entregado por mes), donut de mix de familias,
 * y línea de evolución mensual.
 * @param {Object} widget - Instancia del CustomerAnalysisWidget
 */
export function drawPanelCharts(widget) {
    const data = widget.state.panelData;
    if (!data) return;
    const Chart = globalThis.Chart;
    if (typeof Chart === 'undefined') return;

    const chartMode  = widget.state.panelChartMode || 'bar';
    const baseKey    = `${widget.state.panelPartnerId}_${widget.state.panelMetric}_${widget.state.dateFrom}_${widget.state.dateTo}`;
    const donutsKey  = baseKey;
    const chartKey   = `${baseKey}_${chartMode}`;
    const skipDonuts = widget._panelDonutsKey === donutsKey;
    const skipChart  = widget._panelChartKey  === chartKey;
    if (skipDonuts && skipChart) return;
    widget._panelDonutsKey = donutsKey;
    widget._panelChartKey  = chartKey;

    const isQty   = widget.state.panelMetric === 'qty';
    const fmtTick = isQty
        ? v => (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)))
        : v => widget.fmtK(v);
    const fmtLbl  = isQty
        ? v => (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(Math.round(v)))
        : v => widget.fmtK(v);

    // Plugin compartido para etiquetas encima de barras
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
                    ctx.fillStyle    = '#555';
                    ctx.font         = 'bold 9px sans-serif';
                    ctx.textAlign    = 'center';
                    ctx.textBaseline = 'bottom';
                    ctx.fillText(label, bar.x, bar.y - 2);
                    ctx.restore();
                });
            });
        },
    };

    // Plugin compartido para % encima de sectores de donut
    const pieLabelPlugin = {
        id: 'panelPieLabels',
        afterDatasetsDraw(chart) {
            const { ctx, data: cData } = chart;
            const ds  = cData.datasets[0];
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

    // ── Donuts (solo si cambió métrica/partner/fechas) ───────────────────────
    if (skipDonuts) { /* donuts ya dibujados, solo redibujar gráfico abajo */ }
    // ── Donut: mix por categoría de venta ────────────────────────────────────
    const saleCatEl = !skipDonuts ? widget.saleCatRef.el : null;
    if (saleCatEl && data.sale_category_mix && data.sale_category_mix.length) {
        if (widget._saleCatChart) { widget._saleCatChart.destroy(); widget._saleCatChart = null; }
        const scm = data.sale_category_mix;
        widget._saleCatChart = new Chart(saleCatEl, {
            type: 'doughnut',
            data: {
                labels:   scm.map(s => s.name),
                datasets: [{
                    data:            scm.map(s => isQty ? s.qty : s.amount),
                    backgroundColor: scm.map(s => CAT_COLORS[s.name] ?? CAT_COLORS['']),
                    borderWidth:     2,
                    borderColor:     '#fff',
                }],
            },
            plugins: [pieLabelPlugin],
            options: {
                responsive:          true,
                maintainAspectRatio: false,
                cutout:              '50%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => scm[items[0].dataIndex].name,
                            label: ctx => {
                                const s = scm[ctx.dataIndex];
                                const skuLine = `  ${s.sku_count} SKU${s.sku_count !== 1 ? 's' : ''}`;
                                return isQty
                                    ? [`  ${s.pct}%`, `  ${new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(s.qty)} u.`, skuLine]
                                    : [`  ${s.pct_amount}%`, `  ${widget.fmtMoney(s.amount)}`, skuLine];
                            },
                        },
                    },
                },
            },
        });
    }

    // ── Donut: mix de familias ───────────────────────────────────────────────
    const donutEl = !skipDonuts ? widget.donutRef.el : null;
    if (donutEl && data.family_mix && data.family_mix.length) {
        if (widget._donutChart) { widget._donutChart.destroy(); widget._donutChart = null; }
        widget._donutChart = new Chart(donutEl, {
            type: 'doughnut',
            data: {
                labels:   data.family_mix.map(f => f.name),
                datasets: [{
                    data:            data.family_mix.map(f => isQty ? f.qty : f.amount),
                    backgroundColor: CHART_COLORS.donut,
                    borderWidth:     2,
                    borderColor:     '#fff',
                }],
            },
            plugins: [pieLabelPlugin],
            options: {
                responsive:          true,
                maintainAspectRatio: false,
                cutout:              '50%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => data.family_mix[items[0].dataIndex].name,
                            label: ctx => {
                                const f = data.family_mix[ctx.dataIndex];
                                return isQty
                                    ? [`  ${f.pct}%`, `  ${new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(f.qty)} u.`]
                                    : [`  ${f.pct_amount}%`, `  ${widget.fmtMoney(f.amount)}`];
                            },
                        },
                    },
                },
            },
        });
    }

    // ── Gráfico unificado (solo si cambió chartMode, métrica o datos) ────────
    const barEl     = !skipChart ? widget.barRef.el : null;
    const allMonths = data.monthly_data || [];
    if (barEl && allMonths.length) {
        if (widget._barChart)  { widget._barChart.destroy();  widget._barChart  = null; }
        if (widget._lineChart) { widget._lineChart.destroy(); widget._lineChart = null; }

        const labels = allMonths.map(m => monthLabel(m.month));

        // Desglose "por mes de confirmación del pedido" para el tooltip del dataset
        // Despachado (tasa física): indica de qué mes son los pedidos entregados.
        const physAfterLabel = ctx => {
            if (!ctx.dataset.label || !ctx.dataset.label.startsWith('Despachado')) return '';
            const bm = (allMonths[ctx.dataIndex] || {}).phys_by_order_month || {};
            const keys = Object.keys(bm).sort();
            if (!keys.length) return '';
            return ['Por mes del pedido:'].concat(keys.map(ym => {
                const [y, m] = ym.split('-');
                const lbl = new Date(+y, +m - 1, 1).toLocaleString('es', { month: 'short', year: '2-digit' });
                return `  ${lbl}: ${fmtLbl(bm[ym])}`;
            }));
        };

        if (chartMode === 'bar') {
            widget._barChart = new Chart(barEl, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        {
                            label:           isQty ? 'Pedido (u)' : 'Pedido ($)',
                            data:            allMonths.map(m => isQty ? m.qty_ordered   : m.amount),
                            backgroundColor: 'rgba(13,110,253,0.75)',
                            borderRadius:    3,
                            _fmt:            fmtLbl,
                        },
                        {
                            label:           isQty ? 'Entregado (u)' : 'Entregado ($)',
                            data:            allMonths.map(m => isQty ? m.qty_delivered : m.amount_delivered),
                            backgroundColor: 'rgba(25,135,84,0.70)',
                            borderRadius:    3,
                            _fmt:            fmtLbl,
                        },
                        // Tasa física: solo en modo unidades (no hay importe físico)
                        ...(isQty ? [{
                            label:           'Despachado (u)',
                            data:            allMonths.map(m => m.qty_delivered_phys || 0),
                            backgroundColor: 'rgba(253,126,20,0.70)',
                            borderRadius:    3,
                            _fmt:            fmtLbl,
                        }] : []),
                    ],
                },
                options: {
                    responsive:          true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend:   { display: true, labels: { font: { size: 11 }, boxWidth: 12 } },
                        barLabel: {},
                        tooltip:  { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${fmtLbl(ctx.parsed.y)}`, afterLabel: physAfterLabel } },
                    },
                    scales: {
                        x: { ticks: { font: { size: 10 } } },
                        y: { beginAtZero: true, ticks: { callback: fmtTick, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
                    },
                },
                plugins: [barLabelPlugin],
            });
        } else {
            widget._barChart = new Chart(barEl, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label:            isQty ? 'Pedido (u)' : 'Pedido ($)',
                            data:             allMonths.map(m => isQty ? m.qty_ordered   : m.amount),
                            borderColor:      'rgba(13,110,253,0.85)',
                            backgroundColor:  'rgba(13,110,253,0.10)',
                            fill:             true,
                            tension:          0.3,
                            pointRadius:      3,
                            pointHoverRadius: 5,
                        },
                        {
                            label:            isQty ? 'Entregado (u)' : 'Entregado ($)',
                            data:             allMonths.map(m => isQty ? m.qty_delivered : m.amount_delivered),
                            borderColor:      CHART_COLORS.line,
                            backgroundColor:  'transparent',
                            fill:             false,
                            tension:          0.3,
                            pointRadius:      3,
                            pointHoverRadius: 5,
                        },
                        // Tasa física: solo en modo unidades (no hay importe físico)
                        ...(isQty ? [{
                            label:            'Despachado (u)',
                            data:             allMonths.map(m => m.qty_delivered_phys || 0),
                            borderColor:      'rgba(253,126,20,0.85)',
                            backgroundColor:  'transparent',
                            fill:             false,
                            tension:          0.3,
                            pointRadius:      3,
                            pointHoverRadius: 5,
                        }] : []),
                    ],
                },
                options: {
                    responsive:          true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend:  { display: true, labels: { font: { size: 10 }, boxWidth: 12 } },
                        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${fmtLbl(ctx.parsed.y)}`, afterLabel: physAfterLabel } },
                    },
                    scales: {
                        x: { ticks: { font: { size: 10 } } },
                        y: { beginAtZero: true, ticks: { callback: fmtTick, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
                    },
                },
            });
        }
    }
}
