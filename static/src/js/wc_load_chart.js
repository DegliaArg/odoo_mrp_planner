/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

class WcLoadChartWidget extends Component {
    static template = "odoo_mrp_planner.WcLoadChartWidget";
    static props = { record: { type: Object, optional: true }, "*": true };

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
            kpis: { disponible: 0, planificado: 0, carga_pct: 0, ejecutado: 0, pendiente: 0, tiempo_libre: 0 },
        });

        onMounted(async () => {
            await loadBundle("web.chartjs_lib");
            // Paralelizar: get_wc_tags y get_wc_chart_data son RPCs independientes
            await Promise.all([this._loadTags(), this._loadChart()]);
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
            if (chartData.totals) this.state.kpis = chartData.totals;
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

        const ChartJs = globalThis.Chart || window.Chart;
        if (!ChartJs) { console.error("[WcLoadChart] Chart.js no disponible"); return; }

        if (this.chart) this.chart.destroy();

        const planificado   = data.ejecutado.map((e, i) => e + data.pendiente[i]);
        const tiempoLibre   = data.tiempo_muerto;
        const noplanificado = data.tiempo_muerto;

        this.chart = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Planificado",
                        data: planificado,
                        backgroundColor: "rgba(13,110,253,0.60)",
                        borderColor: "rgba(13,110,253,0.90)",
                        borderWidth: 1,
                        borderRadius: 2,
                        stack: "plan",
                    },
                    {
                        label: "No planificado",
                        data: noplanificado,
                        backgroundColor: "rgba(200,200,200,0.35)",
                        borderColor: "rgba(160,160,160,0.50)",
                        borderWidth: 1,
                        stack: "plan",
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
                        label: "Tiempo libre",
                        data: tiempoLibre,
                        backgroundColor: "rgba(255,153,153,0.50)",
                        borderColor: "rgba(220,80,80,0.70)",
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
                        labels: { boxWidth: 13, padding: 14, font: { size: 12 } },
                    },
                    tooltip: {
                        mode: "index",
                        intersect: false,
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                if (v === 0) return null;
                                return `  ${ctx.dataset.label}: ${typeof v === 'number' ? v.toFixed(2) : v}h`;
                            },
                            footer: (items) => {
                                const i     = items[0].dataIndex;
                                const avail = data.available_hours[i];
                                const used  = data.ejecutado[i] + data.pendiente[i];
                                const pct   = avail > 0 ? Math.round(used / avail * 100) : 0;
                                return `  Ocupación real: ${pct}%  |  Disponible: ${avail}h`;
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

    fmtH(n) { return (n || 0).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + 'h'; }

    wcKpiTooltip(key) {
        const k = this.state.kpis;
        const h = v => this.fmtH(v);
        switch (key) {
            case 'disponible':
                return `Horas calendario disponibles según el horario de trabajo configurado en cada CT\n→ ${h(k.disponible)} disponibles en el período`;
            case 'planificado':
                return `Suma de horas asignadas en órdenes de trabajo confirmadas o en progreso\n→ ${h(k.planificado)} planificadas de ${h(k.disponible)} disponibles`;
            case 'carga_pct':
                return `Planificado ÷ Disponible × 100\n→ ${h(k.planificado)} ÷ ${h(k.disponible)} × 100 = ${k.carga_pct}%\nVerde < 80% | Amarillo 80–100% | Rojo > 100%`;
            case 'ejecutado':
                return `Horas efectivamente trabajadas y registradas en órdenes de trabajo completadas\n→ ${h(k.ejecutado)} ejecutadas de ${h(k.planificado)} planificadas`;
            case 'pendiente':
                return `Planificado − Ejecutado\n→ ${h(k.planificado)} − ${h(k.ejecutado)} = ${h(k.pendiente)} pendientes`;
            case 'tiempo_libre':
                return `Disponible − Planificado\n→ ${h(k.disponible)} − ${h(k.planificado)} = ${h(k.tiempo_libre)} sin asignar`;
        }
        return '';
    }

    cargaClass(pct) {
        if (pct >= 90) return "text-danger fw-bold";
        if (pct >= 70) return "text-warning fw-bold";
        return "text-success fw-bold";
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChartWidget,
});
