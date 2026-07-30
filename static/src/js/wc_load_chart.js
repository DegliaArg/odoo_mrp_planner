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
        const ASSIGN = {
            finish_date:  'una OT entra completa al período si su fecha de FIN cae dentro',
            start_date:   'una OT entra completa al período si su fecha de INICIO cae dentro',
            overlap:      'una OT entra completa al período si estuvo activa en algún momento del rango',
            proportional: 'cada OT aporta solo la fracción de su duración que cae dentro del período',
        };
        const assign = `Criterio de asignación: ${ASSIGN[k.date_mode] || ASSIGN.finish_date} (el mismo de la comparativa y el forecast; se cambia en Ajustes).`;
        switch (key) {
            case 'disponible':
                return `QUÉ ES: la capacidad teórica del centro de trabajo — cuántas horas puede trabajar en el período.`
                    + `\nCÓMO SE CALCULA: horas del horario laboral configurado en cada CT, descontando feriados y licencias del calendario.`
                    + `\nCÓMO LEERLO: es el techo contra el que se mide la carga; no depende de las órdenes de trabajo.`
                    + `\n→ ${h(k.disponible)} disponibles en el período`;
            case 'planificado':
                return `QUÉ ES: el trabajo comprometido — cuánta capacidad reservan las órdenes de trabajo del período.`
                    + `\nCÓMO SE CALCULA: suma del tiempo ESTÁNDAR (duration_expected) de cada OT asignada al período. Las OT en curso incluyen su plan completo: lo ya trabajado aparece en Ejecutado y lo restante en Pendiente.`
                    + `\nCÓMO LEERLO: compáralo contra Disponible — si lo supera, el plan no entra en la capacidad del CT.`
                    + `\n${assign}`
                    + `\n→ ${h(k.planificado)} planificadas de ${h(k.disponible)} disponibles`;
            case 'carga_pct':
                return `QUÉ ES: qué porcentaje de la capacidad del período está ocupado por el plan.`
                    + `\nCÓMO SE CALCULA: Planificado ÷ Disponible × 100 → ${h(k.planificado)} ÷ ${h(k.disponible)} = ${k.carga_pct}%.`
                    + `\nCÓMO LEERLO: cerca de 100% el CT está al límite; por encima, hay más plan que horas y algo se va a atrasar.`
                    + `\nAmarillo ≥ ${k.warn_pct || 70}% | Rojo ≥ ${k.crit_pct || 90}% (umbrales configurables en Ajustes)`;
            case 'ejecutado':
                return `QUÉ ES: el trabajo que realmente se hizo en el período.`
                    + `\nCÓMO SE CALCULA: suma de la duración REAL registrada en las OT asignadas al período — terminadas Y en progreso (estas aportan lo que llevan trabajado hasta ahora).`
                    + `\nCÓMO LEERLO: contra Planificado te dice si el CT va al ritmo del plan; puede superarlo (ver No planificado).`
                    + `\n${assign}`
                    + `\n→ ${h(k.ejecutado)} ejecutadas`;
            case 'pendiente':
                return `QUÉ ES: el trabajo comprometido que todavía falta hacer.`
                    + `\nCÓMO SE CALCULA: por cada OT abierta del período, max(0, plan − real ya trabajado). Una OT en curso se parte: lo trabajado está en Ejecutado y esto es su resto.`
                    + `\nCÓMO LEERLO: es la cola de trabajo del CT — si Pendiente + Ejecutado supera Disponible, no llega.`
                    + `\n${assign}`
                    + `\n→ ${h(k.pendiente)} pendientes`;
            case 'no_planificado':
                return `QUÉ ES: horas trabajadas que el plan no preveía.`
                    + `\nCÓMO SE CALCULA: por cada OT, max(0, real − plan), sin netear entre OT (una que ahorró horas no tapa a otra que se pasó).`
                    + `\nCÓMO LEERLO: mide el desvío contra los estándares. Incluye OT trabajadas SIN duración esperada cargada — si es alto, revisá los tiempos estándar de las rutas.`
                    + `\n→ ${h(k.no_planificado)} fuera del plan`;
        }
        return '';
    }

    /** Explicación de los segmentos de las barras, para el ícono ⓘ del gráfico. */
    chartInfoTooltip() {
        return `Cada CT tiene dos barras:`
            + `\n• Barra PLAN — Planificado (azul): tiempo estándar comprometido en el período. Sin planificar (gris): capacidad disponible que quedó libre.`
            + `\n• Barra REAL — Ejecutado (verde): trabajo hecho dentro del plan. Pendiente (amarillo): lo que falta del plan. No planificado (violeta): horas trabajadas que excedieron el plan o no tenían estándar.`
            + `\nLa altura de la barra REAL = horas ejecutadas + pendientes. Si supera a la barra PLAN, el CT trabajó más de lo planificado.`
            + `\nEl detalle de cada concepto está en los tooltips de las tarjetas de la izquierda.`;
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
