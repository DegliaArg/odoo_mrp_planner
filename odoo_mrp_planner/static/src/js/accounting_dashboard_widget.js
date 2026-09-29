/** @odoo-module **/

/**
 * @widget AccountingDashboardWidget
 * @description Panel de contabilidad del dashboard MRP. Muestra los KPIs
 * generales de FACTURACIÓN real (facturas de cliente posteadas, neto sin
 * impuestos, en moneda de la compañía, con las notas de crédito restando):
 * cards de cabecera, evolución mensual (12 meses), mix por familia y por
 * categoría de venta ABC, top clientes y facturación por vendedor.
 *
 * Respeta el selector nativo multiempresa de Odoo: el backend agrega sobre
 * self.env.companies (las compañías activas del switcher).
 *
 * Métodos RPC que consume:
 *   - get_accounting_filter_options([]) → { families:[{id,name}], sale_categories:[str] }
 *   - get_accounting_dashboard_data(date_from, date_to, family_id, sale_category)
 *       → { kpis, by_family, by_sale_category, top_customers, by_salesperson, evolution }
 *
 * Props esperados:
 *   - record: Object — registro activo del dashboard (requerido por la
 *     infraestructura de widgets de vista).
 */

import { Component, useState, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

/** Paleta ABC de venta (misma que el panel de ventas, para consistencia). */
const CAT_COLORS = {
    A: "rgba(25, 135, 84, 0.80)",
    B: "rgba(13, 110, 253, 0.80)",
    C: "rgba(255, 193, 7, 0.85)",
    D: "rgba(108, 117, 125, 0.80)",
    E: "rgba(200, 210, 220, 0.90)",
    "": "rgba(108, 117, 125, 0.65)",
};

/** Paleta cíclica para las familias (mismos colores que la dona de ventas). */
const FAMILY_COLORS = [
    "rgba(13, 110, 253, 0.80)",  "rgba(25, 135, 84, 0.80)",
    "rgba(255, 193, 7, 0.85)",   "rgba(214, 51, 132, 0.80)",
    "rgba(102, 16, 242, 0.78)",  "rgba(253, 126, 20, 0.82)",
    "rgba(32, 201, 151, 0.80)",  "rgba(111, 66, 193, 0.78)",
];

/** Convierte Date → 'YYYY-MM-DD' (compatible con los campos Date de Odoo). */
function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Plugin de Chart.js: dibuja el % de cada segmento sobre la dona (>=5%). */
const PIE_LABEL_PLUGIN = {
    id: "acctPieLabels",
    afterDatasetsDraw(chart) {
        const { ctx, data } = chart;
        const dataset = data.datasets[0];
        const ttl = dataset.data.reduce((a, b) => a + b, 0);
        chart.getDatasetMeta(0).data.forEach((arc, i) => {
            const pct = ttl ? Math.round(dataset.data[i] / ttl * 100) : 0;
            if (pct < 5) return;
            const { x, y } = arc.getCenterPoint();
            ctx.save();
            ctx.fillStyle = "#fff";
            ctx.font = "bold 11px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.shadowColor = "rgba(0,0,0,0.35)";
            ctx.shadowBlur = 3;
            ctx.fillText(`${pct}%`, x, y);
            ctx.restore();
        });
    },
};

class AccountingDashboardWidget extends Component {
    static template = "odoo_mrp_planner.AccountingDashboardWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.evoRef = useRef("evoCanvas");
        this.famRef = useRef("famCanvas");
        this.catRef = useRef("catCanvas");
        this.funnelRef = useRef("funnelCanvas");
        this._evo = null;
        this._fam = null;
        this._cat = null;
        this._funnel = null;

        const now = new Date();
        const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        this.state = useState({
            loading: true,
            loadError: null,
            dateFrom: toDateStr(firstOfMonth),
            dateTo: toDateStr(lastOfMonth),
            familyId: "",
            saleCategory: "",
            families: [],
            // Métrica de las donas de mix: 'amount' ($) o 'qty' (cantidad facturada).
            mixMetric: "amount",
            data: null,
        });

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                const [opts] = await Promise.all([
                    this.orm.call("mrp.planner.dashboard", "get_accounting_filter_options", []),
                    this._load(),
                ]);
                this.state.families = (opts && opts.families) || [];
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });

        onPatched(() => {
            if (!this.state.loading && this.state.data) {
                if (this.evoRef.el) this._drawEvolution();
                if (this.famRef.el) this._drawFamilyPie();
                if (this.catRef.el) this._drawSaleCatPie();
                if (this.funnelRef.el) this._drawFunnel();
            }
        });

        onWillUnmount(() => {
            if (this._evo) { this._evo.destroy(); this._evo = null; }
            if (this._fam) { this._fam.destroy(); this._fam = null; }
            if (this._cat) { this._cat.destroy(); this._cat = null; }
            if (this._funnel) { this._funnel.destroy(); this._funnel = null; }
        });
    }

    // ── Formato ──────────────────────────────────────────────────────────────

    /** Importe en pesos, sin decimales (montos grandes de facturación). */
    fmtAmt(v) {
        return "$ " + new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(v || 0);
    }

    /** Importe con 2 decimales (ticket promedio). */
    fmtAmt2(v) {
        return "$ " + new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);
    }

    fmtPct(v) {
        return (v === null || v === undefined) ? "—" : new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v) + "%";
    }

    fmtInt(v) {
        return new Intl.NumberFormat("es-AR").format(v || 0);
    }

    /** Cantidad facturada (unidades). Las UdM pueden diferir entre familias:
     * el total es referencial, igual que en el panel de inventario. */
    fmtQty(v) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(v || 0) + " u.";
    }

    /** Valor de una fila de mix según la métrica activa. */
    mixVal(row) {
        return this.state.mixMetric === "qty" ? row.qty : row.amount;
    }

    /** % de una fila de mix según la métrica activa. */
    mixPct(row) {
        return this.state.mixMetric === "qty" ? row.pct_qty : row.pct;
    }

    /** Formatea un valor de mix según la métrica activa ($ o unidades). */
    fmtMix(v) {
        return this.state.mixMetric === "qty" ? this.fmtQty(v) : this.fmtAmt(v);
    }

    /** Cambia la métrica de las donas de mix y las redibuja (sin recargar). */
    setMixMetric(m) {
        if (this.state.mixMetric !== m) { this.state.mixMetric = m; }
    }

    /** Etiqueta 'YYYY-MM' → 'mmm aa' (ej. 'ene 25') para los ejes/tooltips. */
    monthLabel(ym) {
        const [y, m] = ym.split("-");
        const names = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
        return `${names[parseInt(m, 10) - 1]} ${y.slice(2)}`;
    }

    /** Clase de color para el Δ% (verde sube, rojo baja). */
    get deltaClass() {
        const d = this.state.data?.kpis?.delta_pct;
        if (d === null || d === undefined) return "text-muted";
        return d >= 0 ? "text-success" : "text-danger";
    }

    get deltaLabel() {
        const d = this.state.data?.kpis?.delta_pct;
        if (d === null || d === undefined) return "s/ período anterior";
        const sign = d >= 0 ? "▲ +" : "▼ ";
        return `${sign}${this.fmtPct(Math.abs(d))} vs período anterior`;
    }

    // ── Filtros ────────────────────────────────────────────────────────────────

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom > this.state.dateTo) this.state.dateTo = this.state.dateFrom;
        this._load();
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateTo < this.state.dateFrom) this.state.dateFrom = this.state.dateTo;
        this._load();
    }

    setCurrentMonth() {
        const now = new Date();
        this.state.dateFrom = toDateStr(new Date(now.getFullYear(), now.getMonth(), 1));
        this.state.dateTo = toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));
        this._load();
    }

    get isCurrentMonth() {
        const now = new Date();
        return this.state.dateFrom === toDateStr(new Date(now.getFullYear(), now.getMonth(), 1))
            && this.state.dateTo === toDateStr(new Date(now.getFullYear(), now.getMonth() + 1, 0));
    }

    onFamilyChange(ev) {
        const v = ev.target.value;
        if (this.state.familyId !== v) { this.state.familyId = v; this._load(); }
    }

    setSaleCat(c) {
        if (this.state.saleCategory !== c) { this.state.saleCategory = c; this._load(); }
    }

    // ── Carga ────────────────────────────────────────────────────────────────

    async _load() {
        this.state.loading = true;
        this.state.loadError = null;
        if (this._evo) { this._evo.destroy(); this._evo = null; }
        if (this._fam) { this._fam.destroy(); this._fam = null; }
        if (this._cat) { this._cat.destroy(); this._cat = null; }
        if (this._funnel) { this._funnel.destroy(); this._funnel = null; }
        try {
            const data = await this.orm.call(
                "mrp.planner.dashboard",
                "get_accounting_dashboard_data",
                [this.state.dateFrom, this.state.dateTo,
                 this.state.familyId || null, this.state.saleCategory || null],
            );
            this.state.data = data || null;
        } catch (e) {
            console.error("[AccountingDashboardWidget]", e);
            this.state.data = null;
            this.state.loadError = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    // ── Gráficos ────────────────────────────────────────────────────────────────

    _drawEvolution() {
        const canvas = this.evoRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._evo) { this._evo.destroy(); this._evo = null; }

        const rows = this.state.data.evolution || [];
        const labels = rows.map(r => this.monthLabel(r.ym));
        const data = rows.map(r => r.amount);

        this._evo = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Facturación neta",
                    data,
                    backgroundColor: "rgba(13, 110, 253, 0.75)",
                    borderRadius: 3,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => this.fmtAmt(ctx.raw) } },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 11 } } },
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.06)" },
                        ticks: {
                            font: { size: 11 },
                            callback: v => new Intl.NumberFormat("es-AR", { notation: "compact", maximumFractionDigits: 1 }).format(v),
                        },
                    },
                },
            },
        });
    }

    _drawFamilyPie() {
        const canvas = this.famRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._fam) { this._fam.destroy(); this._fam = null; }

        const rows = this.state.data.by_family || [];
        if (!rows.length) return;
        const colors = rows.map((r, i) => r.name === "Otros"
            ? "rgba(173, 181, 189, 0.75)"
            : FAMILY_COLORS[i % FAMILY_COLORS.length]);

        this._fam = new ChartJs(canvas, {
            type: "doughnut",
            data: {
                labels: rows.map(r => r.name),
                datasets: [{
                    data: rows.map(r => this.mixVal(r)),
                    backgroundColor: colors,
                    borderWidth: 1,
                    borderColor: "#fff",
                }],
            },
            plugins: [PIE_LABEL_PLUGIN],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "48%",
                plugins: {
                    legend: { position: "bottom", labels: { font: { size: 10 }, padding: 5, boxWidth: 12 } },
                    tooltip: {
                        callbacks: {
                            label: ctx => `  ${this.fmtMix(this.mixVal(rows[ctx.dataIndex]))} (${this.fmtPct(this.mixPct(rows[ctx.dataIndex]))})`,
                        },
                    },
                },
            },
        });
    }

    _drawSaleCatPie() {
        const canvas = this.catRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._cat) { this._cat.destroy(); this._cat = null; }

        const rows = this.state.data.by_sale_category || [];
        if (!rows.length) return;
        const colors = rows.map(r => CAT_COLORS[r.code === "__none__" ? "" : r.code] ?? CAT_COLORS[""]);

        this._cat = new ChartJs(canvas, {
            type: "doughnut",
            data: {
                labels: rows.map(r => r.name),
                datasets: [{
                    data: rows.map(r => this.mixVal(r)),
                    backgroundColor: colors,
                    borderWidth: 1,
                    borderColor: "#fff",
                }],
            },
            plugins: [PIE_LABEL_PLUGIN],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "48%",
                plugins: {
                    legend: { position: "bottom", labels: { font: { size: 11 }, padding: 6, boxWidth: 14 } },
                    tooltip: {
                        callbacks: {
                            label: ctx => `  ${this.fmtMix(this.mixVal(rows[ctx.dataIndex]))} (${this.fmtPct(this.mixPct(rows[ctx.dataIndex]))})`,
                        },
                    },
                },
            },
        });
    }

    /**
     * Embudo del período (unidades): Pedido → Entregado → Facturado, como
     * barras horizontales. Las conversiones se muestran aparte en el template.
     */
    _drawFunnel() {
        const canvas = this.funnelRef.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this._funnel) { this._funnel.destroy(); this._funnel = null; }

        const f = this.state.data.funnel || {};
        const labels = ["Pedido", "Entregado", "Facturado"];
        const data = [f.ordered || 0, f.delivered || 0, f.invoiced || 0];
        const colors = [
            "rgba(108, 117, 125, 0.75)",
            "rgba(13, 110, 253, 0.75)",
            "rgba(25, 135, 84, 0.80)",
        ];

        this._funnel = new ChartJs(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors,
                    borderRadius: 3,
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => this.fmtQty(ctx.raw) } },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "rgba(0,0,0,0.06)" },
                        ticks: {
                            font: { size: 11 },
                            callback: v => new Intl.NumberFormat("es-AR", { notation: "compact", maximumFractionDigits: 1 }).format(v),
                        },
                    },
                    y: { grid: { display: false }, ticks: { font: { size: 12 } } },
                },
            },
        });
    }
}

registry.category("view_widgets").add("accounting_dashboard_widget", {
    component: AccountingDashboardWidget,
});
