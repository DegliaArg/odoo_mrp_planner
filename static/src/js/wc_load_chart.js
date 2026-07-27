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
            kpis: { disponible: 0, planificado: 0, carga_pct: 0, ejecutado: 0, pendiente: 0, no_planificado: 0 },
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
        try {
            const res = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
            this.state.tags = res.tags || [];
        } catch (e) {
            if (e.message !== "Component is destroyed") {
                console.error("[WcLoadChart] Error al cargar tags:", e);
            }
        }
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
            if (e.message !== "Component is destroyed") {
                console.error("[WcLoadChart] Error al obtener datos:", e);
            }
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

        // Barra "plan": Planificado (duration_expected) + capacidad disponible sin planificar.
        // Barra "real": Ejecutado (duración real de las terminadas) + Pendiente + No planificado
        // (ejecución que superó el plan; puede exceder la capacidad).
        const sinPlanificar = data.available_hours.map((a, i) => Math.max(0, a - data.planificado[i]));

        this.chart = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Planificado",
                        data: data.planificado,
                        backgroundColor: "rgba(13,110,253,0.60)",
                        borderColor: "rgba(13,110,253,0.90)",
                        borderWidth: 1,
                        borderRadius: 2,
                        stack: "plan",
                    },
                    {
                        label: "Sin planificar",
                        data: sinPlanificar,
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
                        label: "No planificado",
                        data: data.no_planificado,
                        backgroundColor: "rgba(111,66,193,0.55)",
                        borderColor: "rgba(111,66,193,0.85)",
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
                                const plan  = data.planificado[i];
                                const carga = avail > 0 ? Math.round(plan / avail * 100) : 0;
                                return `  Carga: ${carga}%  |  Disponible: ${avail}h`;
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
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: "Horas",
                            font: { size: 11 },
                        },
                        ticks: {
                            callback: function(value) { return value + 'h'; },
                        },
                    },
                },
            },
        });
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) this.state.dateTo = this.state.dateFrom;
        this._loadChart();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) this.state.dateFrom = this.state.dateTo;
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
                return `Horas planificadas en las órdenes de trabajo del período (tiempo estándar, duration_expected), terminadas y pendientes\n→ ${h(k.planificado)} planificadas de ${h(k.disponible)} disponibles`;
            case 'carga_pct':
                return `Porcentaje de la capacidad disponible que se planificó\nPlanificado ÷ Disponible × 100\n→ ${h(k.planificado)} ÷ ${h(k.disponible)} × 100 = ${k.carga_pct}%\nVerde < 70% | Amarillo 70–89.9% | Rojo ≥ 90%`;
            case 'ejecutado':
                return `Suma de la duración REAL (workorder.duration) de las OT TERMINADAS cuya fecha de fin cae en el período\n→ ${h(k.ejecutado)} ejecutadas`;
            case 'pendiente':
                return `Horas estándar (duration_expected) de las OT NO terminadas que solapan el período\n→ ${h(k.pendiente)} pendientes`;
            case 'no_planificado':
                return `Tiempo real trabajado que superó lo planificado en las OT terminadas\nEjecutado − duración planificada de las terminadas\n→ ${h(k.no_planificado)} fuera del plan`;
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
