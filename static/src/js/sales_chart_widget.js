/** @odoo-module **/

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
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
        this._chart   = null;

        this.state = useState({
            loading:         true,
            period:          "3m",
            metric:          "qty",
            topN:            20,
            saleCategory:    "",
            productCategId:  "",
            productCategs:   [],
            rows:            [],
        });

        onMounted(async () => {
            const cats = await this.orm.call(
                "mrp.planner.dashboard", "get_product_categories_for_chart", []
            );
            this.state.productCategs = cats || [];
            await this._load();
        });

        onPatched(() => {
            if (!this.state.loading && this.state.rows.length && this.chartRef.el) {
                this._drawChart();
            }
        });

        onWillUnmount(() => {
            if (this._chart) { this._chart.destroy(); this._chart = null; }
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
        try {
            const [df, dt] = this._dateRange();
            const rows = await this.orm.call(
                "mrp.planner.dashboard",
                "get_sales_chart_data",
                [df, dt, this.state.topN, this.state.saleCategory || null, this.state.productCategId || null, this.state.metric],
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

    setPeriod(p)   { if (this.state.period !== p)          { this.state.period = p;          this._load(); } }
    setMetric(m)   { if (this.state.metric !== m)          { this.state.metric = m;          this._load(); } }
    setTopN(n)     { if (this.state.topN !== n)            { this.state.topN = n;            this._load(); } }
    setSaleCat(c)  { if (this.state.saleCategory !== c)    { this.state.saleCategory = c;    this._load(); } }
    setProductCat(ev) {
        const v = ev.target.value;
        if (this.state.productCategId !== v) { this.state.productCategId = v; this._load(); }
    }
}

registry.category("view_widgets").add("sales_chart_widget", {
    component: SalesChartWidget,
});
