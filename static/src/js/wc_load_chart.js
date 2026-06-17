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
        if (chartData && !this.state.empty) {
            this._renderChart(chartData);
        } else if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _renderChart(data) {
        const canvas = this.canvasRef.el;
        if (!canvas) { console.warn("[WcLoadChart] canvas no disponible"); return; }
        if (!window.Chart) { console.error("[WcLoadChart] window.Chart undefined"); return; }

        if (this.chart) this.chart.destroy();

        this.chart = new window.Chart(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Programado",
                        data: data.programado,
                        backgroundColor: "rgba(13,110,253,0.65)",
                        borderColor: "rgba(13,110,253,1)",
                        borderWidth: 1,
                        borderRadius: 3,
                        stack: "programado",
                    },
                    {
                        label: "Ejecutado",
                        data: data.ejecutado,
                        backgroundColor: "rgba(25,135,84,0.75)",
                        borderColor: "rgba(25,135,84,1)",
                        borderWidth: 1,
                        stack: "real",
                    },
                    {
                        label: "Pendiente",
                        data: data.pendiente,
                        backgroundColor: "rgba(255,193,7,0.85)",
                        borderColor: "rgba(200,150,0,1)",
                        borderWidth: 1,
                        stack: "real",
                    },
                    {
                        label: "Tiempo muerto",
                        data: data.tiempo_muerto,
                        backgroundColor: "rgba(190,190,190,0.40)",
                        borderColor: "rgba(150,150,150,0.60)",
                        borderWidth: 1,
                        stack: "real",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: "top",
                        labels: { boxWidth: 14, padding: 16, font: { size: 12 } },
                    },
                    tooltip: {
                        mode: "index",
                        intersect: false,
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                if (v === 0) return null;
                                return `  ${ctx.dataset.label}: ${v}h`;
                            },
                            footer: (items) => {
                                const i = items[0].dataIndex;
                                return `  Disponible: ${data.available_hours[i]}h`;
                            },
                        },
                        padding: 10,
                        boxPadding: 4,
                    },
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { display: false },
                        ticks: { maxRotation: 40 },
                    },
                    y: {
                        stacked: true,
                        title: {
                            display: true,
                            text: "Horas",
                            font: { size: 11 },
                        },
                        ticks: { stepSize: 8 },
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
