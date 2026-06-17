/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class WcLoadChartWidget extends Component {
    static template = "odoo_mrp_reschedule.WcLoadChartWidget";

    setup() {
        this.orm = useService("orm");
        this.canvasRef = useRef("chartCanvas");
        this.chart = null;

        const now = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tags: [],
            selectedTag: "",
            dateFrom: toDateStr(firstOfMonth),
            dateTo:   toDateStr(lastOfMonth),
            loading: false,
            empty: false,
        });

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

    async _loadTags() {
        const tags = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
        this.state.tags = tags;
    }

    async _loadChart() {
        if (!this.state.dateFrom || !this.state.dateTo) return;
        this.state.loading = true;
        this.state.empty   = false;
        let chartData = null;
        try {
            chartData = await this.orm.call(
                "mrp.planner.dashboard",
                "get_wc_chart_data",
                [
                    this.state.dateFrom,
                    this.state.dateTo,
                    this.state.selectedTag ? parseInt(this.state.selectedTag) : null,
                ],
            );
            this.state.empty = !chartData.labels.length;
        } catch (e) {
            console.error("[WcLoadChart] Error al obtener datos:", e);
            this.state.empty = true;
        } finally {
            this.state.loading = false;
        }
        // Canvas siempre está en el DOM — no hace falta esperar tick de OWL
        if (chartData && !this.state.empty) {
            this._renderChart(chartData);
        } else if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _renderChart(data) {
        const canvas = this.canvasRef.el;
        if (!canvas) {
            console.warn("[WcLoadChart] Canvas no disponible");
            return;
        }
        if (!window.Chart) {
            console.error("[WcLoadChart] Chart.js no está cargado (window.Chart undefined)");
            return;
        }

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
                                return [
                                    `  Carga: ${ctx.raw}%`,
                                    `  Pendiente: ${data.pending_hours[i]}h`,
                                    `  Disponible: ${data.available_hours[i]}h`,
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

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        this._loadChart();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this._loadChart();
    }

    onTagChange(ev) {
        this.state.selectedTag = ev.target.value;
        this._loadChart();
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChartWidget,
});
