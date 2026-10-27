/** @odoo-module **/

/**
 * @widget ManagementOverviewWidget
 * @description Panel de Gerencia (Resumen diario). Consolida en una sola
 * vista los indicadores que el CEO recibe a diario por mail, para el mes
 * seleccionado (por defecto, el mes en curso):
 *   - Facturado del mes (piezas + monto) con variación diaria.
 *   - Despachos del mes (piezas, estado Hecho) con variación diaria.
 *   - Embalajes / Picking pendientes AHORA (foto del estado Asignado).
 *   - Demanda del mes por categoría de producto (tabla + dona).
 *   - Producido del mes por categoría de producto (tabla + dona).
 *
 * Mantiene la estética del resto de paneles del módulo: tarjetas o_planner_card,
 * números o_planner_number, títulos de sección en mayúsculas, carga diferida de
 * Chart.js y colores de los gráficos leídos del tema (modo claro/oscuro).
 *
 * Método RPC que consume:
 *   - get_management_overview(month) → objeto consolidado (ver backend).
 *
 * Props: { record: Object } (requerido por la infraestructura de widgets).
 */

import { Component, useState, useRef, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

/** Paleta de la dona por categoría — misma que el resto de los paneles. */
const DONUT_COLORS = [
    "rgba(13, 110, 253, 0.80)", "rgba(25, 135, 84, 0.80)",
    "rgba(255, 193, 7,  0.85)", "rgba(220, 53,  69, 0.75)",
    "rgba(108, 117, 125, 0.75)", "rgba(102, 16, 242, 0.70)",
    "rgba(253, 126, 20, 0.75)", "rgba(32, 201, 151, 0.75)",
    "rgba(214, 51, 132, 0.75)", "rgba(13, 202, 240, 0.75)",
];
/** Máximo de categorías con color propio en la dona; el resto va a "Otras". */
const DONUT_TOP = 8;

/**
 * Colores dependientes del tema (claro/oscuro). Chart.js pinta sobre <canvas>
 * y no hereda CSS, así que se leen las variables de Bootstrap/Odoo al dibujar.
 * @returns {{text:string, muted:string, grid:string, bg:string}}
 */
function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (cs.getPropertyValue(name) || "").trim() || fallback;
    return {
        text:  v("--bs-body-color",      "#212529"),
        muted: v("--bs-secondary-color", "#6c757d"),
        grid:  v("--bs-border-color",    "rgba(0,0,0,0.1)"),
        bg:    v("--bs-tertiary-bg",     "#ffffff"),
    };
}

class ManagementOverviewWidget extends Component {
    static template = "odoo_mrp_planner.ManagementOverviewWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.demandRef = useRef("demandCanvas");
        this.producedRef = useRef("producedCanvas");
        this._demandChart = null;
        this._producedChart = null;

        const now = new Date();
        this.state = useState({
            loading: true,       // spinner de la primera carga
            reloading: false,    // recarga suave (contenido atenuado)
            error: null,
            month: this._monthStr(now),
            data: null,
        });

