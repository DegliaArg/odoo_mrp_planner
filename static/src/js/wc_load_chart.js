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
        this._root     = useRef("wcRoot");
        this.chart = null;
        this._chartData = null;

        const now = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth  = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            tags:            [],
            machines:        [],
            selectedTag:     "",
            selectedMachine: "",
            dateFrom:        toDateStr(firstOfMonth),
            dateTo:          toDateStr(lastOfMonth),
            loading:         false,
            empty:           false,
            kpis: { disponible: 0, planificado: 0, carga_pct: 0, ejecutado: 0, pendiente: 0, tiempo_libre: 0 },
        });

        onMounted(async () => {
            await loadBundle("web.chartjs_lib");
            await this._loadTags();    // sets default Vulcanizado + loads machines
            await this._loadChart();
            requestAnimationFrame(() => this._syncH());
        });

        onWillUnmount(() => {
            if (this.chart) { this.chart.destroy(); this.chart = null; }
        });
    }

    // ── Carga inicial ────────────────────────────────────────────────────────

    async _loadTags() {
        const tags = await this.orm.call("mrp.planner.dashboard", "get_wc_tags", []);
        this.state.tags = tags;
        // Sector por defecto: Vulcanizado
        const vulc = tags.find(t => t.name.toLowerCase().includes("vulcaniz"));
        if (vulc) this.state.selectedTag = String(vulc.id);
        await this._loadMachines();
    }

    async _loadMachines() {
        const tagId = this.state.selectedTag ? parseInt(this.state.selectedTag) : null;
        this.state.machines = await this.orm.call(
            "mrp.planner.dashboard", "get_wc_machines", [tagId]
        );
        this.state.selectedMachine = "";
    }

    async _loadChart() {
        if (!this.state.dateFrom || !this.state.dateTo) return;
        this.state.loading = true;
        this.state.empty   = false;
        let chartData = null;
        try {
            const tagId = this.state.selectedTag     ? parseInt(this.state.selectedTag)     : null;
            const wcId  = this.state.selectedMachine ? parseInt(this.state.selectedMachine) : null;
            chartData = await this.orm.call(
                "mrp.planner.dashboard",
                "get_wc_chart_data",
                [this.state.dateFrom, this.state.dateTo, tagId, wcId],
            );
            this._chartData = chartData;
            this.state.empty = !chartData.labels.length;
            if (chartData.totals) this.state.kpis = chartData.totals;
        } catch (e) {
            console.error("[WcLoadChart]", e);
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
        requestAnimationFrame(() => this._syncH());
    }

    _syncH() {
        const root = this._root.el;
        if (!root) return;
        const kpiEl   = root.querySelector('.o_kpi_height_src');
        const chartEl = root.querySelector('.o_table_scroll');
        if (!kpiEl || !chartEl) return;
        chartEl.style.height = '0';
        const h = kpiEl.offsetHeight;
        chartEl.style.height = Math.max(h, 150) + 'px';
        if (this.chart) this.chart.resize();
    }

    // ── Eventos de filtros ───────────────────────────────────────────────────

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; this._loadChart(); }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; this._loadChart(); }

    async onTagChange(ev) {
        this.state.selectedTag = ev.target.value;
        await this._loadMachines();
        this._loadChart();
    }

    onMachineChange(ev) {
        this.state.selectedMachine = ev.target.value;
        this._loadChart();
    }

    // ── Gráfico ──────────────────────────────────────────────────────────────

    _renderChart(data) {
        const canvas = this.canvasRef.el;
        if (!canvas || !window.Chart) return;
        if (this.chart) this.chart.destroy();

        const planificado   = data.ejecutado.map((e, i) => e + data.pendiente[i]);
        const tiempoLibre   = data.tiempo_muerto;
        const noplanificado = data.tiempo_muerto;

        this.chart = new window.Chart(canvas, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Planificado",
                        data: planificado,
                        backgroundColor: "rgba(13,110,253,0.60)",
                        borderColor: "rgba(13,110,253,0.90)",
                        borderWidth: 1, borderRadius: 2, stack: "plan",
                    },
                    {
                        label: "No planificado",
                        data: noplanificado,
                        backgroundColor: "rgba(200,200,200,0.35)",
                        borderColor: "rgba(160,160,160,0.50)",
                        borderWidth: 1, stack: "plan",
                    },
                    {
                        label: "Ejecutado",
                        data: data.ejecutado,
                        backgroundColor: "rgba(25,135,84,0.75)",
                        borderColor: "rgba(25,135,84,1)",
                        borderWidth: 1, stack: "real",
                    },
                    {
                        label: "Pendiente",
                        data: data.pendiente,
                        backgroundColor: "rgba(255,193,7,0.85)",
                        borderColor: "rgba(200,150,0,1)",
                        borderWidth: 1, stack: "real",
                    },
                    {
                        label: "Tiempo libre",
                        data: tiempoLibre,
                        backgroundColor: "rgba(255,153,153,0.50)",
                        borderColor: "rgba(220,80,80,0.70)",
                        borderWidth: 1, stack: "real",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (event, elements) => {
                    if (!elements.length) return;
                    const idx  = elements[0].index;
                    const wcId = this._chartData?.wc_ids?.[idx];
                    if (wcId) {
                        this.state.selectedMachine = String(wcId);
                        this._loadChart();
                    }
                },
                plugins: {
                    legend: {
                        display: true, position: "top",
                        labels: { boxWidth: 13, padding: 14, font: { size: 12 } },
                    },
                    tooltip: {
                        mode: "index", intersect: false,
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                if (v === 0) return null;
                                return `  ${ctx.dataset.label}: ${typeof v === "number" ? v.toFixed(2) : v}h`;
                            },
                            footer: (items) => {
                                const i     = items[0].dataIndex;
                                const avail = data.available_hours[i];
                                const used  = data.ejecutado[i] + data.pendiente[i];
                                const pct   = avail > 0 ? Math.round(used / avail * 100) : 0;
                                return `  Ocupación: ${pct}%  |  Disponible: ${avail}h  — Clic para filtrar`;
                            },
                        },
                        padding: 10, boxPadding: 4,
                    },
                },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 40 } },
                    y: {
                        stacked: true,
                        title: { display: true, text: "Horas", font: { size: 11 } },
                        ticks: { stepSize: 8 },
                    },
                },
            },
        });
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    fmtH(n) { return (n || 0).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "h"; }

    cargaClass(pct) {
        if (pct >= 90) return "text-danger fw-bold";
        if (pct >= 70) return "text-warning fw-bold";
        return "text-success fw-bold";
    }
}

registry.category("view_widgets").add("wc_load_chart", {
    component: WcLoadChartWidget,
});
