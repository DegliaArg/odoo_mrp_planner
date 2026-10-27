/** @odoo-module **/

/**
 * @widget ManagementOverviewWidget
 * @description Panel de Gerencia (Resumen diario). Consolida en una sola vista
 * los indicadores que el CEO recibe a diario por mail, para el mes seleccionado
 * (por defecto, el mes en curso):
 *   - Facturado del mes (piezas + monto) con variación diaria.
 *   - Despachos del mes (piezas, estado Hecho) con variación diaria.
 *   - Embalajes / Picking pendientes AHORA (foto del estado Asignado).
 *   - Demanda del mes por categoría de producto (tabla).
 *   - Producido del mes por categoría de producto (tabla).
 *
 * Mantiene la estética del resto de paneles del módulo: tarjetas o_planner_card,
 * números o_planner_number y títulos de sección en mayúsculas.
 *
 * Método RPC que consume:
 *   - get_management_overview(month) → objeto consolidado (ver backend).
 *
 * Props: { record: Object } (requerido por la infraestructura de widgets).
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class ManagementOverviewWidget extends Component {
    static template = "odoo_mrp_planner.ManagementOverviewWidget";
    static props = {
        record: { type: Object },
        "*": true,
    };

    setup() {
        this.orm = useService("orm");

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
                await this._load();
            } catch (e) {
                if (e.message !== "Component is destroyed") throw e;
            }
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
     * Variación de hoy vs ayer para un indicador acumulable, en términos
     * LINEALES (hoy − ayer), sin porcentuales.
     * @param {{today:number, yesterday:number}} d
     * @returns {{show:boolean, today:number, diff:number, absDiff:number, dir:string}}
     */
    delta(d) {
        if (!d) return { show: false };
        const today = d.today || 0, yest = d.yesterday || 0;
        const diff = today - yest;
        return {
            show: true,
            today,
            diff,
            absDiff: Math.abs(diff),
            dir: diff > 0 ? "up" : (diff < 0 ? "down" : "flat"),
        };
    }

    get daily() { return this.state.data?.daily || {}; }
    get hasDaily() { return this.state.data?.is_current && !!this.state.data?.daily?.demand; }

    /**
     * Ancho (%) de la barrita de fondo de una fila, relativo al mayor valor de
     * la columna. Usa el monto si la tabla lo muestra; si no, las piezas.
     * @param {Object} row
     * @param {Array} rows
     * @param {boolean} withAmount
     * @returns {number} 0–100
     */
    barPct(row, rows, withAmount) {
        const f = withAmount ? "amount" : "qty";
        const max = Math.max(...rows.map(r => Math.abs(r[f] || 0)), 0);
        const v = Math.abs(row[f] || 0);
        return max > 0 ? Math.max(2, Math.round(v / max * 100)) : 0;
    }
}

registry.category("view_widgets").add("management_overview_widget", {
    component: ManagementOverviewWidget,
});