        onMounted(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                await this._load();
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
        });

        onPatched(() => {
            if (this.state.data && !this.state.loading) {
                this._drawDonut(this.demandRef, "_demandChart", this.state.data.demand);
                this._drawDonut(this.producedRef, "_producedChart", this.state.data.produced);
            }
        });

        onWillUnmount(() => {
            if (this._demandChart) { this._demandChart.destroy(); this._demandChart = null; }
            if (this._producedChart) { this._producedChart.destroy(); this._producedChart = null; }
        });
    }

    // ── Helpers de mes ───────────────────────────────────────────────────────

    _monthStr(d) {
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    }

    get isCurrentMonth() {
        return this.state.month === this._monthStr(new Date());
    }

    /** Etiqueta "Octubre 2026" del mes activo. */
    get monthLabel() {
        const [y, m] = this.state.month.split("-");
        const names = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                       "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
        return `${names[parseInt(m) - 1]} ${y}`;
    }

    onMonthChange(ev) {
        const v = ev.target.value;
        if (v && v !== this.state.month) { this.state.month = v; this._load(); }
    }

    setCurrentMonth() {
        const m = this._monthStr(new Date());
        if (this.state.month !== m) { this.state.month = m; this._load(); }
    }

    // ── Carga ────────────────────────────────────────────────────────────────

    async _load() {
        const first = !this.state.data;
        this.state.loading = first;
        this.state.reloading = !first;
        this.state.error = null;
        if (this._demandChart) { this._demandChart.destroy(); this._demandChart = null; }
        if (this._producedChart) { this._producedChart.destroy(); this._producedChart = null; }
        try {
            const data = await this.orm.call(
                "mrp.planner.dashboard", "get_management_overview", [this.state.month]);
            this.state.data = data;
        } catch (e) {
            console.error("[ManagementOverviewWidget]", e);
            this.state.error = e?.data?.message || e?.message || String(e);
        } finally {
            this.state.loading = false;
            this.state.reloading = false;
        }
    }

    // ── Formateo ─────────────────────────────────────────────────────────────

    fmt(v) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(v || 0);
    }

    money(v) {
        const sym = this.state.data?.currency || "$";
        return `${sym} ${new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(v || 0)}`;
    }

    /**
     * Describe la variación de hoy vs ayer para un indicador acumulable.
     * @param {{today:number, yesterday:number}} d
     * @returns {{show:boolean, today:number, dir:string, pct:(number|null)}}
     */
    delta(d) {
        if (!d) return { show: false };
        const today = d.today || 0, yest = d.yesterday || 0;
        const dir = today > yest ? "up" : (today < yest ? "down" : "flat");
        const pct = yest > 0 ? Math.round((today - yest) / yest * 100) : null;
        return { show: true, today, dir, pct };
    }

    get daily() { return this.state.data?.daily || {}; }
    get hasDaily() { return this.state.data?.is_current && !!this.state.data?.daily?.demand; }

    // ── Gráficos ─────────────────────────────────────────────────────────────

    /**
     * Dibuja una dona de distribución por categoría a partir de las filas de un
     * indicador. Toma las DONUT_TOP categorías de mayor cantidad y agrupa el
     * resto en "Otras".
     */
    _drawDonut(ref, attr, section) {
        const canvas = ref.el;
        if (!canvas) return;
        const ChartJs = globalThis.Chart;
        if (!ChartJs) return;
        if (this[attr]) { this[attr].destroy(); this[attr] = null; }

        const rows = (section?.rows || []).filter(r => (r.qty || 0) > 0);
        if (!rows.length) return;

        let entries = [...rows].sort((a, b) => b.qty - a.qty);
        if (entries.length > DONUT_TOP) {
            const head = entries.slice(0, DONUT_TOP);
            const otras = entries.slice(DONUT_TOP).reduce((s, e) => s + e.qty, 0);
            entries = [...head, { name: "Otras", qty: otras }];
        }
        const th = themeColors();
        const total = entries.reduce((s, e) => s + e.qty, 0);
        const fmtN = v => new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 }).format(v);

        this[attr] = new ChartJs(canvas, {
            type: "doughnut",
            data: {
                labels: entries.map(e => e.name),
                datasets: [{
                    data: entries.map(e => e.qty),
                    backgroundColor: entries.map((e, i) =>
                        e.name === "Otras" ? "rgba(173, 181, 189, 0.75)"
                                           : DONUT_COLORS[i % DONUT_COLORS.length]),
                    borderWidth: 1,
                    borderColor: th.bg,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "52%",
                plugins: {
                    legend: {
                        position: "right",
                        labels: { color: th.text, font: { size: 10 }, padding: 6, boxWidth: 12 },
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => {
                                const pct = total ? Math.round(ctx.raw / total * 100) : 0;
                                return `  ${fmtN(ctx.raw)} (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    }
}

registry.category("view_widgets").add("management_overview_widget", {
    component: ManagementOverviewWidget,
});
