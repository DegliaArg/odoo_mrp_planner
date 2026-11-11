/**
 * production_needs_widget.js (odoo_mrp_planner_scheduling)
 *
 * Panel 1 — Motor de necesidades de producción.
 *
 * Muestra, para un mes a programar y una ventana de promedio de forecast, la
 * necesidad neta y la cantidad sugerida a fabricar por artículo (replica la
 * hoja PLANIFICACION del Excel). Desde cada fila con estado "PROGRAMAR" (o la
 * selección múltiple) se dispara la OF del producto terminado; las OF/OC de los
 * componentes las genera Odoo hacia atrás por las rutas de abastecimiento.
 *
 *   RPC: mrp.production.needs.get_needs_data(targetMonth, dateFrom, dateTo, warehouseId)
 *        mrp.production.needs.action_generate_mo(items, warehouseId)
 *
 * Reutiliza el formateador de números es-AR del módulo base para mantener la
 * estética de los demás paneles. El filtrado por texto/estado y el orden se
 * aplican client-side sobre state.rows.
 */
/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { fmt } from "@odoo_mrp_planner/js/forecast_formatters";

function toDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function firstOfMonth(offset = 0) {
    const d = new Date();
    return toDateStr(new Date(d.getFullYear(), d.getMonth() + offset, 1));
}

// Columnas numéricas de la tabla (clave → etiqueta corta + ayuda).
const COLS = [
    { key: "stock_position", label: "Posición", title: "Cantidad pronosticada (a la mano + entrante − saliente) del almacén." },
    { key: "avg_forecast",   label: "Prom. fc", title: "Promedio de forecast = suma de la ventana / Nº de meses de la ventana." },
    { key: "month_forecast", label: "Fc mes",   title: "Forecast del mes a programar." },
    { key: "safety_stock",   label: "Stock seg.", title: "ROUNDUP(promedio × factor de seguridad)." },
    { key: "target_stock",   label: "Objetivo", title: "Stock de seguridad + forecast del mes." },
    { key: "net_need",       label: "Necesidad", title: "MAX(0, objetivo − posición)." },
    { key: "suggested_qty",  label: "A fabricar", title: "Cantidad sugerida: MAX(mínimo por turno, necesidad). Sólo producción interna." },
    { key: "coverage_now",   label: "Cob. (m)", title: "Cobertura actual en meses = posición / promedio de forecast." },
];

export class ProductionNeedsWidget extends Component {
    static template = "odoo_mrp_planner_scheduling.ProductionNeedsWidget";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.cols = COLS;

        this.state = useState({
            targetMonth: firstOfMonth(0),
            dateFrom: firstOfMonth(-5),
            dateTo: firstOfMonth(0),
            warehouseId: false,
            warehouses: [],
            search: "",
            stateFilter: "all",
            rows: [],
            kpis: {},
            meta: {},
            sortCol: "suggested_qty",
            sortDir: "desc",
            selected: {},   // {product_id: true}
            loading: false,
            generating: false,
        });

        onWillStart(async () => {
            this.state.warehouses = await this.orm.searchRead(
                "stock.warehouse", [], ["id", "name"]);
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        try {
            const res = await this.orm.call(
                "mrp.production.needs", "get_needs_data",
                [this.state.targetMonth, this.state.dateFrom, this.state.dateTo,
                 this.state.warehouseId || false]);
            this.state.rows = res.rows || [];
            this.state.kpis = res.kpis || {};
            this.state.meta = res.meta || {};
            this.state.selected = {};
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filtros ─────────────────────────────────────────────────────────────
    onFilterChange(field, ev) {
        this.state[field] = ev.target.value;
        this.load();
    }
    onWarehouseChange(ev) {
        const v = ev.target.value;
        this.state.warehouseId = v ? parseInt(v, 10) : false;
        this.load();
    }
    setStateFilter(f) { this.state.stateFilter = f; }

    // ── Orden ───────────────────────────────────────────────────────────────
    sortBy(col) {
        if (this.state.sortCol === col) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortCol = col;
            this.state.sortDir = "desc";
        }
    }

    get visibleRows() {
        let rows = [...this.state.rows];
        const q = (this.state.search || "").trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                (r.name || "").toLowerCase().includes(q) ||
                (r.code || "").toLowerCase().includes(q));
        }
        const f = this.state.stateFilter;
        if (f === "programar") rows = rows.filter(r => (r.state || "").includes("PROGRAMAR"));
        else if (f === "revisar") rows = rows.filter(r => (r.state || "").includes("REVISAR"));
        else if (f === "necesidad") rows = rows.filter(r => (r.net_need || 0) > 0);

        const col = this.state.sortCol;
        const dir = this.state.sortDir === "asc" ? 1 : -1;
        rows.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (typeof va === "string" || typeof vb === "string") {
                return dir * String(va || "").localeCompare(String(vb || ""));
            }
            va = va == null ? -Infinity : va;
            vb = vb == null ? -Infinity : vb;
            return dir * (va - vb);
        });
        return rows;
    }

    // ── Formateo / estilos ──────────────────────────────────────────────────
    f(n) { return n == null ? "—" : fmt(n); }

    stateClass(state) {
        const s = state || "";
        if (s.includes("PROGRAMAR")) return "text-bg-success";
        if (s === "STOCK SUFICIENTE") return "text-bg-light border";
        if (s === "NO FABRICAR") return "text-bg-secondary";
        if (s.includes("REVISAR") || s === "SIN FORECAST") return "text-bg-warning";
        return "text-bg-light border";
    }

    // ── Selección ───────────────────────────────────────────────────────────
    isSelectable(row) { return (row.suggested_qty || 0) > 0; }
    toggleRow(row) {
        if (!this.isSelectable(row)) return;
        if (this.state.selected[row.product_id]) delete this.state.selected[row.product_id];
        else this.state.selected[row.product_id] = true;
    }
    toggleAll() {
        const sel = this.selectedCount;
        if (sel > 0) { this.state.selected = {}; return; }
        const next = {};
        for (const r of this.visibleRows) if (this.isSelectable(r)) next[r.product_id] = true;
        this.state.selected = next;
    }
    get selectedCount() { return Object.keys(this.state.selected).length; }

    // ── Disparo de OF ───────────────────────────────────────────────────────
    async _generate(items) {
        if (!items.length) {
            this.notification.add("No hay artículos con cantidad a fabricar.", { type: "warning" });
            return;
        }
        this.state.generating = true;
        try {
            const act = await this.orm.call(
                "mrp.production.needs", "action_generate_mo",
                [items, this.state.warehouseId || false]);
            this.notification.add(
                `${items.length} orden(es) de fabricación generada(s).`, { type: "success" });
            if (act) await this.action.doAction(act);
        } finally {
            this.state.generating = false;
        }
    }
    async generateRow(row) {
        await this._generate([{ product_id: row.product_id, qty: row.suggested_qty }]);
    }
    async generateSelected() {
        const items = this.state.rows
            .filter(r => this.state.selected[r.product_id] && (r.suggested_qty || 0) > 0)
            .map(r => ({ product_id: r.product_id, qty: r.suggested_qty }));
        await this._generate(items);
    }
}

registry.category("view_widgets").add("production_needs_widget", {
    component: ProductionNeedsWidget,
});
