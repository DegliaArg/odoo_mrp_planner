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

        // Barra "plan": Planificado (plan prorrateado al período) + capacidad sin planificar.
        // Barra "real": Ejecutado dentro del plan + Pendiente + No planificado (el exceso).
        // "No planificado" es un subconjunto del ejecutado: se resta del segmento
        // "Ejecutado" para no contarlo dos veces (la barra mide ejecutado + pendiente).
        const sinPlanificar   = data.available_hours.map((a, i) => Math.max(0, a - data.planificado[i]));
        const ejecutadoEnPlan = data.ejecutado.map((e, i) => Math.max(0, e - data.no_planificado[i]));

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
                        data: ejecutadoEnPlan,
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
                                const ejec  = data.ejecutado[i];
                                const carga = avail > 0 ? Math.round(plan / avail * 100) : 0;
                                return `  Carga: ${carga}%  |  Disponible: ${avail}h  |  Ejecutado total: ${ejec}h`;
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
        const MODE_LABELS = {
            finish_date:  'por fecha de cierre',
            start_date:   'por fecha de inicio',
            overlap:      'por solapamiento completo',
            proportional: 'proporcional por duración',
        };
        const modeNote = `\nCriterio de asignación: ${MODE_LABELS[k.date_mode] || 'por fecha de cierre'} (el mismo de la comparativa y el forecast, configurable en Ajustes).`;
        switch (key) {
            case 'disponible':
                return `Horas del calendario laboral de cada CT en el período, descontando feriados y licencias\n→ ${h(k.disponible)} disponibles`;
            case 'planificado':
                return `Horas planificadas (duration_expected) de las OT asignadas al período\n→ ${h(k.planificado)} planificadas de ${h(k.disponible)} disponibles` + modeNote;
            case 'carga_pct':
                return `Porcentaje de la capacidad disponible que se planificó\nPlanificado ÷ Disponible × 100\n→ ${h(k.planificado)} ÷ ${h(k.disponible)} × 100 = ${k.carga_pct}%\nAmarillo ≥ ${k.warn_pct || 70}% | Rojo ≥ ${k.crit_pct || 90}% (configurable en Ajustes)`;
            case 'ejecutado':
                return `Horas reales trabajadas de las OT asignadas al período (incluye OT en progreso)\n→ ${h(k.ejecutado)} ejecutadas` + modeNote;
            case 'pendiente':
                return `Plan del período aún no ejecutado, de OT abiertas\nΣ max(0, plan del período − real del período)\n→ ${h(k.pendiente)} pendientes` + modeNote;
            case 'no_planificado':
                return `Ejecución del período que superó (o no tenía) plan\nΣ max(0, real del período − plan del período)\n→ ${h(k.no_planificado)} fuera del plan`;
        }
        return '';
    }

    cargaClass(pct) {
        const warn = this.state.kpis.warn_pct || 70;
        const crit = this.state.kpis.crit_pct || 90;
        if (pct >= crit) return "text-danger fw-bold";
        if (pct >= warn) return "text-warning fw-bold";
        return "text-success fw-bold";
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChartWidget,
});
