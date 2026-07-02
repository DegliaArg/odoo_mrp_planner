/** @odoo-module **/

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry }  from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const CAT_COLORS = {
    A: "rgba(25, 135, 84, 0.80)",
    B: "rgba(13, 110, 253, 0.80)",
    C: "rgba(255, 193, 7, 0.85)",
    D: "rgba(108, 117, 125, 0.80)",
    E: "rgba(200, 210, 220, 0.90)",
    "": "rgba(108, 117, 125, 0.65)",
};

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class SalesChartWidget extends Component {
    static template = "odoo_mrp_planner.SalesChartWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm      = useService("orm");
        this.chartRef = useRef("salesCanvas");
        this.pieRef   = useRef("pieCanvas");
        this._chart   = null;
        this._pie     = null;

        this.state = useState({
            loading:         true,
            period:          "3m",
            metric:          "qty",
            topN:            20,
            saleCategory:    "",
            productCategId:  "",
            productCategs:   [],
            rows:            [],
            docType:         "sales",
        });

        onMounted(async () => {
            // Paralelizar: get_product_categories_for_chart y _load() son RPCs independientes
            const [cats] = await Promise.all([
                this.orm.call("mrp.planner.dashboard", "get_product_categories_for_chart", []),
                this._load(),
            ]);
            this.state.productCategs = cats || [];
        });

        onPatched(() => {
            if (!this.state.loading && this.state.rows.length) {
                if (this.chartRef.el) this._drawChart();
                if (this.pieRef.el)   this._drawPie();
            }
        });

        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
            if (this._pie)   { this._pie.destroy();   this._pie   = null; }
        });
    }

    _dateRange() {
        const to   = new Date();
        const from = new Date(to);
        const m    = { "1m": 1, "3m": 3, "6m": 6, "12m": 12 }[this.state.period] || 3;
        from.setMonth(from.getMonth() - m);
        return [toDateStr(from), toDateStr(to)];
    }

    async _load() {
        this.state.loading = true;
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        if (this._pie)   { this._pie.destroy();   this._pie   = null; }
        try {
            const [df, dt] = this._dateRange();
            const rows = await this.orm.call(
                "mrp.planner.dashboard",
                "get_sales_chart_data",
                [df, dt, this.state.topN, this.state.saleCategory || null, this.state.productCategId || null, this.state.metric, this.state.docType],
            );
            this.state.rows = rows || [];
        } catch (e) {
            console.error("[SalesChartWidget]", e);
            this.state.rows = [];
        } finally {
            this.state.loading = false;
        }
    }

    _drawChart() {
        const canvas = this.chartRef.el;
        if (!canvas) return;

        const ChartJs = globalThis.Chart;
        if (typeof ChartJs === "undefined") {
            console.warn("[SalesChartWidget] Chart.js no disponible");
            return;
        }

        if (this._chart) { this._chart.destroy(); this._chart = null; }

        const isQty  = this.state.metric === "qty";
        const rows   = [...this.state.rows].sort((a, b) => isQty ? b.qty - a.qty : b.amount - a.amount);
        const labels = rows.map(r => r.code || r.name);
        const data   = rows.map(r => isQty ? r.qty : r.amount);
        const colors = rows.map(r => CAT_COLORS[r.sale_category] ?? CAT_COLORS[""]);

        const fmt = isQty
            ? v => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v) + " u."
            : v => "$ " + new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);

        this._chart = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: isQty ? "Unidades vendidas" : "Importe",
                    data,
                    backgroundColor: colors,
                    borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => {
                                const r = rows[items[0].dataIndex];
                                return r.code ? `${r.code} — ${r.name}` : r.name;
                            },
                            label: ctx => fmt(ctx.raw),
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 }, maxRotation: 45 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.06)" },
                        ticks: { font: { size: 11 } },
                    },
                },
            },
        });
    }

    _drawPie() {
        const canvas = this.pieRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._pie) { this._pie.destroy(); this._pie = null; }

        const ORDER  = ['A', 'B', 'C', 'D', 'E', ''];
        const NAMES  = { A: 'Cat. A', B: 'Cat. B', C: 'Cat. C', D: 'Cat. D', E: 'Cat. E', '': 'Sin cat.' };
        const bycat  = {};
        for (const r of this.state.rows) {
            const c = r.sale_category || '';
            if (!bycat[c]) bycat[c] = { skus: 0, qty: 0, amount: 0 };
            bycat[c].skus++;
            bycat[c].qty    += r.qty    || 0;
            bycat[c].amount += r.amount || 0;
        }

        const cats   = ORDER.filter(c => bycat[c]);
        const total  = cats.reduce((s, c) => s + bycat[c].skus, 0);
        const fmtN   = v => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(v);
        const fmtAmt = v => '$ ' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v);

        const pieLabelPlugin = {
            id: 'pieLabels',
            afterDatasetsDraw(chart) {
                const { ctx, data } = chart;
                const dataset = data.datasets[0];
                const ttl = dataset.data.reduce((a, b) => a + b, 0);
                chart.getDatasetMeta(0).data.forEach((arc, i) => {
                    const pct = ttl ? Math.round(dataset.data[i] / ttl * 100) : 0;
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

        this._pie = new ChartJs(canvas, {
            type: 'doughnut',
            data: {
                labels: cats.map(c => NAMES[c]),
                datasets: [{
                    data:            cats.map(c => bycat[c].skus),
                    backgroundColor: cats.map(c => CAT_COLORS[c] ?? CAT_COLORS['']),
                    borderWidth: 1,
                    borderColor: '#fff',
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
                            title: items => NAMES[cats[items[0].dataIndex]],
                            label: ctx => {
                                const d   = bycat[cats[ctx.dataIndex]];
                                const pct = total ? Math.round(d.skus / total * 100) : 0;
                                return [
                                    `  ${d.skus} SKU (${pct}%)`,
                                    `  Qty total: ${fmtN(d.qty)} u.`,
                                    `  Importe: ${fmtAmt(d.amount)}`,
                                ];
                            },
                        },
                    },
                },
            },
        });
    }

    setPeriod(p)   { if (this.state.period !== p)          { this.state.period = p;          this._load(); } }
    setMetric(m)   { if (this.state.metric !== m)          { this.state.metric = m;          this._load(); } }
    setTopN(n)     { if (this.state.topN !== n)            { this.state.topN = n;            this._load(); } }
    setSaleCat(c)  { if (this.state.saleCategory !== c)    { this.state.saleCategory = c;    this._load(); } }
    setDocType(d)  { if (this.state.docType !== d)         { this.state.docType = d;         this._load(); } }
    setProductCat(ev) {
        const v = ev.target.value;
        if (this.state.productCategId !== v) { this.state.productCategId = v; this._load(); }
    }
}

registry.category("view_widgets").add("sales_chart_widget", {
    component: SalesChartWidget,
});
