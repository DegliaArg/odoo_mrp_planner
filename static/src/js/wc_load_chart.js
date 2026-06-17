/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

const MONTHS = [
    "Enero","Febrero","Marzo","Abril","Mayo","Junio",
    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre",
];

class WcLoadChartWidget extends Component {
    static template = "odoo_mrp_reschedule.WcLoadChartWidget";

    setup() {
        this.orm = useService("orm");
        this.canvasRef = useRef("chartCanvas");
        this.chart = null;

        const now = new Date();
        this.state = useState({
            tags: [],
            selectedTag: "",
            year: now.getFullYear(),
            month: now.getMonth() + 1,
            loading: false,
            empty: false,
        });

        // Build list of selectable months (current month ± 12)
        this.monthOptions = [];
        for (let delta = -6; delta <= 6; delta++) {
            let d = new Date(now.getFullYear(), now.getMonth() + delta, 1);
            this.monthOptions.push({
                value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
                label: `${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
            });
        }

        onMounted(async () => {
            await loadBundle("web.chartjs_lib");
            await this._loadTags();
            await this._loadChart();
        });

        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }
        });
    }

    get monthValue() {
        return `${this.state.year}-${String(this.state.month).padStart(2, "0")}`;
    }

    async _loadTags() {
        const tags = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
        this.state.tags = tags;
    }

    async _loadChart() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "mrp.planner.dashboard",
                "get_wc_chart_data",
                [this.state.year, this.state.month, this.state.selectedTag ? parseInt(this.state.selectedTag) : null],
            );
            this.state.empty = data.labels.length === 0;
            if (!this.state.empty) {
                this._renderChart(data);
            } else if (this.chart) {
                this.chart.destroy();
                this.chart = null;
            }
        } finally {
            this.state.loading = false;
        }
    }

    _renderChart(data) {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        if (this.chart) {
            this.chart.destroy();
        }

        const percentages = data.labels.map((_, i) => {
            const avail = data.available_hours[i];
            if (!avail) return 0;
            return Math.round((data.pending_hours[i] / avail) * 100);
        });

        const bgColors = percentages.map(p =>
            p > 90 ? "rgba(220,53,69,0.75)" :
            p > 70 ? "rgba(255,193,7,0.80)" :
            "rgba(25,135,84,0.70)"
        );
        const borderColors = bgColors.map(c => c.replace(/[\d.]+\)$/, "1)"));

        this.chart = new window.Chart(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [{
                    label: "Carga (%)",
                    data: percentages,
                    backgroundColor: bgColors,
                    borderColor: borderColors,
                    borderWidth: 1,
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (items) => items[0].label,
                            label: (ctx) => {
                                const i = ctx.dataIndex;
                                const pending = data.pending_hours[i];
                                const avail   = data.available_hours[i];
                                return [
                                    `  Carga: ${ctx.raw}%`,
                                    `  Pendiente: ${pending}h`,
                                    `  Disponible: ${avail}h`,
                                ];
                            },
                        },
                        padding: 10,
                        boxPadding: 4,
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxRotation: 45 },
                    },
                    y: {
                        beginAtZero: true,
                        suggestedMax: 100,
                        ticks: {
                            stepSize: 20,
                            callback: v => v + "%",
                        },
                        title: {
                            display: true,
                            text: "% de capacidad utilizada",
                            font: { size: 11 },
                        },
                    },
                },
            },
        });
    }

    onTagChange(ev) {
        this.state.selectedTag = ev.target.value;
        this._loadChart();
    }

    onMonthChange(ev) {
        const [year, month] = ev.target.value.split("-");
        this.state.year  = parseInt(year);
        this.state.month = parseInt(month);
        this._loadChart();
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChartWidget,
});
